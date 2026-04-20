#!/usr/bin/env python3
"""Skill CLI -- lightweight CLI client for stealth-browser skill.

Routes all browser commands through the Skill Daemon (Unix socket) for
persistent HTTP connection reuse.  Auto-starts the daemon on first call.

Usage (after install-skill creates the shim):
  stealth-browser open https://example.com --session default
  stealth-browser snapshot --session default -i
  stealth-browser click @e3 --session default
  stealth-browser fill @e1 "search term" --session default
  stealth-browser press Enter --session default
  stealth-browser extract --type text --session default
  stealth-browser run "find Python jobs" --session default --max-steps 10
  stealth-browser session create --name default
  stealth-browser session list
  stealth-browser session destroy default
  stealth-browser daemon status
  stealth-browser daemon stop

All commands output JSON: {"success": true, "data": {...}} or {"success": false, "error": "..."}
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).parent
DAEMON_PY = SKILL_DIR / "daemon.py"
CONFIG_YAML = SKILL_DIR / "config.yaml"
SESSION_CACHE = Path.home() / ".stealth-browser" / "skill-session.json"

if platform.system() == "Windows":
    _tmp = Path(os.environ.get("TEMP", str(Path.home())))
    DAEMON_SOCK = _tmp / "stealth-browser-daemon.sock"
else:
    DAEMON_SOCK = Path.home() / ".stealth-browser" / "skill-daemon.sock"

PID_FILE = Path.home() / ".stealth-browser" / "skill-daemon.pid"
LOCK_FILE = Path.home() / ".stealth-browser" / "skill-daemon.lock"

DAEMON_START_TIMEOUT = 5  # seconds to wait for daemon socket


# ── Output helpers ─────────────────────────────────────────────────────────────


def _ok(data: Any = None) -> None:
    print(json.dumps({"success": True, "data": data}, ensure_ascii=False))


def _err(msg: str) -> None:
    print(json.dumps({"success": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


# ── Session cache ──────────────────────────────────────────────────────────────

# Cache format: {"name": {"session_id": "...", "vnc_url": "..."}}
# Legacy format: {"name": "session_id_str"} — auto-migrated on load.


def _load_session_cache() -> dict[str, dict]:
    """Load session cache, migrating legacy str format to dict format."""
    try:
        if SESSION_CACHE.exists():
            raw = json.loads(SESSION_CACHE.read_text(encoding="utf-8"))
            migrated: dict[str, dict] = {}
            for key, value in raw.items():
                if isinstance(value, str):
                    migrated[key] = {"session_id": value, "vnc_url": ""}
                elif isinstance(value, dict):
                    migrated[key] = value
            return migrated
    except Exception:
        pass
    return {}


def _save_session_cache(cache: dict[str, dict]) -> None:
    SESSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _get_session_id(name: str | None) -> str | None:
    """Return cached session_id for the given name (or 'default')."""
    key = name or "default"
    entry = _load_session_cache().get(key)
    if isinstance(entry, dict):
        return entry.get("session_id")
    return None


def _get_vnc_url(name: str | None) -> str | None:
    """Return cached VNC URL for the given session name."""
    key = name or "default"
    entry = _load_session_cache().get(key)
    if isinstance(entry, dict):
        vnc = entry.get("vnc_url")
        return vnc if vnc else None
    return None


def _set_session_id(name: str | None, session_id: str, vnc_url: str = "") -> None:
    """Cache session_id and VNC URL for the given name."""
    key = name or "default"
    cache = _load_session_cache()
    cache[key] = {"session_id": session_id, "vnc_url": vnc_url}
    _save_session_cache(cache)


def _del_session_id(name: str | None) -> None:
    key = name or "default"
    cache = _load_session_cache()
    cache.pop(key, None)
    _save_session_cache(cache)


# ── Daemon management ──────────────────────────────────────────────────────────


def _is_socket_alive() -> bool:
    """Return True if the daemon socket exists and accepts connections."""
    if not DAEMON_SOCK.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(str(DAEMON_SOCK))
        s.close()
        return True
    except Exception:
        return False


def _ensure_daemon() -> None:
    """Start daemon if not running.  Uses a lock file to prevent races (Unix only)."""
    if _is_socket_alive():
        return

    if platform.system() == "Windows":
        _ensure_daemon_windows()
    else:
        _ensure_daemon_unix()


def _ensure_daemon_unix() -> None:
    """Unix: use fcntl.flock to prevent concurrent daemon startup."""
    import fcntl

    lock_fd = open(LOCK_FILE, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Another process is starting the daemon; wait for it
        lock_fd.close()
        deadline = time.monotonic() + DAEMON_START_TIMEOUT
        while time.monotonic() < deadline:
            if _is_socket_alive():
                return
            time.sleep(0.1)
        _err("Daemon failed to start (lock timeout)")
        return

    try:
        if _is_socket_alive():
            return  # Another process beat us to it

        args = [sys.executable, str(DAEMON_PY)]
        if CONFIG_YAML.exists():
            args += ["--config", str(CONFIG_YAML)]

        subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + DAEMON_START_TIMEOUT
        while time.monotonic() < deadline:
            if _is_socket_alive():
                return
            time.sleep(0.1)

        _err(f"Daemon failed to start within {DAEMON_START_TIMEOUT}s")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _ensure_daemon_windows() -> None:
    """Windows: no fcntl available; start daemon and wait for socket."""
    args = [sys.executable, str(DAEMON_PY)]
    if CONFIG_YAML.exists():
        args += ["--config", str(CONFIG_YAML)]

    subprocess.Popen(
        args,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + DAEMON_START_TIMEOUT
    while time.monotonic() < deadline:
        if _is_socket_alive():
            return
        time.sleep(0.1)

    _err(f"Daemon failed to start within {DAEMON_START_TIMEOUT}s")


# ── JSON-RPC transport ─────────────────────────────────────────────────────────


def _rpc(method: str, path: str, body: dict | None = None) -> dict:
    """Send one JSON-RPC request to the daemon and return the result."""
    _ensure_daemon()

    req = json.dumps(
        {"id": str(uuid.uuid4()), "method": method, "path": path, "json": body}
    ).encode() + b"\n"

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(120)
    try:
        s.connect(str(DAEMON_SOCK))
        s.sendall(req)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()

    resp = json.loads(buf.decode())
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp.get("result", {})


# ── Commands ───────────────────────────────────────────────────────────────────


def cmd_open(args: list[str]) -> None:
    """open <url> [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser open <url> [--session <name>]")
    url = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/navigate", {"url": url})

    output: dict[str, Any] = {"url": result.get("url", url), "title": result.get("title", "")}

    # Surface intervention detection from server
    if result.get("intervention"):
        output["intervention"] = result["intervention"]
        if result.get("vnc_url"):
            output["vnc_url"] = result["vnc_url"]
        else:
            vnc_url = _get_vnc_url(session_name)
            if vnc_url:
                output["vnc_url"] = vnc_url

    _ok(output)


def cmd_snapshot(args: list[str]) -> None:
    """snapshot [--session <name>] [-i/--interactive] [--iframe <selector>]"""
    session_name = _flag(args, "--session")
    interactive = "-i" in args or "--interactive" in args
    iframe_selector = _flag(args, "--iframe")
    sid = _require_session(session_name)
    body: dict[str, Any] = {"interactive_only": interactive}
    if iframe_selector:
        body["iframe_selector"] = iframe_selector
    result = _rpc("POST", f"/sessions/{sid}/snapshot", body)

    # Surface intervention detection from server
    if isinstance(result, dict) and result.get("intervention"):
        vnc_url = _get_vnc_url(session_name)
        if vnc_url and not result.get("vnc_url"):
            result["vnc_url"] = vnc_url

    _ok(result)


def cmd_click(args: list[str]) -> None:
    """click <ref|x,y> [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser click <ref> [--session <name>]")
    ref = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    body: dict[str, Any] = {}
    if "," in ref and not ref.startswith("@"):
        try:
            x, y = ref.split(",", 1)
            body = {"x": float(x), "y": float(y)}
        except ValueError:
            body = {"ref": ref}
    else:
        body = {"ref": ref}
    _rpc("POST", f"/sessions/{sid}/click", body)
    _ok()


def cmd_fill(args: list[str]) -> None:
    """fill <ref> <text> [--session <name>]"""
    if len(args) < 2:
        _err("Usage: stealth-browser fill <ref> <text> [--session <name>]")
    ref = args[0]
    # text may contain spaces; collect everything until --session
    text_parts = []
    i = 1
    while i < len(args) and args[i] != "--session":
        text_parts.append(args[i])
        i += 1
    text = " ".join(text_parts)
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/fill", {"ref": ref, "text": text})
    _ok()


def cmd_scroll(args: list[str]) -> None:
    """scroll <up|down> [--amount N] [--session <name>]"""
    direction = args[0] if args else "down"
    amount = int(_flag(args, "--amount") or "500")
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/scroll", {"direction": direction, "amount": amount})
    _ok()


def cmd_press(args: list[str]) -> None:
    """press <key> [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser press <key> [--session <name>]")
    key = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/keyboard/press", {"key": key})
    _ok()


def cmd_extract(args: list[str]) -> None:
    """extract [--type text|html|links|images] [--selector CSS] [--session <name>]"""
    extract_type = _flag(args, "--type") or "text"
    selector = _flag(args, "--selector")
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/extract", {
        "extract_type": extract_type,
        "selector": selector,
    })
    _ok(result)


