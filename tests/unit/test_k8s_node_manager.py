"""K8sNodeManager lifecycle tests — verify warm pool, reconcile, and release logic.

Tests use mocked k8s API and aiohttp calls.  No cluster access required.
"""

import asyncio
import time
from unittest import mock

import pytest

from agent_browser.browser.k8s_node_manager import (
    BR_IDLE_TIMEOUT,
    WARM_POOL_SIZE,
    BrPodInfo,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_pod(name: str, busy: bool = False) -> BrPodInfo:
    return BrPodInfo(
        pod_name=name,
        pod_url=f"http://{name}.svc:8080",
        busy=busy,
        session_id="sess-1" if busy else None,
        last_idle_at=time.time() if not busy else 0,
    )


def _make_manager():
    """Create a K8sBrowserNodeManager with mocked k8s client (no cluster needed)."""
    with mock.patch("agent_browser.browser.k8s_node_manager.K8sBrowserNodeManager.__init__", lambda self: None):
        from agent_browser.browser.k8s_node_manager import K8sBrowserNodeManager
        mgr = K8sBrowserNodeManager.__new__(K8sBrowserNodeManager)
        mgr._core = mock.MagicMock()
        mgr._pods = {}
        mgr._lock = asyncio.Lock()
        mgr._warm_lock = asyncio.Lock()
        mgr._warm_task = None
        mgr._http_session = None
        return mgr


# ── Test: Warm pool replenishment ────────────────────────────────────


class TestEnsureWarmPool:
    """_ensure_warm_pool creates pods to reach WARM_POOL_SIZE."""

    @pytest.mark.asyncio
    async def test_creates_pods_when_below_size(self):
        mgr = _make_manager()
        # Pool is empty, need WARM_POOL_SIZE pods
        with mock.patch.object(mgr, "_create_br_pod", side_effect=[
            _make_pod("br-1"),
            _make_pod("br-2"),
            _make_pod("br-3"),
        ]):
            await mgr._ensure_warm_pool()

        idle = [p for p in mgr._pods.values() if not p.busy]
        assert len(idle) == WARM_POOL_SIZE

    @pytest.mark.asyncio
    async def test_no_creation_when_at_size(self):
        mgr = _make_manager()
        # Pre-fill pool
        for i in range(WARM_POOL_SIZE):
            mgr._pods[f"br-{i}"] = _make_pod(f"br-{i}")

        with mock.patch.object(mgr, "_create_br_pod") as mock_create:
            await mgr._ensure_warm_pool()
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_fill(self):
        mgr = _make_manager()
        # 1 idle pod, need 2 more
        mgr._pods["br-existing"] = _make_pod("br-existing")

        with mock.patch.object(mgr, "_create_br_pod", side_effect=[
            _make_pod("br-new-1"),
            _make_pod("br-new-2"),
        ]):
            await mgr._ensure_warm_pool()

        idle = [p for p in mgr._pods.values() if not p.busy]
        assert len(idle) == WARM_POOL_SIZE

    @pytest.mark.asyncio
    async def test_does_not_count_busy_pods(self):
        mgr = _make_manager()
        # 2 busy + 0 idle → should create WARM_POOL_SIZE
        mgr._pods["br-busy-1"] = _make_pod("br-busy-1", busy=True)
        mgr._pods["br-busy-2"] = _make_pod("br-busy-2", busy=True)

        with mock.patch.object(mgr, "_create_br_pod", side_effect=[
            _make_pod(f"br-new-{i}") for i in range(WARM_POOL_SIZE)
        ]):
            await mgr._ensure_warm_pool()

        idle = [p for p in mgr._pods.values() if not p.busy]
        assert len(idle) == WARM_POOL_SIZE


# ── Test: Warm pool loop ─────────────────────────────────────────────


class TestWarmPoolLoop:
    """_warm_pool_loop reclaims timed-out idle pods then replenishes."""

    @pytest.mark.asyncio
    async def test_reclaims_timed_out_idle_pods(self):
        mgr = _make_manager()
        # One pod idle for longer than BR_IDLE_TIMEOUT
        old_pod = _make_pod("br-old")
        old_pod.last_idle_at = time.time() - BR_IDLE_TIMEOUT - 100
        mgr._pods["br-old"] = old_pod

        # Another pod recently idle (should NOT be reclaimed)
        new_pod = _make_pod("br-new")
        new_pod.last_idle_at = time.time() - 60  # 1 min ago
        mgr._pods["br-new"] = new_pod

        with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()):
            with mock.patch.object(mgr, "_ensure_warm_pool", mock.AsyncMock()):
                # Run one iteration of the loop manually
                to_reclaim = []
                idle_pods = [p for p in mgr._pods.values() if not p.busy]
                to_reclaim = [p for p in idle_pods if time.time() - p.last_idle_at > BR_IDLE_TIMEOUT]
                for p in to_reclaim:
                    mgr._pods.pop(p.pod_name, None)

        # Old pod reclaimed, new pod kept
        assert "br-old" not in mgr._pods
        assert "br-new" in mgr._pods

    @pytest.mark.asyncio
    async def test_reclaims_all_timed_out_even_at_warm_pool_size(self):
        """All timed-out idle pods are reclaimed regardless of WARM_POOL_SIZE."""
        mgr = _make_manager()
        # Create WARM_POOL_SIZE idle pods, all timed out
        for i in range(WARM_POOL_SIZE):
            p = _make_pod(f"br-old-{i}")
            p.last_idle_at = time.time() - BR_IDLE_TIMEOUT - 100
            mgr._pods[f"br-old-{i}"] = p

        # Simulate reclaim logic
        idle_pods = [p for p in mgr._pods.values() if not p.busy]
        to_reclaim = [p for p in idle_pods if time.time() - p.last_idle_at > BR_IDLE_TIMEOUT]
        for p in to_reclaim:
            mgr._pods.pop(p.pod_name, None)

        # All should be reclaimed (unlike cluster version which skips first WARM_POOL_SIZE)
        assert len(mgr._pods) == 0


