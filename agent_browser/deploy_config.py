"""Deployment configuration model, validation, and I/O.

Single source of truth for ALL deployment state (browser, API, LLM, Docker, K8s).
Extends the existing config.yaml schema with new sections rather than creating a parallel file.

Config precedence (unchanged from existing system):
  1. Explicit parameters (function kwargs)
  2. Environment variables (AGENT_BROWSER_*)
  3. YAML config (~/.agent-browser/config.yaml) — EXTENDED with new sections
  4. Auto-detection (localhost:8000, 127.0.0.1:19222)
  5. Hardcoded defaults
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".agent-browser"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


# ── Data Model ──────────────────────────────────────────────


@dataclass
class DeployConfig:
    """Extended deployment configuration. Superset of SkillConfig concepts."""

    # ── Deployment metadata ──
    mode: str = "local"  # local | docker-aio | docker-distributed | k8s-aio | k8s-distributed
    os: str = ""  # auto-detected: darwin, linux
    arch: str = ""  # auto-detected: arm64, amd64
    configured_at: str = ""
    last_verified: str | None = None

    # ── Browser ──
    browser_type: str = "cloakbrowser"  # cloakbrowser | chrome | playwright
    cdp_url: str = "http://127.0.0.1:19222"
    headless: bool = False
    max_sessions: int = 10
    idle_timeout: int = 1800

    # ── API server ──
    api_enabled: bool = True
    api_port: int = 8000
    api_host: str = "127.0.0.1"

    # ── LLM (separated layer — changes frequently) ──
    llm_provider: str = ""  # empty = use existing SkillConfig logic
    llm_model: str = ""
    llm_api_key_set: bool = False  # presence flag only, never store key
    llm_base_url: str | None = None

    # ── Stealth ──
    stealth_enabled: bool = True
    stealth_mode: str = "full"  # full | vanilla

    # ── Docker (only relevant when mode=docker-*) ──
    docker_registry: str | None = None
    docker_image_tag: str = "latest"
    docker_shm_size: str = "256Mi"
    docker_memory_limit: str = "2Gi"
    docker_cpu_limit: str = "2000m"

    # ── K8s (Phase 4+ — schema reserved now) ──
    k8s_namespace: str = "agent-browser"
    k8s_context: str | None = None
    k8s_registry: str | None = None
    k8s_storage_class: str = "standard"
    k8s_replicas: int = 1

    # ── Proxy ──
    proxy_enabled: bool = False
    proxy_list: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, excluding empty/None values for clean YAML."""
        raw = asdict(self)
        return {k: v for k, v in raw.items() if v is not None and v != "" and v != [] and v}


# ── Validation ──────────────────────────────────────────────


@dataclass
class ConfigIssue:
    severity: str  # error | warning | info
    section: str  # browser | docker | k8s | llm | api | general
    message: str
    fix_hint: str = ""
    auto_fixable: bool = False