def cmd_run(args: list[str]) -> None:
    """run "<task>" [--session <name>] [--max-steps N]"""
    if not args:
        _err("Usage: stealth-browser run \"<task>\" [--session <name>] [--max-steps N]")
    task = args[0]
    session_name = _flag(args, "--session")
    max_steps = int(_flag(args, "--max-steps") or "10")
    sid = _require_session(session_name)

    # Submit task
    submit = _rpc("POST", f"/sessions/{sid}/task", {
        "task": task,
        "intelligence": "agent",
        "max_steps": max_steps,
    })
    task_id = submit.get("task_id")
    if not task_id:
        _err(f"No task_id returned: {submit}")

    # Poll for completion
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(5)
        status = _rpc("GET", f"/sessions/{sid}/tasks/{task_id}")
        state = status.get("status", "running")
        if state in ("completed", "failed", "stuck", "timeout"):
            _ok(status)
            return

    _err("Task timed out after 300s")


def cmd_back(args: list[str]) -> None:
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/back")
    _ok()


def cmd_url(args: list[str]) -> None:
    """url [--session <name>]"""
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("GET", f"/sessions/{sid}/url")
    _ok(result)


def cmd_title(args: list[str]) -> None:
    """title [--session <name>]"""
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("GET", f"/sessions/{sid}/title")
    _ok(result)