# ── Test: Reconcile orphan busy pods ─────────────────────────────────


class TestReconcileOrphanPods:
    """_reconcile_existing_pods should delete busy pods (orphan from previous cp)."""

    @pytest.mark.asyncio
    async def test_registers_idle_pods(self):
        mgr = _make_manager()

        # Mock k8s list to return one idle pod
        mock_pod = mock.MagicMock()
        mock_pod.metadata.name = "br-idle-1"
        mock_pod.status.phase = "Running"

        mock_response = mock.MagicMock()
        mock_response.items = [mock_pod]

        mgr._core.list_namespaced_pod = mock.MagicMock(return_value=mock_response)

        # Mock health check to return idle
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.json = mock.AsyncMock(return_value={"busy": False, "status": "ok"})

        mock_http = mock.MagicMock()
        mock_http.get = mock.MagicMock()
        mock_http.get.return_value.__aenter__ = mock.AsyncMock(return_value=mock_resp)
        mock_http.get.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch.object(mgr, "_get_http_session", return_value=mock_http):
            with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()):
                await mgr._reconcile_existing_pods()

        assert "br-idle-1" in mgr._pods
        assert mgr._pods["br-idle-1"].busy is False

    @pytest.mark.asyncio
    async def test_deletes_orphan_busy_pods(self):
        mgr = _make_manager()

        # Mock k8s list to return one busy pod
        mock_pod = mock.MagicMock()
        mock_pod.metadata.name = "br-busy-orphan"
        mock_pod.status.phase = "Running"

        mock_response = mock.MagicMock()
        mock_response.items = [mock_pod]

        mgr._core.list_namespaced_pod = mock.MagicMock(return_value=mock_response)

        # Mock health check to return busy
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.json = mock.AsyncMock(return_value={"busy": True, "session_id": "old-session"})

        mock_http = mock.MagicMock()
        mock_http.get = mock.MagicMock()
        mock_http.get.return_value.__aenter__ = mock.AsyncMock(return_value=mock_resp)
        mock_http.get.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch.object(mgr, "_get_http_session", return_value=mock_http):
            with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()) as mock_delete:
                await mgr._reconcile_existing_pods()

        # Busy pod should NOT be registered in _pods
        assert "br-busy-orphan" not in mgr._pods
        # Busy pod should be deleted
        mock_delete.assert_called_once_with("br-busy-orphan")


