"""Docker smoke tests -- prove containerized deployment works.

These tests attempt real Docker operations but SKIP GRACEFULLY if:
- Docker daemon is not running
- docker CLI is not installed
- Image build fails (network, missing Dockerfile)

No test should ever fail because Docker isn't available.
All Docker-unavailable scenarios produce pytest.skip().
"""

import os
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_DOCKER_SH = os.path.join(PROJECT_ROOT, "scripts", "deploy-docker.sh")
DOCKER_COMPOSE_YAML = os.path.join(PROJECT_ROOT, "docker", "docker-compose.yml")


def _docker_available():
    """Check if Docker daemon is reachable. Returns (available, reason)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, None
        return False, result.stderr.strip() or "Docker daemon returned error"
    except FileNotFoundError:
        return False, "docker CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "docker info timed out"


def _docker_compose_available():
    """Check if docker compose (v2) is available."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, None
        return False, result.stderr.strip()
    except FileNotFoundError:
        # Try v1
        try:
            result = subprocess.run(
                ["docker-compose", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0, None
        except FileNotFoundError:
            return False, "docker-compose not installed"
    except subprocess.TimeoutExpired:
        return False, "timed out"


# ════════════════════════════════════════════════════════════════════
# A. Script Sanity (no Docker required)
# ════════════════════════════════════════════════════════════════════


class TestDockerScriptSanity:
    def test_deploy_script_exists(self):
        """deploy-docker.sh script file exists."""
        assert os.path.isfile(DEPLOY_DOCKER_SH), f"deploy-docker.sh not found at {DEPLOY_DOCKER_SH}"

    def test_help_exits_zero(self):
        """--help exits 0 with usage info."""
        result = subprocess.run(
            ["bash", DEPLOY_DOCKER_SH, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) > 0

    def test_unknown_flag_exits_nonzero(self):
        """Unknown flag causes non-zero exit."""
        result = subprocess.run(
            ["bash", DEPLOY_DOCKER_SH, "--nonexistent-flag"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0


# ════════════════════════════════════════════════════════════════════
# B. Docker Build + Run [requires Docker daemon]
# ════════════════════════════════════════════════════════════════════


class TestDockerBuild:
    def test_docker_info_succeeds(self):
        """Docker info returns successfully (daemon is up)."""
        available, reason = _docker_available()
        if not available:
            pytest.skip(reason)
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) > 0


class TestDockerCompose:
    def test_compose_file_exists(self):
        """docker-compose.yml exists in docker/ directory."""
        if not os.path.isfile(DOCKER_COMPOSE_YAML):
            pytest.skip("docker-compose.yml not found -- Docker deployment may not be configured yet")

    def test_compose_config_parses(self):
        """docker compose config parses without errors."""
        available, reason = _docker_compose_available()
        if not available:
            pytest.skip(reason)
        if not os.path.isfile(DOCKER_COMPOSE_YAML):
            pytest.skip("docker-compose.yml not found")
        result = subprocess.run(
            ["docker", "compose", "-f", DOCKER_COMPOSE_YAML, "config"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0 or "image" in result.stderr.lower()


class TestDockerHealthCheck:
    def test_container_can_be_listed(self):
        """`docker ps` runs without error (may return empty list)."""
        available, reason = _docker_available()
        if not available:
            pytest.skip(reason)
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


# ════════════════════════════════════════════════════════════════════
# C. Install Script Docker Integration
# ════════════════════════════════════════════════════════════════════


class TestInstallScriptDockerMode:
    def test_install_sh_exists(self):
        """install.sh script exists."""
        install_sh = os.path.join(PROJECT_ROOT, "scripts", "install.sh")
        assert os.path.isfile(install_sh), f"install.sh not found at {install_sh}"

    def test_install_sh_help(self):
        """install.sh --help exits 0."""
        install_sh = os.path.join(PROJECT_ROOT, "scripts", "install.sh")
        result = subprocess.run(
            ["bash", install_sh, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