def cmd_wait(args: list[str]) -> None:
    """wait <selector> [--timeout <ms>] [--session <name>]"""
    if not args or args[0].startswith("--"):
        _err("Usage: stealth-browser wait <selector> [--timeout <ms>] [--session <name>]")
    selector = args[0]
    timeout = int(_flag(args, "--timeout") or "5000")
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/wait", {"selector": selector, "timeout": timeout})
    _ok(result)


def cmd_find(args: list[str]) -> None:
    """find <selector> [--max N] [--session <name>]"""
    if not args or args[0].startswith("--"):
        _err("Usage: stealth-browser find <selector> [--max N] [--session <name>]")
    selector = args[0]
    max_results = int(_flag(args, "--max") or "50")
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/find_elements", {
        "selector": selector,
        "max_results": max_results,
    })
    _ok(result)


def cmd_mouse(args: list[str]) -> None:
    """mouse <x,y> [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser mouse <x,y> [--session <name>]")
    coords = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    try:
        x, y = coords.split(",", 1)
        _rpc("POST", f"/sessions/{sid}/mouse/move", {"x": float(x), "y": float(y)})
    except ValueError:
        _err(f"Invalid coordinates: {coords}. Expected format: x,y")
    _ok()


def cmd_keys(args: list[str]) -> None:
    """keys <sequence> [--session <name>]  e.g. keys "Control+c" """
    if not args or args[0].startswith("--"):
        _err("Usage: stealth-browser keys <sequence> [--session <name>]")
    sequence = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/keys/send", {"keys": sequence})
    _ok()


def cmd_eval(args: list[str]) -> None:
    """eval <expression> [--session <name>]"""
    if not args or args[0].startswith("--"):
        _err("Usage: stealth-browser eval <expression> [--session <name>]")
    expression = args[0]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/evaluate", {"expression": expression})
    _ok(result)


def cmd_upload(args: list[str]) -> None:
    """upload <ref> <file_path> [--session <name>]"""
    if len(args) < 2:
        _err("Usage: stealth-browser upload <ref> <file_path> [--session <name>]")
    ref = args[0]
    file_path = args[1]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    _rpc("POST", f"/sessions/{sid}/upload", {"ref": ref, "file_paths": [file_path]})
    _ok()


def cmd_screenshot(args: list[str]) -> None:
    """screenshot [--full-page] [--session <name>]"""
    full_page = "--full-page" in args
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("POST", f"/sessions/{sid}/screenshot", {"full_page": full_page})
    _ok(result)


def cmd_pdf(args: list[str]) -> None:
    """pdf [--output <path>] [--landscape] [--session <name>]"""
    output_path = _flag(args, "--output")
    landscape = "--landscape" in args
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    body: dict[str, Any] = {"landscape": landscape}
    if output_path:
        body["output_path"] = output_path
    result = _rpc("POST", f"/sessions/{sid}/pdf", body)
    _ok(result)


def cmd_tab(args: list[str]) -> None:
    """tab list|switch|open|close [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser tab <list|switch <index>|open [url]|close [index]> [--session <name>]")
    sub = args[0]
    rest = args[1:]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)

    if sub == "list":
        result = _rpc("GET", f"/sessions/{sid}/tabs")
        _ok(result)

    elif sub == "switch":
        if not rest or rest[0].startswith("--"):
            _err("Usage: stealth-browser tab switch <index> [--session <name>]")
        try:
            index = int(rest[0])
        except ValueError:
            _err(f"Invalid tab index: {rest[0]}")
        _rpc("POST", f"/sessions/{sid}/tabs/switch", {"index": index})
        _ok()

    elif sub == "open":
        url = rest[0] if rest and not rest[0].startswith("--") else None
        body: dict[str, Any] = {}
        if url:
            body["url"] = url
        result = _rpc("POST", f"/sessions/{sid}/tabs/open", body)
        _ok(result)

    elif sub == "close":
        index = None
        if rest and not rest[0].startswith("--"):
            try:
                index = int(rest[0])
            except ValueError:
                _err(f"Invalid tab index: {rest[0]}")
        body = {}
        if index is not None:
            body["index"] = index
        _rpc("POST", f"/sessions/{sid}/tabs/close", body)
        _ok()

    else:
        _err(f"Unknown tab subcommand: {sub}. Use: list, switch, open, close")