def validate_config(cfg: DeployConfig, env_check: bool = True) -> list[ConfigIssue]:
    """Validate deployment config and return list of issues."""
    issues: list[ConfigIssue] = []

    # Mode validation
    valid_modes = {"local", "docker-aio", "docker-distributed", "k8s-aio", "k8s-distributed"}
    if cfg.mode not in valid_modes:
        issues.append(
            ConfigIssue(
                severity="error",
                section="general",
                message=f"Invalid deployment mode: '{cfg.mode}'. Must be one of {valid_modes}",
                fix_hint="Set deployment.mode to 'local' for first-time setup",
            )
        )

    # Browser validation
    if cfg.browser_type == "cloakbrowser" and env_check:
        try:
            import cloakbrowser  # noqa: F401
        except ImportError:
            issues.append(
                ConfigIssue(
                    severity="error",
                    section="browser",
                    message="CloakBrowser package not installed",
                    fix_hint="Run: pip install cloakbrowser",
                    auto_fixable=True,
                )
            )
    if cfg.cdp_url and "19222" in cfg.cdp_url and env_check:
        try:
            import asyncio

            import aiohttp

            async def _check():
                async with (
                    aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s,
                    s.get(cfg.cdp_url + "/json/version") as r,
                ):
                    if r.status != 200:
                        issues.append(
                            ConfigIssue(
                                severity="warning",
                                section="browser",
                                message=f"CDP not reachable at {cfg.cdp_url} (status {r.status})",
                                fix_hint="Start CloakBrowser or verify CDP port",
                            )
                        )

            asyncio.run(_check())
        except Exception:
            issues.append(
                ConfigIssue(
                    severity="warning",
                    section="browser",
                    message=f"Cannot verify CDP at {cfg.cdp_url}",
                    fix_hint="Start CloakBrowser or set headless=true to skip browser check",
                )
            )

    # Docker validation
    if "docker" in cfg.mode and env_check:
        docker_ok = _command_exists("docker")
        if not docker_ok:
            issues.append(
                ConfigIssue(
                    severity="error",
                    section="docker",
                    message="Docker not installed but Docker mode selected",
                    fix_hint="Install Docker: https://docs.docker.com/get-docker/",
                )
            )
        compose_ok = _command_exists("docker-compose")
        if not compose_ok:
            issues.append(
                ConfigIssue(
                    severity="warning",
                    section="docker",
                    message="docker-compose not found (needed for Docker mode)",
                    fix_hint="Install Docker Compose or use local mode instead",
                )
            )

    # K8s validation
    if "k8s" in cfg.mode and env_check:
        kubectl_ok = _command_exists("kubectl")
        if not kubectl_ok:
            issues.append(
                ConfigIssue(
                    severity="error",
                    section="k8s",
                    message="kubectl not installed but K8s mode selected",
                    fix_hint="Install kubectl or use local/Docker mode",
                )
            )
        # Check for cluster access
        if kubectl_ok:
            result = _run_cmd("kubectl config current-context", timeout=5)
            if result.returncode != 0:
                issues.append(
                    ConfigIssue(
                        severity="warning",
                        section="k8s",
                        message="kubectl cannot connect to any cluster",
                        fix_hint="Run: kubectl config use-context <context>",
                    )
                )

    # API port check
    if cfg.api_enabled and env_check:
        try:
            import asyncio

            import aiohttp

            async def _check_api():
                url = f"http://{cfg.api_host}:{cfg.api_port}/health"
                async with (
                    aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s,
                    s.get(url) as r,
                ):
                    if r.status != 200:
                        issues.append(
                            ConfigIssue(
                                severity="info",
                                section="api",
                                message=f"API not running at {url} (status {r.status})",
                                fix_hint="Start API server with: uvicorn src.api:app --port {cfg.api_port}",
                            )
                        )

            asyncio.run(_check_api())
        except Exception:
            pass  # API not required for basic usage

    # LLM config
    if not cfg.llm_api_key_set and env_check:
        has_openai = bool(os.getenv("OPENAI_API_KEY"))
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
        has_glm = bool(os.getenv("GLM_API_KEY")) or bool(
            os.getenv("OPENAI_BASE_URL", "") and "bigmodel" in os.getenv("OPENAI_BASE_URL", "")
        )
        if not (has_openai or has_anthropic or has_glm):
            issues.append(
                ConfigIssue(
                    severity="info",
                    section="llm",
                    message="No LLM API key found (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GLM_API_KEY)",
                    fix_hint="Set an env var or run setup() interactively to configure",
                )
            )

    return issues


# ── Environment Detection ──────────────────────────────────────────


def detect_environment() -> dict[str, Any]:
    """Detect OS, arch, and available tools. Returns dict for DeployConfig."""
    import platform

    os_name = platform.system().lower()  # darwin, linux, win32
    machine = platform.machine().lower()  # x86_64 → amd64, arm64

    arch = "amd64" if machine == "x86_64" else ("arm64" if machine == "arm64" else machine)

    return {
        "os": os_name,
        "arch": arch,
        "has_docker": _command_exists("docker"),
        "has_compose": _command_exists("docker-compose"),
        "has_kubectl": _command_exists("kubectl"),
        "has_cloakbrowser": _package_installed("cloakbrowser"),
        "python_version": platform.python_version(),
    }


def _command_exists(cmd: str) -> bool:
    """Check if a command exists on PATH."""
    import shutil

    return shutil.which(cmd) is not None


def _package_installed(package: str) -> bool:
    """Check if a Python package is installed."""
    try:
        __import__(package)
        return True
    except ImportError:
        return False


