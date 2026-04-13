"""Browser instance pool.

Supports two modes:
1. local: Launch CloakBrowser process locally
2. docker: Launch CloakBrowser in a Docker container
"""

import asyncio
import contextlib
import logging
import os
from typing import Literal

from agent_browser.models import (
    BrowserInstance,
    DockerBrowserInstance,
    K8sBrowserInstance,
    LocalBrowserInstance,
    ResourceExhaustedError,
)

logger = logging.getLogger(__name__)


class PortAllocator:
    """Port allocator."""

    def __init__(self, start: int = 19222, end: int = 19300):
        self.start = start
        self.end = end
        self.allocated = set()

    def allocate(self) -> int:
        """Allocate an available port."""
        for port in range(self.start, self.end + 1):
            if port not in self.allocated:
                self.allocated.add(port)
                return port
        raise RuntimeError(f"No available ports in range {self.start}-{self.end}")

    def release(self, port: int):
        """Release a port."""
        self.allocated.discard(port)


class BrowserInstancePool:
    """Browser instance pool -- supports local, Docker, and K8s modes."""

    def __init__(self, mode: Literal["local", "docker", "k8s"] = "local"):
        self.mode = mode
        self.instances = {}
        self.port_allocator = PortAllocator(start=19222, end=19300)
        self.novnc_port_allocator = PortAllocator(
            start=int(os.getenv("NOVNC_PORT_START", "6080")),
            end=int(os.getenv("NOVNC_PORT_END", "6200")),
        )
        self._docker_client = None  # Lazy init, reused
        self._debug_mode = os.getenv("DEBUG_CONTAINERS", "false").lower() == "true"
        self._k8s_pool: K8sBrowserPool | None = None
        logger.info(f"BrowserInstancePool initialized in {mode} mode")

    async def allocate(
        self,
        session_id: str,
        profile_dir: str,
        browser_type: str = "chromium",
    ) -> BrowserInstance:
        """Allocate a browser instance."""
        if self.mode == "local":
            return await self._allocate_local(session_id, profile_dir)
        if self.mode == "k8s":
            if self._k8s_pool is None:
                self._k8s_pool = K8sBrowserPool()
            instance = await self._k8s_pool.allocate(session_id)
            self.instances[session_id] = instance  # Store so release() can find it
            return instance
        return await self._allocate_docker(session_id, profile_dir)

    async def _allocate_local(
        self,
        session_id: str,
        profile_dir: str,
    ) -> LocalBrowserInstance:
        """Launch local CloakBrowser process."""
        from agent_browser.browser.stealth_launcher import launch_stealth_browser

        cdp_port = self.port_allocator.allocate()

        logger.info(f"Launching local browser for session {session_id} on port {cdp_port}")

        # Use stealth_launcher to launch the browser
        pw, browser, cdp_url = await launch_stealth_browser(
            headless=False,
            proxy=None,
            user_data_dir=profile_dir,
            cdp_port=cdp_port,
        )

        instance = LocalBrowserInstance(
            instance_id=f"local_{session_id}",
            cdp_url=cdp_url,
            cdp_port=cdp_port,
            playwright=pw,
            browser=browser,
            session_id=session_id,
        )

        self.instances[session_id] = instance
        logger.info(f"Local browser instance created: {instance.instance_id}")
        return instance

    def _get_docker_client(self):
        """Get or create Docker client (reuse connection)."""
        if self._docker_client is None:
            import docker

            self._docker_client = docker.from_env()
        return self._docker_client

    async def _allocate_docker(
        self,
        session_id: str,
        profile_dir: str,
    ) -> DockerBrowserInstance:
        """Launch CloakBrowser in a Docker container."""
        cdp_port = self.port_allocator.allocate()
        container_name = f"browser_{session_id}"

        logger.info(f"Launching Docker browser for session {session_id}")

        client = self._get_docker_client()

        # In debug mode, keep containers for log inspection; otherwise auto-clean
        auto_remove = not self._debug_mode

        # Check if running inside a Docker container (API container)
        in_docker = os.path.exists("/.dockerenv")

        if in_docker:
            # Mode D: API container -> browser container (via Docker network)
            # Container path -> host path conversion
            # HOST_PROFILE_PATH is the absolute path of profile directory on host
            host_profile_base = os.getenv("HOST_PROFILE_PATH")
            if not host_profile_base:
                raise RuntimeError(
                    "HOST_PROFILE_PATH must be set in Docker mode (host path that maps to PROFILE_STORAGE)"
                )
            # profile_dir is container-internal path /data/profiles/{session_id}
            # Extract session subdirectory name and append to host path
            session_subdir = os.path.basename(profile_dir)
            host_profile_dir = os.path.join(host_profile_base, session_subdir)

            container = client.containers.run(
                "agent-browser-browser:latest",
                name=container_name,
                detach=True,
                shm_size="128mb",
                mem_limit="2g",
                environment={
                    "CDP_PORT": "19222",
                    "HEADLESS": "false",
                    "PROFILE_STORAGE": "/data/profiles",
                },
                ports={
                    "6080/tcp": None,  # noVNC (host dynamic port)
                    "5900/tcp": None,  # VNC direct (host dynamic port)
                },
                volumes={host_profile_dir: {"bind": "/data/profiles", "mode": "rw"}},
                network="agent-browser-network",  # Shared network
                auto_remove=auto_remove,
            )

            # CDP URL uses IP address (Chrome rejects non-IP/localhost Host headers)
            import socket

            try:
                container_ip = socket.gethostbyname(container_name)
            except Exception:
                # DNS may not be registered right after container start; retry after wait
                import asyncio

                await asyncio.sleep(3)
                container_ip = socket.gethostbyname(container_name)
            cdp_url = f"http://{container_ip}:19222"

            # Read public access config (for informing users about browser node address)
            public_host = os.getenv("BROWSER_PUBLIC_HOST", "www.aiecho.site")
            port_offset = int(os.getenv("BROWSER_PORT_OFFSET", "0"))

            public_cdp_port = None  # Mode D: CDP not exposed externally (internal network)
            public_novnc_port = None
            novnc_url = None
            if public_host:
                container.reload()
                ports = container.ports or {}
                novnc_mapping = ports.get("6080/tcp")
                if novnc_mapping:
                    host_port = int(novnc_mapping[0]["HostPort"])
                    public_novnc_port = host_port + port_offset
                    novnc_url = f"http://{public_host}:{public_novnc_port}/vnc.html"

        else:
            # Mode B: local API -> Docker browser (via port mapping)
            novnc_port = self.novnc_port_allocator.allocate()
            container = client.containers.run(
                "agent-browser-browser:latest",
                name=container_name,
                detach=True,
                shm_size="128mb",
                mem_limit="1g",
                ports={
                    "19222/tcp": cdp_port,  # Map to host dynamic port
                    "6080/tcp": novnc_port,  # noVNC (fixed port range)
                },
                environment={
                    "CDP_PORT": "19222",
                    "HEADLESS": "false",
                    "PROFILE_STORAGE": "/data/profiles",
                },
                volumes={profile_dir: {"bind": "/data/profiles", "mode": "rw"}},
                auto_remove=auto_remove,
            )

            # CDP URL uses localhost
            cdp_url = f"http://localhost:{cdp_port}"

            # Extract container IP for reverse proxy support
            container.reload()
            network_settings = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            container_ip = None
            for net in network_settings.values():
                if net.get("IPAddress"):
                    container_ip = net["IPAddress"]
                    break

            # Read public access config (for informing users about browser node address)
            public_host = os.getenv("BROWSER_PUBLIC_HOST", "www.aiecho.site")
            port_offset = int(os.getenv("BROWSER_PORT_OFFSET", "0"))

            public_novnc_port = novnc_port + port_offset
            novnc_url = f"http://{public_host}:{public_novnc_port}/vnc.html"
            public_cdp_port = cdp_port + port_offset

        # Wait for browser inside container to start
        await self._wait_cdp_ready(cdp_url, timeout=30)

        instance = DockerBrowserInstance(
            instance_id=container_name,
            cdp_url=cdp_url,
            cdp_port=cdp_port,
            container=container,
            session_id=session_id,
            container_name=container_name,
            container_ip=container_ip,
            novnc_host_port=novnc_port if not in_docker else None,
            public_host=public_host,
            public_cdp_port=public_cdp_port,
            public_novnc_port=public_novnc_port,
            novnc_url=novnc_url,
        )

        self.instances[session_id] = instance
        logger.info(f"Docker browser instance created: {instance.instance_id}")
        return instance

    async def _wait_cdp_ready(self, cdp_url: str, timeout: int = 30):
        """Wait for CDP port to become ready."""
        from urllib.parse import urlparse

        import aiohttp

        parsed = urlparse(cdp_url)
        host = parsed.hostname
        port = parsed.port or 19222

        # Chrome DevTools HTTP endpoint rejects non-IP/localhost Host headers
        # Resolve container name to IP address for health check
        check_url = cdp_url
        try:
            import socket

            ip = socket.gethostbyname(host)
            check_url = f"http://{ip}:{port}"
        except Exception:
            pass  # Fall back to original URL

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.get(
                        f"{check_url}/json/version",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp,
                ):
                    if resp.status == 200:
                        logger.info(f"CDP ready at {cdp_url}")
                        return
            except Exception:
                pass
            await asyncio.sleep(1)

        raise TimeoutError(f"CDP not ready at {cdp_url} after {timeout}s")

    async def release(self, session_id: str):
        """Release a browser instance."""
        instance = self.instances.pop(session_id, None)
        if not instance:
            logger.warning(f"Instance not found for session {session_id}")
            return

        logger.info(f"Releasing browser instance: {instance.instance_id}")

        if isinstance(instance, LocalBrowserInstance):
            # Close local browser process
            try:
                await instance.browser.close()
                await instance.playwright.stop()
                logger.info(f"Local browser closed: {instance.instance_id}")
            except Exception as e:
                logger.warning(f"Failed to close local browser: {e}")

        elif isinstance(instance, DockerBrowserInstance):
            # Stop and remove container
            try:
                instance.container.stop(timeout=10)
                if self._debug_mode:
                    # Debug mode: manually remove (auto_remove=False)
                    with contextlib.suppress(Exception):
                        instance.container.remove(force=True)  # Container may already be removed
                logger.info(f"Docker container stopped: {instance.container_name}")
            except Exception as e:
                logger.warning(f"Failed to stop Docker container: {e}")
            # Release noVNC port (Mode B)
            if instance.novnc_host_port:
                self.novnc_port_allocator.release(instance.novnc_host_port)

        elif isinstance(instance, K8sBrowserInstance):
            # Return pod to pool (don't delete it — Deployment manages lifecycle)
            if self._k8s_pool:
                await self._k8s_pool.release(session_id)
            logger.info(f"K8s browser pod returned to pool: {instance.pod_name}")

        # Release port
        self.port_allocator.release(instance.cdp_port)