def cmd_dropdown(args: list[str]) -> None:
    """dropdown options <ref> | dropdown select <ref> <text> [--session <name>]"""
    if not args:
        _err("Usage: stealth-browser dropdown <options <ref>|select <ref> <text>> [--session <name>]")
    sub = args[0]
    rest = args[1:]
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)

    if sub == "options":
        if not rest or rest[0].startswith("--"):
            _err("Usage: stealth-browser dropdown options <ref> [--session <name>]")
        ref = rest[0]
        result = _rpc("POST", f"/sessions/{sid}/dropdown/options", {"ref": ref})
        _ok(result)

    elif sub == "select":
        if len(rest) < 2:
            _err("Usage: stealth-browser dropdown select <ref> <option_text> [--session <name>]")
        ref = rest[0]
        # option text may contain spaces; collect until --session
        text_parts = []
        i = 1
        while i < len(rest) and rest[i] != "--session":
            text_parts.append(rest[i])
            i += 1
        option_text = " ".join(text_parts)
        _rpc("POST", f"/sessions/{sid}/dropdown/select", {"ref": ref, "option_text": option_text})
        _ok()

    else:
        _err(f"Unknown dropdown subcommand: {sub}. Use: options, select")


def cmd_session(args: list[str]) -> None:
    """session create|list|destroy [--name <name>]"""
    if not args:
        _err("Usage: stealth-browser session <create|list|destroy> [--name <name>]")
    sub = args[0]
    rest = args[1:]

    if sub == "create":
        name = _flag(rest, "--name") or "default"
        result = _rpc("POST", "/sessions/create", {"user_id": f"skill_{name}"})
        sid = result.get("session_id", result.get("id", ""))
        if not sid:
            _err(f"No session_id returned: {result}")

        # Extract and cache VNC URL
        vnc_url = ""
        if "vnc_url" in result and result.get("vnc_url"):
            vnc_url = result["vnc_url"]
        elif "novnc_url" in result and result.get("novnc_url"):
            vnc_url = result["novnc_url"]
        _set_session_id(name, sid, vnc_url=vnc_url)

        output = {"name": name, "session_id": sid}
        if vnc_url:
            output["vnc_url"] = vnc_url

        _ok(output)

    elif sub == "list":
        result = _rpc("GET", "/sessions")
        cache = _load_session_cache()
        _ok({"sessions": result.get("sessions", []), "cached": cache})

    elif sub == "destroy":
        name = _flag(rest, "--name") or (rest[0] if rest else "default")
        sid = _get_session_id(name)
        if sid:
            try:
                _rpc("DELETE", f"/sessions/{sid}")
            except Exception:
                pass
            _del_session_id(name)
        _ok({"name": name, "destroyed": True})

    else:
        _err(f"Unknown session subcommand: {sub}")


