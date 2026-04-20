"""K8s Browser Node Manager — dynamic br pod lifecycle management.

Creates and deletes br pods on demand, maintaining a warm pool of idle pods.
CP pod uses this manager to allocate/release browser pods for sessions.

Lifecycle:
  startup → reconcile existing pods → fill warm pool to WARM_POOL_SIZE
  allocate → grab idle pod (or create on-demand) → replenish warm pool
  release → stop browser → delete pod + PVC → replenish warm pool
  _warm_pool_loop (every 60s) → reclaim timed-out idle pods → replenish warm pool
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

BR_IMAGE = os.getenv("BR_IMAGE", "registry-cn-gimc-local.gimccloud.com/library/stealth-browser-br:latest")
BR_NAMESPACE = os.getenv("BR_NAMESPACE", "stealth-browser")
BR_HEADLESS_SVC = os.getenv(
    "BROWSER_HEADLESS_SVC",
    "stealth-browser-br-headless.stealth-browser.svc.cluster.local",
)
WARM_POOL_SIZE = int(os.getenv("WARM_POOL_SIZE", "3"))
BR_IDLE_TIMEOUT = int(os.getenv("BR_IDLE_TIMEOUT_SECONDS", "3600"))
STORAGE_CLASS = os.getenv("STORAGE_CLASS", "rook-ceph-block")
BR_SHM_SIZE = os.getenv("BR_SHM_SIZE", "512Mi")
BR_MEM_REQUEST = os.getenv("BR_MEM_REQUEST", "512Mi")
BR_MEM_LIMIT = os.getenv("BR_MEM_LIMIT", "4Gi")
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
        self._http_session: "aiohttp.ClientSession | None" = None

    def start(self):
        """Start background warm-pool maintenance task."""
        self._warm_task = asyncio.create_task(self._warm_pool_loop())
        asyncio.create_task(self._reconcile_and_warm())
        logger.info("K8sBrowserNodeManager started")

    async def _reconcile_and_warm(self):
        """Discover existing BR pods from k8s, clean orphans, then fill warm pool."""
        # Brief delay to allow DNS to propagate after pod startup
        await asyncio.sleep(5)
        await self._reconcile_existing_pods()
        await self._ensure_warm_pool()

    # ── Public API ────────────────────────────────────────────────────

    async def allocate(self, session_id: str):
        """Find idle warm pod or create a new one, start browser, return K8sBrowserInstance."""
        from stealth_browser.models import K8sBrowserInstance

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
        """Stop browser and delete the br pod + PVC.

        Pods are always deleted on release (not returned to idle pool) to prevent
        session data leakage via persistent PVC profiles.
        """
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

    # ── Internal helpers ─────────────────────────────────────────────

    async def get_pod_info(self, pod_name: str) -> BrPodInfo | None:
        """Look up a single pod by name (no K8s API call, local registry only)."""
        async with self._lock:
            return self._pods.get(pod_name)

    def _get_http_session(self):
        """Lazy-initialised shared aiohttp session (reused across health checks)."""
        import aiohttp

        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def shutdown(self):
        """Cancel warm-pool background task and close shared HTTP session."""
        if self._warm_task:
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        logger.info("K8sBrowserNodeManager shutdown complete")

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
        pod_name = f"stealth-browser-br-{suffix}"
        pvc_name = f"profiles-{pod_name}"

        logger.info(f"Creating br pod {pod_name}")

        # Create PVC
        pvc = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=pvc_name,
                namespace=BR_NAMESPACE,
                labels={"app": "stealth-browser-br", "pod": pod_name},
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
                    "app": "stealth-browser-br",
                    "managed-by": "stealth-browser-cp",
                },
            ),
            spec=k8s_client.V1PodSpec(
                hostname=pod_name,
                subdomain="stealth-browser-br-headless",
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
                            # Propagate stealth profile to BR pod
                            k8s_client.V1EnvVar(
                                name="STEALTH_BROWSER_STEALTH_PROFILE",
                                value=os.getenv("STEALTH_BROWSER_STEALTH_PROFILE", "off"),
                            ),
                        ],
                        env_from=[
                            k8s_client.V1EnvFromSource(
                                secret_ref=k8s_client.V1SecretEnvSource(
                                    name="stealth-browser-secret", optional=True
                                )
                            )
                        ],
                        resources=k8s_client.V1ResourceRequirements(
                            requests={"memory": BR_MEM_REQUEST, "cpu": "500m"},
                            limits={"memory": BR_MEM_LIMIT, "cpu": "2000m"},
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
                            medium="Memory", size_limit=BR_SHM_SIZE
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
        pod_url = f"http://{pod_name}.stealth-browser-br-headless.{BR_NAMESPACE}.svc.cluster.local:8080"
        info = BrPodInfo(pod_name=pod_name, pod_url=pod_url)

        # Wait for readiness
        await self._wait_pod_ready(pod_name, pod_url, timeout=90)
        return info

    async def _wait_pod_ready(self, pod_name: str, pod_url: str, timeout: int = 90):
        """Poll /health until pod is ready."""
        import aiohttp

        start = time.time()
        cs = self._get_http_session()
        while time.time() - start < timeout:
            try:
                async with cs.get(
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

    # ── Reconciliation ───────────────────────────────────────────────

    async def _reconcile_existing_pods(self):
        """Discover existing BR pods in k8s, clean orphan busy pods, register idle ones."""
        import aiohttp

        try:
            pods = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._core.list_namespaced_pod(
                    BR_NAMESPACE,
                    label_selector="app=stealth-browser-br,managed-by=stealth-browser-cp",
                ),
            )
            cs = self._get_http_session()
            to_delete: list[str] = []  # orphan busy pods to clean up

            for pod in pods.items:
                pod_name = pod.metadata.name
                phase = pod.status.phase if pod.status else None
                if phase not in ("Running", "Pending"):
                    continue

                pod_url = f"http://{pod_name}.stealth-browser-br-headless.{BR_NAMESPACE}.svc.cluster.local:8080"

                # Check if pod is actually idle or busy
                busy = False
                health_ok = False
                for attempt in range(3):
                    try:
                        async with cs.get(
                            f"{pod_url}/health",
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                busy = data.get("busy", False)
                                health_ok = True
                                break
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(2)
                        else:
                            logger.warning(f"Failed to reach {pod_name} after 3 attempts: {e}")

                if not health_ok:
                    continue  # Not reachable, skip

                if busy:
                    # Orphan busy pod: browser session from previous cp instance
                    # No session in pool_manager memory can release it — delete it
                    logger.warning(
                        f"Reconcile: found orphan busy pod {pod_name}, scheduling deletion"
                    )
                    to_delete.append(pod_name)
                    continue

                # Idle pod — register for warm pool
                info = BrPodInfo(pod_name=pod_name, pod_url=pod_url)
                async with self._lock:
                    self._pods[pod_name] = info
                logger.info(f"Reconciled existing idle br pod {pod_name}")

            # Delete orphan busy pods (outside lock to avoid blocking)
            for pod_name in to_delete:
                try:
                    await self._delete_br_pod(pod_name)
                    logger.info(f"Reconcile: deleted orphan busy pod {pod_name}")
                except Exception as e:
                    logger.warning(f"Reconcile: failed to delete orphan pod {pod_name}: {e}")

            idle_count = sum(1 for p in self._pods.values() if not p.busy)
            logger.info(
                f"Reconciliation complete: {idle_count} idle pods registered, "
                f"{len(to_delete)} orphan busy pods deleted"
            )
        except Exception as e:
            logger.error(f"Failed to reconcile existing br pods: {e}")

    # ── Warm pool management ─────────────────────────────────────────

    async def _ensure_warm_pool(self):
        """Ensure warm pool has WARM_POOL_SIZE idle pods (create in parallel)."""
        async with self._warm_lock:
            async with self._lock:
                idle_count = sum(1 for p in self._pods.values() if not p.busy)
                needed = max(0, WARM_POOL_SIZE - idle_count)

            if needed <= 0:
                return

            logger.info(f"Warm pool: idle={idle_count}, creating {needed} pod(s)")

            async def _create_and_register():
                pod = await self._create_br_pod()
                async with self._lock:
                    self._pods[pod.pod_name] = pod
                logger.info(f"Warm pool: created idle br pod {pod.pod_name}")

            results = await asyncio.gather(
                *[_create_and_register() for _ in range(needed)],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"Failed to create warm br pod: {r}")

    async def _warm_pool_loop(self):
        """Background task: reclaim timed-out idle pods, then replenish (runs every 60s)."""
        while True:
            await asyncio.sleep(60)
            try:
                # Delete ALL idle pods that exceeded idle timeout (not just excess)
                to_reclaim: list[BrPodInfo] = []
                async with self._lock:
                    idle_pods = [p for p in self._pods.values() if not p.busy]
                    to_reclaim = [
                        p for p in idle_pods if time.time() - p.last_idle_at > BR_IDLE_TIMEOUT
                    ]
                    for p in to_reclaim:
                        self._pods.pop(p.pod_name, None)

                for pod in to_reclaim:
                    logger.info(f"Idle timeout: reclaiming br pod {pod.pod_name}")
                    await self._delete_br_pod(pod.pod_name)

                # Replenish warm pool to WARM_POOL_SIZE
                await self._ensure_warm_pool()
            except Exception as e:
                logger.error(f"Warm pool loop error: {e}")