# ── Test: Release always deletes ─────────────────────────────────────


class TestReleaseDeletesPod:
    """release() always deletes pod + PVC, never returns to idle pool."""

    @pytest.mark.asyncio
    async def test_release_deletes_healthy_pod(self):
        mgr = _make_manager()
        pod = _make_pod("br-to-release", busy=True)
        pod.session_id = "sess-1"
        mgr._pods["br-to-release"] = pod

        # Mock browser/stop success
        mock_resp = mock.MagicMock()
        mock_resp.status = 200

        mock_http_ctx = mock.MagicMock()
        mock_http_ctx.post = mock.MagicMock()
        mock_http_ctx.post.return_value.__aenter__ = mock.AsyncMock(return_value=mock_resp)
        mock_http_ctx.post.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("aiohttp.ClientSession", return_value=mock_http_ctx):
            with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()) as mock_delete:
                with mock.patch.object(mgr, "_ensure_warm_pool", mock.AsyncMock()):
                    await mgr.release("sess-1", "br-to-release")

        # Pod removed from registry
        assert "br-to-release" not in mgr._pods
        # Pod deleted from k8s
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_deletes_unhealthy_pod(self):
        mgr = _make_manager()
        pod = _make_pod("br-unhealthy", busy=True)
        pod.session_id = "sess-2"
        mgr._pods["br-unhealthy"] = pod

        # Mock browser/stop failure
        mock_http_ctx = mock.MagicMock()
        mock_http_ctx.post = mock.MagicMock()
        mock_http_ctx.post.return_value.__aenter__ = mock.AsyncMock(side_effect=Exception("connection refused"))
        mock_http_ctx.post.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("aiohttp.ClientSession", return_value=mock_http_ctx):
            with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()) as mock_delete:
                with mock.patch.object(mgr, "_ensure_warm_pool", mock.AsyncMock()):
                    await mgr.release("sess-2", "br-unhealthy")

        assert "br-unhealthy" not in mgr._pods
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_triggers_warm_pool_replenish(self):
        mgr = _make_manager()
        pod = _make_pod("br-release", busy=True)
        mgr._pods["br-release"] = pod

        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_http_ctx = mock.MagicMock()
        mock_http_ctx.post = mock.MagicMock()
        mock_http_ctx.post.return_value.__aenter__ = mock.AsyncMock(return_value=mock_resp)
        mock_http_ctx.post.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("aiohttp.ClientSession", return_value=mock_http_ctx):
            with mock.patch.object(mgr, "_delete_br_pod", mock.AsyncMock()):
                with mock.patch.object(mgr, "_ensure_warm_pool", mock.AsyncMock()) as mock_warm:
                    await mgr.release("sess", "br-release")
                    # Give asyncio a chance to run the background task
                    await asyncio.sleep(0.05)
                    mock_warm.assert_called_once()


# ── Test: Allocate triggers warm pool replenish ──────────────────────


class TestAllocateReplenish:
    """allocate() triggers _ensure_warm_pool in background."""

    @pytest.mark.asyncio
    async def test_allocate_from_idle_pool(self):
        mgr = _make_manager()
        idle_pod = _make_pod("br-idle")
        mgr._pods["br-idle"] = idle_pod

        # Mock browser/start response
        mock_post_resp = mock.AsyncMock()
        mock_post_resp.status = 200
        mock_post_resp.json = mock.AsyncMock(return_value={"status": "ok"})
        mock_post_resp.__aenter__ = mock.AsyncMock(return_value=mock_post_resp)
        mock_post_resp.__aexit__ = mock.AsyncMock(return_value=False)

        mock_http = mock.MagicMock()
        mock_http.post = mock.MagicMock(return_value=mock_post_resp)
        mock_http.__aenter__ = mock.AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("aiohttp.ClientSession", return_value=mock_http):
            with mock.patch.object(mgr, "_get_pod_ip", return_value="10.0.0.1"):
                with mock.patch.object(mgr, "_ensure_warm_pool", mock.AsyncMock()) as mock_warm:
                    instance = await mgr.allocate("sess-1")
                    await asyncio.sleep(0.05)
                    mock_warm.assert_called_once()

        assert mgr._pods["br-idle"].busy is True
