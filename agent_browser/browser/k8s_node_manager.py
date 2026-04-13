"""K8s Browser Node Manager — dynamic br pod lifecycle management.

Creates and deletes br pods on demand, maintaining a warm pool of idle pods.
CP pod uses this manager to allocate/release browser pods for sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

BR_IMAGE = os.getenv("BR_IMAGE", "registry-cn-gimc-local.gimccloud.com/library/agent-browser-br:latest")
BR_NAMESPACE = os.getenv("BR_NAMESPACE", "agent-browser")
BR_HEADLESS_SVC = os.getenv(
    "BROWSER_HEADLESS_SVC",
    "agent-browser-br-headless.agent-browser.svc.cluster.local",
)
WARM_POOL_SIZE = int(os.getenv("WARM_POOL_SIZE", "3"))
BR_IDLE_TIMEOUT = int(os.getenv("BR_IDLE_TIMEOUT_SECONDS", "3600"))
STORAGE_CLASS = os.getenv("STORAGE_CLASS", "rook-ceph-block")
CLOAKBROWSER_PATH = os.getenv(
    "CLOAKBROWSER_PATH",
    "/root/.cloakbrowser/chromium-145.0.7632.159.7/chrome",
)


@dataclass
class BrPodInfo:
    pod_name: str
    pod_url: str  # http://{pod_name}.{headless_svc}:8080
    busy: bool = False
    session_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_idle_at: float = field(default_factory=time.time)


class K8sBrowserNodeManager:
    """Dynamically create/delete br pods; maintain a warm pool of idle pods."""

    def __init__(self):
        from kubernetes import client as k8s_client, config as k8s_config

        try:
            k8s_config.load_incluster_config()  # Inside k8s pod
            logger.info("K8sBrowserNodeManager: using in-cluster config")
        except Exception:
            k8s_config.load_kube_config()  # Local dev / testing
            logger.info("K8sBrowserNodeManager: using kubeconfig")

        self._core = k8s_client.CoreV1Api()
        self._pods: dict[str, BrPodInfo] = {}  # pod_name -> BrPodInfo
        self._lock = asyncio.Lock()
        self._warm_lock = asyncio.Lock()  # Serializes warm pool replenishment
        self._warm_task: asyncio.Task | None = None

    def start(self):
        """Start background warm-pool maintenance task."""
        self._warm_task = asyncio.create_task(self._warm_pool_loop())
        asyncio.create_task(self._reconcile_and_warm())
        logger.info("K8sBrowserNodeManager started")

    async def _reconcile_and_warm(self):
        """Discover existing idle BR pods from k8s, then fill warm pool."""
        # Brief delay to allow DNS to propagate after pod startup
        await asyncio.sleep(5)
        await self._reconcile_existing_pods()
        await self._ensure_warm_pool()

    async def allocate(self, session_id: str):
        """Find idle warm pod or create a new one, start browser, return K8sBrowserInstance."""
        from agent_browser.models import K8sBrowserInstance

        pod: BrPodInfo | None = None
        async with self._lock:
            for p in self._pods.values():
                if not p.busy:
                    p.busy = True
                    p.session_id = session_id
                    pod = p
                    break

        if pod is None:
            # No warm pod — create on-demand (outside lock to avoid blocking warm pool)
            logger.info(f"No idle warm pods for session {session_id}, creating new br pod")
            pod = await self._create_br_pod()
            async with self._lock:
                pod.busy = True
                pod.session_id = session_id
                self._pods[pod.pod_name] = pod

        # Start browser on the pod
        import aiohttp

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    f"{pod.pod_url}/browser/start",
                    json={"session_id": session_id, "profile_dir": "/data/profiles"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"browser/start failed on {pod.pod_name}: {resp.status} {body}"
                        )
                    result = await resp.json()
        except Exception:
            # Roll back pod claim on failure
            async with self._lock:
                if pod.pod_name in self._pods:
                    self._pods[pod.pod_name].busy = False
                    self._pods[pod.pod_name].session_id = None
                    self._pods[pod.pod_name].last_idle_at = time.time()
            raise

        # Get pod IP for CDP connection (Chrome rejects non-IP/localhost Host headers)
        pod_ip = await self._get_pod_ip(pod.pod_name)
        cdp_url = f"http://{pod_ip}:19222"

        instance = K8sBrowserInstance(
            instance_id=pod.pod_name,
            cdp_url=cdp_url,
            cdp_port=19222,
            pod_index=0,  # unused in dynamic routing — kept for model compat
            pod_url=pod.pod_url,
            pod_name=pod.pod_name,
            session_id=session_id,
        )
        logger.info(f"Allocated br pod {pod.pod_name} for session {session_id}")

        # Replenish warm pool in background
        asyncio.create_task(self._ensure_warm_pool())
        return instance

    async def release(self, session_id: str, pod_name: str):
        """Stop browser and delete the br pod + PVC."""
        async with self._lock:
            pod = self._pods.pop(pod_name, None)

        if not pod:
            logger.warning(f"release: pod {pod_name} not found in registry")
            # Still attempt deletion in case it exists in k8s
            await self._delete_br_pod(pod_name)
            return

        # Stop browser (best-effort)
        import aiohttp

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    f"{pod.pod_url}/browser/stop",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    logger.info(f"browser/stop on {pod_name}: {resp.status}")
        except Exception as e:
            logger.warning(f"browser/stop failed for {pod_name}: {e}")

        await self._delete_br_pod(pod_name)
        logger.info(f"Released and deleted br pod {pod_name}")

        # Replenish warm pool
        asyncio.create_task(self._ensure_warm_pool())

    async def shutdown(self):
        """Cancel warm-pool background task."""
        if self._warm_task:
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        logger.info("K8sBrowserNodeManager shutdown complete")

    # ── Internal helpers ─────────────────────────────────────────────

    async def _get_pod_ip(self, pod_name: str) -> str:
        """Get pod IP address from k8s API."""
        pod = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._core.read_namespaced_pod(pod_name, BR_NAMESPACE),
        )
        ip = pod.status.pod_ip
        if not ip:
            raise RuntimeError(f"Pod {pod_name} has no IP yet")
        return ip

    async def _create_br_pod(self) -> BrPodInfo:
        """Create a br Pod + PVC in k8s and wait until ready."""
        from kubernetes import client as k8s_client

        suffix = uuid.uuid4().hex[:8]
        pod_name = f"agent-browser-br-{suffix}"
        pvc_name = f"profiles-{pod_name}"

        logger.info(f"Creating br pod {pod_name}")

        # Create PVC
        pvc = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=pvc_name,
                namespace=BR_NAMESPACE,
                labels={"app": "agent-browser-br", "pod": pod_name},
            ),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                storage_class_name=STORAGE_CLASS,
                resources=k8s_client.V1ResourceRequirements(
                    requests={"storage": "10Gi"}
                ),
            ),
        )
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._core.create_namespaced_persistent_volume_claim(BR_NAMESPACE, pvc),
        )

        # Create Pod
        pod_spec = k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=BR_NAMESPACE,
                labels={
                    "app": "agent-browser-br",
                    "managed-by": "agent-browser-cp",
                },
            ),
            spec=k8s_client.V1PodSpec(
                hostname=pod_name,
                subdomain="agent-browser-br-headless",
                restart_policy="Never",
                containers=[
                    k8s_client.V1Container(
                        name="browser",
                        image=BR_IMAGE,
                        image_pull_policy="Always",
                        command=["/entrypoint-browser.sh"],
                        ports=[
                            k8s_client.V1ContainerPort(container_port=8080, name="browser-api"),
                            k8s_client.V1ContainerPort(container_port=6080, name="novnc"),
                        ],
                        env=[
                            k8s_client.V1EnvVar(name="POD_NAME", value=pod_name),
                            k8s_client.V1EnvVar(name="DISPLAY", value=":99"),
                            k8s_client.V1EnvVar(name="HEADLESS", value="false"),
                            k8s_client.V1EnvVar(name="PYTHONPATH", value="/app"),
                            k8s_client.V1EnvVar(
                                name="REBROWSER_PATCHES_RUNTIME_FIX_MODE",
                                value="addBinding",
                            ),
                            k8s_client.V1EnvVar(
                                name="CLOAKBROWSER_PATH", value=CLOAKBROWSER_PATH
                            ),
                            # Bind CDP to all interfaces so CP can connect via headless DNS
                            k8s_client.V1EnvVar(name="CDP_BIND_ADDRESS", value="0.0.0.0"),
                        ],
                        env_from=[
                            k8s_client.V1EnvFromSource(
                                secret_ref=k8s_client.V1SecretEnvSource(
                                    name="agent-browser-secret", optional=True
                                )
                            )
                        ],
                        resources=k8s_client.V1ResourceRequirements(
                            requests={"memory": "512Mi", "cpu": "500m"},
                            limits={"memory": "4Gi", "cpu": "2000m"},
                        ),
                        volume_mounts=[
                            k8s_client.V1VolumeMount(mount_path="/dev/shm", name="shm"),
                            k8s_client.V1VolumeMount(
                                mount_path="/data/profiles", name="profiles"
                            ),
                        ],
                        readiness_probe=k8s_client.V1Probe(
                            http_get=k8s_client.V1HTTPGetAction(
                                path="/health", port=8080
                            ),
                            initial_delay_seconds=10,
                            period_seconds=5,
                            failure_threshold=12,
                        ),
                    )
                ],
                volumes=[
                    k8s_client.V1Volume(
                        name="shm",
                        empty_dir=k8s_client.V1EmptyDirVolumeSource(
                            medium="Memory", size_limit="256Mi"
                        ),
                    ),
                    k8s_client.V1Volume(
                        name="profiles",
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=pvc_name
                        ),
                    ),
                ],
            ),
        )
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._core.create_namespaced_pod(BR_NAMESPACE, pod_spec),
        )

        # DNS: {hostname}.{subdomain}.{namespace}.svc.cluster.local
        pod_url = f"http://{pod_name}.agent-browser-br-headless.{BR_NAMESPACE}.svc.cluster.local:8080"
        info = BrPodInfo(pod_name=pod_name, pod_url=pod_url)

        # Wait for readiness
        await self._wait_pod_ready(pod_name, pod_url, timeout=90)
        return info

    async def _wait_pod_ready(self, pod_name: str, pod_url: str, timeout: int = 90):
        """Poll /health until pod is ready."""
        import aiohttp

        start = time.time()
        while time.time() - start < timeout:
            try:
                async with aiohttp.ClientSession() as http:
                    async with http.get(
                        f"{pod_url}/health",
                        timeout=aiohttp.ClientTimeout(total=3),
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"br pod {pod_name} is ready")
                            return
            except Exception:
                pass
            await asyncio.sleep(3)
        raise TimeoutError(f"br pod {pod_name} not ready after {timeout}s")

    async def _delete_br_pod(self, pod_name: str):
        """Delete br Pod and its PVC."""
        pvc_name = f"profiles-{pod_name}"
        for name, kind, fn in [
            (pod_name, "Pod", lambda n=pod_name: self._core.delete_namespaced_pod(n, BR_NAMESPACE)),
            (pvc_name, "PVC", lambda n=pvc_name: self._core.delete_namespaced_persistent_volume_claim(n, BR_NAMESPACE)),
        ]:
            try:
                await asyncio.get_event_loop().run_in_executor(None, fn)
                logger.info(f"Deleted {kind} {name}")
            except Exception as e:
                logger.warning(f"Failed to delete {kind} {name}: {e}")

    async def _reconcile_existing_pods(self):
        """Discover existing idle BR pods in k8s and register them in the warm pool."""
        try:
            pods = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._core.list_namespaced_pod(
                    BR_NAMESPACE,
                    label_selector="app=agent-browser-br,managed-by=agent-browser-cp",
                ),
            )
            registered = 0
            for pod in pods.items:
                pod_name = pod.metadata.name
                phase = pod.status.phase if pod.status else None
                if phase not in ("Running", "Pending"):
                    continue
                pod_url = f"http://{pod_name}.agent-browser-br-headless.{BR_NAMESPACE}.svc.cluster.local:8080"
                # Check if pod is actually idle (not serving a browser session)
                busy = False
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as http:
                        async with http.get(
                            f"{pod_url}/health",
                            timeout=aiohttp.ClientTimeout(total=3),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                busy = data.get("busy", False)
                            else:
                                continue  # Not ready yet, skip
                except Exception:
                    continue  # Not reachable, skip

                info = BrPodInfo(pod_name=pod_name, pod_url=pod_url, busy=busy)
                async with self._lock:
                    self._pods[pod_name] = info
                registered += 1
                logger.info(f"Reconciled existing br pod {pod_name} (busy={busy})")

            logger.info(f"Reconciliation complete: registered {registered} existing br pods")
        except Exception as e:
            logger.error(f"Failed to reconcile existing br pods: {e}")

    async def _ensure_warm_pool(self):
        """Ensure warm pool has WARM_POOL_SIZE idle pods (create if needed, serialized)."""
        async with self._warm_lock:
            async with self._lock:
                idle_count = sum(1 for p in self._pods.values() if not p.busy)
                needed = max(0, WARM_POOL_SIZE - idle_count)

            logger.debug(f"Warm pool check: idle={idle_count}, needed={needed}")
            for _ in range(needed):
                try:
                    pod = await self._create_br_pod()
                    async with self._lock:
                        self._pods[pod.pod_name] = pod
                    logger.info(f"Warm pool: created idle br pod {pod.pod_name}")
                except Exception as e:
                    logger.error(f"Failed to create warm br pod: {e}")

    async def _warm_pool_loop(self):
        """Background task: maintain warm pool + idle-timeout cleanup (runs every 60s)."""
        while True:
            await asyncio.sleep(60)
            try:
                # Reclaim excess idle pods that exceeded idle timeout (keep at least WARM_POOL_SIZE)
                to_reclaim: list[BrPodInfo] = []
                async with self._lock:
                    idle_pods = [p for p in self._pods.values() if not p.busy]
                    # Excess pods beyond warm pool size that are stale
                    excess = idle_pods[WARM_POOL_SIZE:]
                    to_reclaim = [
                        p for p in excess if time.time() - p.last_idle_at > BR_IDLE_TIMEOUT
                    ]
                    for p in to_reclaim:
                        self._pods.pop(p.pod_name, None)

                for pod in to_reclaim:
                    logger.info(f"Idle timeout: reclaiming excess br pod {pod.pod_name}")
                    await self._delete_br_pod(pod.pod_name)

                # Replenish to keep warm pool healthy
                await self._ensure_warm_pool()
            except Exception as e:
                logger.error(f"Warm pool loop error: {e}")