def cmd_daemon(args: list[str]) -> None:
    """daemon status|stop"""
    sub = args[0] if args else "status"

    if sub == "status":
        running = _is_socket_alive()
        pid = None
        if running and PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
            except Exception:
                pass
        _ok({"running": running, "pid": pid, "sock": str(DAEMON_SOCK)})

    elif sub == "stop":
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                import signal
                os.kill(pid, signal.SIGTERM)
                _ok({"stopped": True, "pid": pid})
                return
            except Exception as exc:
                _err(f"Failed to stop daemon: {exc}")
        _ok({"stopped": False, "reason": "daemon not running"})

    else:
        _err(f"Unknown daemon subcommand: {sub}")


def cmd_doctor(args: list[str]) -> None:
    """doctor -- check environment and API service connectivity"""
    import asyncio
    import sys as _sys

    # Reuse doctor.py logic if available, otherwise do a lightweight check
    try:
        from stealth_browser.skill.scripts.doctor import run_diagnosis
        report = asyncio.run(run_diagnosis())
        _ok(report.to_dict())
    except ImportError:
        # Fallback: just check daemon + API reachability
        checks = []

        # Python version
        v = _sys.version_info
        checks.append({
            "name": "python_version",
            "status": "pass" if (v.major, v.minor) >= (3, 11) else "fail",
            "message": f"Python {v.major}.{v.minor}",
        })

        # Daemon
        checks.append({
            "name": "skill_daemon",
            "status": "pass" if _is_socket_alive() else "warn",
            "message": "Skill daemon running" if _is_socket_alive() else "Daemon not running (will auto-start)",
        })

        # API reachability via daemon
        try:
            result = _rpc("GET", "/health")
            checks.append({"name": "api_service", "status": "pass", "message": f"API reachable"})
        except Exception as exc:
            checks.append({"name": "api_service", "status": "fail", "message": str(exc)})

        ready = all(c["status"] != "fail" for c in checks)
        _ok({"ready": ready, "checks": checks})


# ── Helpers ────────────────────────────────────────────────────────────────────