def _run_cmd(cmd: str, timeout: int = 10) -> Any:
    """Run a shell command, return result with returncode/output."""
    import subprocess

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return type(
            "result",
            (),
            {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
        )
    except subprocess.TimeoutExpired:
        return type("result", (), {"returncode": -1, "stdout": "", "stderr": f"Timed out after {timeout}s"})
    except Exception as e:
        return type("result", (), {"returncode": -1, "stdout": "", "stderr": str(e)})


# ── Config I/O ────────────────────────────────────────────────────


def load_deploy_config() -> DeployConfig:
    """Load deployment config from extended config.yaml.

    Reads the NEW sections (deployment, browser, docker, k8s, proxy) from
    the existing ~/.agent-browser/config.yaml file. Falls back to defaults
    if sections don't exist yet.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    yaml_data = _load_yaml_config(CONFIG_PATH)
    if not yaml_data:
        return DeployConfig()

    cfg = DeployConfig()

    # Deployment section
    dep = yaml_data.get("deployment", {})
    if isinstance(dep, dict):
        cfg.mode = dep.get("mode", cfg.mode)
        cfg.os = dep.get("os", cfg.os)
        cfg.arch = dep.get("arch", cfg.arch)
        cfg.configured_at = dep.get("configured_at", "")
        cfg.last_verified = dep.get("last_verified")

    # Browser section
    br = yaml_data.get("browser", {})
    if isinstance(br, dict):
        cfg.browser_type = br.get("type", cfg.browser_type)
        cfg.cdp_url = br.get("cdp_url", cfg.cdp_url)
        cfg.headless = br.get("headless", cfg.headless)
        cfg.max_sessions = br.get("max_sessions", cfg.max_sessions)
        cfg.idle_timeout = br.get("idle_timeout", cfg.idle_timeout)

    # API section
    api = yaml_data.get("api", {})
    if isinstance(api, dict):
        cfg.api_enabled = api.get("enabled", cfg.api_enabled)
        cfg.api_port = api.get("port", cfg.api_port)
        cfg.api_host = api.get("host", cfg.api_host)

    # LLM section
    llm = yaml_data.get("llm", {})
    if isinstance(llm, dict):
        cfg.llm_provider = llm.get("provider", cfg.llm_provider)
        cfg.llm_model = llm.get("model", cfg.llm_model)
        cfg.llm_base_url = llm.get("base_url", cfg.llm_base_url)
        cfg.llm_api_key_set = bool(llm.get("api_key_set", False))

    # Stealth section
    st = yaml_data.get("stealth", {})
    if isinstance(st, dict):
        cfg.stealth_enabled = st.get("enabled", cfg.stealth_enabled)
        cfg.stealth_mode = st.get("mode", cfg.stealth_mode)

    # Docker section
    dk = yaml_data.get("docker", {})
    if isinstance(dk, dict):
        cfg.docker_registry = dk.get("registry")
        cfg.docker_image_tag = dk.get("image_tag", cfg.docker_image_tag)
        cfg.docker_shm_size = dk.get("shm_size", cfg.docker_shm_size)
        rl = dk.get("resource_limits", {})
        if isinstance(rl, dict):
            cfg.docker_memory_limit = rl.get("memory", cfg.docker_memory_limit)
            cfg.docker_cpu_limit = rl.get("cpu", cfg.docker_cpu_limit)

    # K8s section
    k8s = yaml_data.get("k8s", {})
    if isinstance(k8s, dict):
        cfg.k8s_namespace = k8s.get("namespace", cfg.k8s_namespace)
        cfg.k8s_context = k8s.get("context")
        cfg.k8s_registry = k8s.get("registry")
        cfg.k8s_storage_class = k8s.get("storage_class", cfg.k8s_storage_class)
        cfg.k8s_replicas = k8s.get("replicas", cfg.k8s_replicas)

    # Proxy section
    px = yaml_data.get("proxy", {})
    if isinstance(px, dict):
        cfg.proxy_enabled = px.get("enabled", cfg.proxy_enabled)
        cfg.proxy_list = px.get("list", cfg.proxy_list)

    return cfg


def generate_config(cfg: DeployConfig, path: Path | None = None) -> Path:
    """Write validated DeployConfig to config.yaml (atomic write).

    Extends existing config.yaml with new sections without overwriting
    unrelated keys that may exist.
    """
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config to preserve unrelated sections
    existing = _load_yaml_config(target) or {}

    # Build full config dict: existing + new/overridden
    full = dict(existing)

    # Write new sections (these overwrite on conflict)
    full["deployment"] = {
        "mode": cfg.mode,
        "os": cfg.os or detect_environment().get("os", ""),
        "arch": cfg.arch or detect_environment().get("arch", ""),
        "configured_at": cfg.configured_at or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_verified": cfg.last_verified,
    }
    full["browser"] = {
        "type": cfg.browser_type,
        "cdp_url": cfg.cdp_url,
        "headless": cfg.headless,
        "max_sessions": cfg.max_sessions,
        "idle_timeout": cfg.idle_timeout,
    }
    full["api"] = {
        "enabled": cfg.api_enabled,
        "port": cfg.api_port,
        "host": cfg.api_host,
    }
    if cfg.llm_provider or cfg.llm_model:
        full["llm"] = {
            "provider": cfg.llm_provider,
            "model": cfg.llm_model,
            "base_url": cfg.llm_base_url,
            "api_key_set": cfg.llm_api_key_set,
        }
    full["stealth"] = {
        "enabled": cfg.stealth_enabled,
        "mode": cfg.stealth_mode,
    }
    if cfg.docker_registry or "docker" in cfg.mode:
        full["docker"] = {
            "registry": cfg.docker_registry,
            "image_tag": cfg.docker_image_tag,
            "shm_size": cfg.docker_shm_size,
            "resource_limits": {
                "memory": cfg.docker_memory_limit,
                "cpu": cfg.docker_cpu_limit,
            },
        }
    if cfg.k8s_context or "k8s" in cfg.mode:
        full["k8s"] = {
            "namespace": cfg.k8s_namespace,
            "context": cfg.k8s_context,
            "registry": cfg.k8s_registry,
            "storage_class": cfg.k8s_storage_class,
            "replicas": cfg.k8s_replicas,
        }
    if cfg.proxy_enabled or cfg.proxy_list:
        full["proxy"] = {
            "enabled": cfg.proxy_enabled,
            "list": cfg.proxy_list,
        }

    # Also write under skill:* namespace so config.py:_apply_yaml_overrides() can read it.
    # This fixes the YAML path mismatch where generate_config() writes top-level
    # keys but _apply_yaml_overrides() reads from skill.* nested keys.
    full["skill"] = {
        "calling_mode": "cli" if "docker" not in cfg.mode and "k8s" not in cfg.mode else "api",
        "browser_mode": "local",
        "intelligence": "llm",
        "cdp_url": cfg.cdp_url,
        "api_url": f"http://{cfg.api_host}:{cfg.api_port}" if cfg.api_enabled else "",
        "browser": {
            "headless": cfg.headless,
            "default_timeout": 30000,  # SkillConfig default
        },
        "stealth": {
            "enabled": cfg.stealth_enabled,
            "mode": cfg.stealth_mode,
            "warmup": False,
        },
    }

    # Atomic write: temp file → rename
    import tempfile

    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="ab-config-", dir=target.parent)
    try:
        os.write(fd, _dump_yaml(full).encode("utf-8"))
    finally:
        os.close(fd)

    import shutil

    shutil.move(tmp_path, target)  # atomic on POSIX

    logger.info(f"Configuration written to {target}")
    return target


def _load_yaml_config(path: Path) -> dict | None:
    """Load YAML config file, returning dict or None if missing/invalid."""
    if not path.exists():
        return None
    try:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to load config from {path}: {e}")
        return None


def _dump_yaml(data: dict) -> str:
    """Dump dict to YAML string without external dependencies."""
    try:
        import yaml

        return yaml.dump(data, default_flow_style=False, allow_unicode=True)
    except ImportError:
        # Fallback: simple manual YAML dump for common types
        lines = []

        def _dump(obj, indent=0):
            prefix = "  " * indent
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lines.append(f"{prefix}{k}: {_dump(v, indent + 1)}")
            elif isinstance(obj, list):
                lines.append(f"{prefix}- [{', '.join(_dump(i, 0) for i in obj)}]")
            elif isinstance(obj, str):
                lines.append(f'{prefix}"{obj}"')
            elif isinstance(obj, bool):
                lines.append(f"{prefix}{str(obj).lower()}")
            else:
                lines.append(f"{prefix}{obj}")

        _dump(data)
        return "\n".join(lines)