class K8sBrowserPool:
    """Manages a pool of pre-deployed browser pods (K8s Deployment).

    Allocates free pods from a Deployment to sessions, returns them when
    sessions end. Uses StateStore for cross-replica pod allocation tracking.
    """

    def __init__(self, store=None):
        self.namespace = os.getenv("KUBERNETES_NAMESPACE", "agent-browser")
        self._core_v1 = None
        self._apps_v1 = None
        # Free pod cache (rebuilt from K8s API + store on each allocate)
        self._free_pods: list[str] = []
        # Shared state store (K8s ConfigMap or in-memory)
        from agent_browser.state.store import create_state_store
        self.store = store or create_state_store()
        logger.info(f"K8sBrowserPool initialized (namespace={self.namespace})")

    def _get_core_v1(self):
        """Lazy-load K8s CoreV1 API client."""
        if self._core_v1 is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()  # Fallback for local dev
            self._core_v1 = client.CoreV1Api()
        return self._core_v1

    async def _discover_pods(self) -> list[tuple[str, str]]:
        """Query ready browser pods, returning (pod_name, pod_ip) tuples."""
        import asyncio

        core_v1 = self._get_core_v1()
        loop = asyncio.get_event_loop()

        def _list():
            resp = core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="app=agent-browser,component=browser",
            )
            return [
                (p.metadata.name, p.status.pod_ip)
                for p in resp.items
                if p.status.phase == "Running" and p.status.pod_ip
            ]

        try:
            all_running = await loop.run_in_executor(None, _list)
        except Exception as e:
            logger.error(f"Failed to discover browser pods: {e}")
            return []

        # Exclude pods that are allocated in the shared store
        try:
            allocated = await self.store.get_allocated_pods()
            allocated_set = set(allocated.values())
            return [(n, ip) for n, ip in all_running if n not in allocated_set]
        except Exception as e:
            logger.warning("Store read failed during pod discovery, using all running pods: %s", e)
            return all_running

    async def allocate(self, session_id: str) -> K8sBrowserInstance:
        """Allocate a free browser pod to a session."""
        if not self._free_pods:
            self._free_pods = await self._discover_pods()

        if not self._free_pods:
            allocated = await self.store.get_allocated_pods()
            raise ResourceExhaustedError(
                f"No available browser pods (allocated={len(allocated)})"
            )

        pod_name, pod_ip = self._free_pods.pop(0)

        # Record allocation in shared store
        await self.store.allocate_pod(session_id, pod_name)

        # Build CDP URL via auth proxy (port 80) on pod IP.
        # Auth proxy forwards /cdp/* to localhost CDP (127.0.0.1:19222).
        cdp_url = f"http://{pod_ip}:80/cdp"
        novnc_url = f"http://{pod_ip}:80"

        instance = K8sBrowserInstance(
            instance_id=pod_name,
            cdp_url=cdp_url,
            cdp_port=19222,
            session_id=session_id,
            pod_name=pod_name,
            novnc_url=novnc_url,
        )

        logger.info(f"Allocated pod {pod_name} ({pod_ip}) to session {session_id}")
        return instance

    async def release(self, session_id: str):
        """Return a pod to the free pool."""
        pod_name = await self.store.release_pod(session_id)
        if pod_name:
            # Re-fetch pod IP (may have changed after restart)
            try:
                pods = await self._discover_pods()
                match = [ip for n, ip in pods if n == pod_name]
                if match:
                    self._free_pods.append((pod_name, match[0]))
                else:
                    logger.warning("Pod %s not found during release, skipping re-add", pod_name)
            except Exception:
                self._free_pods.append((pod_name, ""))  # Will be rediscovered next allocate
            logger.info(f"Returned pod {pod_name} to free pool (session {session_id})")

    async def get_allocated_pods(self) -> dict[str, str]:
        """Get current allocation mapping from store (read-only)."""
        return await self.store.get_allocated_pods()

    def get_idle_pods(self) -> list[str]:
        """Get list of idle/free pod names."""
        return [name for name, _ip in self._free_pods]

    async def restart_pod(self, pod_name: str):
        """Delete a pod so Deployment recreates it (for cleanup)."""
        import asyncio

        core_v1 = self._get_core_v1()
        loop = asyncio.get_event_loop()

        def _delete():
            core_v1.delete_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )

        try:
            await loop.run_in_executor(None, _delete)
            # Remove from free pool since it's being recreated
            if pod_name in self._free_pods:
                self._free_pods.remove(pod_name)
            logger.info(f"Triggered pod restart: {pod_name}")
        except Exception as e:
            logger.warning(f"Failed to restart pod {pod_name}: {e}")
