#!/usr/bin/env python3
"""Skill Daemon -- persistent proxy process for stealth-browser API service.

Maintains a single long-lived aiohttp.ClientSession to the remote API service,
eliminating per-invocation TCP connection overhead.

Communication: Unix domain socket (~/.stealth-browser/skill-daemon.sock)
Protocol:      newline-delimited JSON-RPC
  Request:  {"id": "<uuid>", "method": "GET|POST|DELETE", "path": "/...", "json": {...}|null}
  Response: {"id": "<uuid>", "result": {...}} | {"id": "<uuid>", "error": "<msg>"}

Lifecycle:
  - Started automatically by cli.py on first command
  - Writes PID to ~/.stealth-browser/skill-daemon.pid
  - Auto-exits after IDLE_TIMEOUT seconds of inactivity (default 1800 = 30 min)
  - Cleans up stale socket on startup if previous PID is dead

Usage:
  python daemon.py [--config /path/to/config.yaml] [--idle-timeout 1800]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────────

_STATE_DIR = Path.home() / ".stealth-browser"

if platform.system() == "Windows":
    # Windows AF_UNIX paths must not contain colons; use %TEMP% as fallback
    _tmp = Path(os.environ.get("TEMP", str(Path.home())))
    DAEMON_SOCK = _tmp / "stealth-browser-daemon.sock"
else:
    DAEMON_SOCK = _STATE_DIR / "skill-daemon.sock"

PID_FILE = _STATE_DIR / "skill-daemon.pid"
LOG_FILE = _STATE_DIR / "skill-daemon.log"
LOCK_FILE = _STATE_DIR / "skill-daemon.lock"

DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes
DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 600

# ── Logging ────────────────────────────────────────────────────────────────────

# Ensure state directory exists before initializing file logging
_STATE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [daemon] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)


# ── Config loader ──────────────────────────────────────────────────────────────


def _load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load skill config.yaml.  Falls back to defaults if file missing."""
    # Default config path: same directory as this script
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    cfg: dict[str, Any] = {
        "api_url": DEFAULT_API_URL,
        "api_key": "",
        "timeout": DEFAULT_TIMEOUT,
    }

    if not config_path.exists():
        return cfg

    try:
        import yaml  # type: ignore[import-untyped]

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        svc = data.get("service", {})
        if isinstance(svc, dict):
            if svc.get("url"):
                cfg["api_url"] = str(svc["url"]).rstrip("/")
            if svc.get("api_key"):
                cfg["api_key"] = str(svc["api_key"])
            if svc.get("timeout"):
                try:
                    cfg["timeout"] = int(svc["timeout"])
                except (ValueError, TypeError):
                    pass
    except Exception as exc:
        logger.warning("Failed to load config %s: %s", config_path, exc)

    return cfg


# ── PID helpers ────────────────────────────────────────────────────────────────


def _is_pid_alive(pid: int) -> bool:
    if platform.system() == "Windows":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cleanup_stale() -> None:
    """Remove stale socket + PID file if previous daemon is dead."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if not _is_pid_alive(pid):
                logger.info("Removing stale PID file (pid=%d dead)", pid)
                PID_FILE.unlink(missing_ok=True)
                DAEMON_SOCK.unlink(missing_ok=True)
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)
            DAEMON_SOCK.unlink(missing_ok=True)
    elif DAEMON_SOCK.exists():
        # Socket without PID file — likely stale
        DAEMON_SOCK.unlink(missing_ok=True)


# ── Daemon ─────────────────────────────────────────────────────────────────────


class SkillDaemon:
    """Async Unix socket server that proxies requests to the API service."""

    def __init__(self, config: dict[str, Any], idle_timeout: int) -> None:
        self._cfg = config
        self._idle_timeout = idle_timeout
        self._http: Any = None  # aiohttp.ClientSession
        self._last_request: float = time.monotonic()
        self._stop_event = asyncio.Event()

    # ── HTTP session ───────────────────────────────────────────────────────────

    async def _ensure_http(self) -> None:
        import aiohttp

        if self._http is None or self._http.closed:
            connector = aiohttp.TCPConnector(
                limit=10,
                force_close=False,
                enable_cleanup_closed=True,
            )
            self._http = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self._cfg["timeout"]),
            )
            logger.info("Created aiohttp session → %s", self._cfg["api_url"])

    async def _proxy(self, method: str, path: str, body: dict | None) -> dict:
        """Forward request to API service, reusing the persistent session."""
        await self._ensure_http()
        headers: dict[str, str] = {}
        if self._cfg["api_key"]:
            headers["X-API-Key"] = self._cfg["api_key"]

        url = self._cfg["api_url"] + path
        try:
            async with self._http.request(method, url, json=body, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"API {resp.status}: {text}")
                if resp.content_length == 0:
                    return {}
                return await resp.json()
        except RuntimeError:
            raise
        except Exception as exc:
            # Connection error — close session so next call reconnects
            if self._http and not self._http.closed:
                await self._http.close()
                self._http = None
            raise RuntimeError(f"Connection error: {exc}") from exc

    # ── Request handler ────────────────────────────────────────────────────────

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one JSON-RPC request from cli.py."""
        self._last_request = time.monotonic()
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=30)
            if not raw:
                return
            req = json.loads(raw.decode())
            req_id = req.get("id", "")
            method = req.get("method", "GET").upper()
            path = req.get("path", "/")
            body = req.get("json")

            try:
                result = await self._proxy(method, path, body)
                resp = {"id": req_id, "result": result}
            except Exception as exc:
                resp = {"id": req_id, "error": str(exc)}

            writer.write(json.dumps(resp).encode() + b"\n")
            await writer.drain()
        except Exception as exc:
            logger.warning("handle error: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ── Idle watchdog ──────────────────────────────────────────────────────────

    async def _idle_watchdog(self) -> None:
        """Stop the daemon after idle_timeout seconds of inactivity."""
        while not self._stop_event.is_set():
            await asyncio.sleep(60)
            idle = time.monotonic() - self._last_request
            if idle >= self._idle_timeout:
                logger.info("Idle timeout reached (%.0fs), shutting down", idle)
                self._stop_event.set()

    # ── Run ────────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        server = await asyncio.start_unix_server(self.handle, str(DAEMON_SOCK))
        logger.info(
            "Skill daemon started (pid=%d, sock=%s, idle_timeout=%ds)",
            os.getpid(),
            DAEMON_SOCK,
            self._idle_timeout,
        )
        asyncio.create_task(self._idle_watchdog())
        async with server:
            await self._stop_event.wait()

        logger.info("Skill daemon stopping")
        if self._http and not self._http.closed:
            await self._http.close()


# ── Entry point ────────────────────────────────────────────────────────────────


async def _async_main(config_path: Path | None, idle_timeout: int) -> None:
    _cleanup_stale()

    # Ensure state directory exists
    _STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    try:
        cfg = _load_config(config_path)
        daemon = SkillDaemon(cfg, idle_timeout)
        await daemon.run()
    finally:
        PID_FILE.unlink(missing_ok=True)
        DAEMON_SOCK.unlink(missing_ok=True)
        logger.info("Skill daemon exited cleanly")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stealth Browser Skill Daemon")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT,
        help="Seconds of inactivity before auto-exit (default 1800)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_async_main(args.config, args.idle_timeout))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