def _flag(args: list[str], name: str) -> str | None:
    """Extract --flag value from args list."""
    try:
        idx = args.index(name)
        return args[idx + 1] if idx + 1 < len(args) else None
    except ValueError:
        return None


def _require_session(name: str | None) -> str:
    """Return cached session_id or error."""
    sid = _get_session_id(name)
    if not sid:
        label = name or "default"
        _err(
            f"No session '{label}' found. "
            f"Run: stealth-browser session create --name {label}"
        )
    return sid  # type: ignore[return-value]


# ── Intervention commands ──────────────────────────────────────────────────────


def cmd_check(args: list[str]) -> None:
    """check [--session <name>] -- check if current page requires human intervention."""
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    result = _rpc("GET", f"/sessions/{sid}/check-intervention")
    _ok(result)


def cmd_vnc(args: list[str]) -> None:
    """vnc [--session <name>] -- print VNC URL for the session."""
    session_name = _flag(args, "--session")
    sid = _require_session(session_name)
    vnc_url = _get_vnc_url(session_name)
    if not vnc_url:
        # Try fetching from API session status
        try:
            result = _rpc("GET", f"/sessions/{sid}")
            vnc_url = result.get("vnc_url", "")
        except Exception:
            vnc_url = ""
    _ok({"vnc_url": vnc_url or "VNC not available"})


# ── Dispatch ───────────────────────────────────────────────────────────────────

COMMANDS: dict[str, Any] = {
    "open": cmd_open,
    "snapshot": cmd_snapshot,
    "click": cmd_click,
    "fill": cmd_fill,
    "scroll": cmd_scroll,
    "press": cmd_press,
    "extract": cmd_extract,
    "run": cmd_run,
    "back": cmd_back,
    "url": cmd_url,
    "title": cmd_title,
    "wait": cmd_wait,
    "find": cmd_find,
    "mouse": cmd_mouse,
    "keys": cmd_keys,
    "eval": cmd_eval,
    "upload": cmd_upload,
    "screenshot": cmd_screenshot,
    "pdf": cmd_pdf,
    "tab": cmd_tab,
    "dropdown": cmd_dropdown,
    "session": cmd_session,
    "daemon": cmd_daemon,
    "doctor": cmd_doctor,
    "check": cmd_check,
    "vnc": cmd_vnc,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: stealth-browser <command> [options]\n\n"
            "Commands:\n"
            "  open <url>                Navigate to URL\n"
            "  snapshot [-i] [--iframe]  Get page snapshot\n"
            "  click <ref>               Click element\n"
            "  fill <ref> <text>         Fill input\n"
            "  scroll <up|down>          Scroll page\n"
            "  press <key>               Press keyboard key\n"
            "  extract [--type text]     Extract page content\n"
            "  run \"<task>\"              Run agent task\n"
            "  back                      Navigate back\n"
            "  url                       Get current URL\n"
            "  title                     Get page title\n"
            "  wait <selector>           Wait for selector\n"
            "  find <selector>           Find elements\n"
            "  mouse <x,y>               Move mouse\n"
            "  keys <sequence>           Send key sequence\n"
            "  eval <expression>         Evaluate JavaScript\n"
            "  upload <ref> <path>       Upload file\n"
            "  screenshot [--full-page]  Take screenshot\n"
            "  pdf [--output <path>]     Save as PDF\n"
            "  tab list|switch|open|close\n"
            "  dropdown options|select\n"
            "  session create|list|destroy\n"
            "  daemon status|stop\n"
            "  doctor                    Run environment diagnostics\n"
            "  check                     Check if page needs human intervention\n"
            "  vnc                       Show VNC URL for manual access\n\n"
            "All commands accept --session <name> (default: 'default')\n"
            "All output is JSON: {\"success\": true, \"data\": {...}}"
        )
        return

    cmd = args[0]
    rest = args[1:]

    handler = COMMANDS.get(cmd)
    if handler is None:
        _err(f"Unknown command: {cmd}. Run 'stealth-browser --help' for usage.")

    try:
        handler(rest)
    except RuntimeError as exc:
        _err(str(exc))
    except Exception as exc:
        _err(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
