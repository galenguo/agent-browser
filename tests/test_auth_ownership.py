"""
API Key 认证 + 会话所有权检查单元测试

使用 FastAPI TestClient + patch，无需真实浏览器或 lifespan。
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 导入一次，后续通过 patch 控制模块级变量
import api as api_module


def _make_mock_session(user_id: str, session_id: str):
    session = MagicMock()
    session.user_id = user_id
    session.session_id = session_id
    session.created_at = time.time()
    session.last_activity = time.time()
    session.tasks = {}
    session.task_lock = asyncio.Lock()
    session.browser_instance = MagicMock()
    return session


def _make_manager(sessions: dict = None):
    mgr = MagicMock()
    mgr.sessions = sessions or {}
    mgr.max_concurrent = 10
    mgr.browser_pool = MagicMock()
    mgr.browser_pool.mode = "local"
    mgr.get_session_status = AsyncMock(return_value={
        "session_id": "sid", "user_id": "uid",
        "created_at": time.time(), "last_activity": time.time(),
        "idle_time": 0.0, "tasks": {}, "browser_node": None,
    })
    mgr.close_session = AsyncMock()
    mgr.create_session = AsyncMock(return_value=("new_sid", None))
    return mgr


def client_with(api_key: str = None, sessions: dict = None):
    """Return a TestClient with patched _session_manager and _api_key."""
    mgr = _make_manager(sessions)
    patches = [
        patch.object(api_module, "_session_manager", mgr),
        patch.object(api_module, "_api_key", api_key),
    ]
    for p in patches:
        p.start()
    c = TestClient(api_module.app, raise_server_exceptions=False)
    # stop patches after client is created (lifespan won't run with TestClient default)
    for p in patches:
        p.stop()
    # re-apply for the duration of the test via context manager approach
    # simpler: just return client + manager, caller patches inline
    return c, mgr


# ─── helpers ───────────────────────────────────────────────────────────────

def get(path, key=None, sessions=None, **kwargs):
    mgr = _make_manager(sessions)
    with patch.object(api_module, "_session_manager", mgr), \
         patch.object(api_module, "_api_key", key):
        c = TestClient(api_module.app, raise_server_exceptions=False)
        return c.get(path, **kwargs), mgr


def post(path, key=None, sessions=None, **kwargs):
    mgr = _make_manager(sessions)
    with patch.object(api_module, "_session_manager", mgr), \
         patch.object(api_module, "_api_key", key):
        c = TestClient(api_module.app, raise_server_exceptions=False)
        return c.post(path, **kwargs), mgr


def delete(path, key=None, sessions=None, **kwargs):
    mgr = _make_manager(sessions)
    with patch.object(api_module, "_session_manager", mgr), \
         patch.object(api_module, "_api_key", key):
        c = TestClient(api_module.app, raise_server_exceptions=False)
        return c.delete(path, **kwargs), mgr


# ─── No API Key (single-tenant) ────────────────────────────────────────────

class TestNoApiKey:
    def test_health(self):
        resp, _ = get("/health")
        assert resp.status_code == 200

    def test_list_sessions(self):
        resp, _ = get("/sessions")
        assert resp.status_code == 200

    def test_get_session(self):
        sid = "sess_abc"
        resp, _ = get(f"/sessions/{sid}", sessions={sid: _make_mock_session("u1", sid)})
        assert resp.status_code == 200

    def test_delete_session(self):
        sid = "sess_abc"
        resp, _ = delete(f"/sessions/{sid}", sessions={sid: _make_mock_session("u1", sid)})
        assert resp.status_code == 200


# ─── API Key authentication ────────────────────────────────────────────────

class TestApiKeyAuth:
    def test_missing_key_401(self):
        resp, _ = get("/sessions", key="secret")
        assert resp.status_code == 401

    def test_wrong_key_401(self):
        resp, _ = get("/sessions", key="secret", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_passes(self):
        resp, _ = get("/sessions", key="secret", headers={"X-API-Key": "secret"})
        assert resp.status_code == 200

    def test_health_no_auth_needed(self):
        resp, _ = get("/health", key="secret")
        assert resp.status_code == 200

    def test_401_mentions_auth(self):
        resp, _ = get("/sessions", key="secret")
        detail = resp.json()["detail"].lower()
        assert "auth" in detail or "key" in detail


# ─── Session ownership ─────────────────────────────────────────────────────

class TestSessionOwnership:
    def test_owner_can_access(self):
        sid = "sess_abc"
        resp, _ = get(
            f"/sessions/{sid}", key="my-key",
            sessions={sid: _make_mock_session("my-key", sid)},
            headers={"X-API-Key": "my-key"},
        )
        assert resp.status_code == 200

    def test_other_user_404(self):
        """Other user's session returns 404 (not 403, prevents enumeration)"""
        sid = "sess_abc"
        resp, _ = get(
            f"/sessions/{sid}", key="my-key",
            sessions={sid: _make_mock_session("other-key", sid)},
            headers={"X-API-Key": "my-key"},
        )
        assert resp.status_code == 404

    def test_access_denied_returns_not_found(self):
        """Access denied message is generic 'Session not found' (no leakage)"""
        sid = "sess_abc"
        resp, _ = get(
            f"/sessions/{sid}", key="my-key",
            sessions={sid: _make_mock_session("other-key", sid)},
            headers={"X-API-Key": "my-key"},
        )
        assert resp.json()["detail"] == "Session not found"

    def test_owner_can_delete(self):
        sid = "sess_abc"
        resp, _ = delete(
            f"/sessions/{sid}", key="my-key",
            sessions={sid: _make_mock_session("my-key", sid)},
            headers={"X-API-Key": "my-key"},
        )
        assert resp.status_code == 200

    def test_other_user_cannot_delete(self):
        sid = "sess_abc"
        resp, _ = delete(
            f"/sessions/{sid}", key="my-key",
            sessions={sid: _make_mock_session("other-key", sid)},
            headers={"X-API-Key": "my-key"},
        )
        assert resp.status_code == 404

    def test_list_sessions_scoped_to_user(self):
        """list_sessions 只返回当前用户的会话（IDOR 防护）"""
        sessions = {
            "s1": _make_mock_session("key-a", "s1"),
            "s2": _make_mock_session("key-b", "s2"),
        }
        resp, _ = get("/sessions", key="key-a", sessions=sessions, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 200
        # key-a 只能看到 s1（自己的会话）
        ids = {s["session_id"] for s in resp.json()["sessions"]}
        assert ids == {"s1"}
        assert resp.json()["total"] == 1


# ─── create_session uses API key as user_id ────────────────────────────────

class TestCreateSessionUsesApiKey:
    def test_api_key_overrides_user_id(self):
        mgr = _make_manager()
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "my-api-key"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                "/sessions/create",
                json={"user_id": "attacker-injected"},
                headers={"X-API-Key": "my-api-key"},
            )
        assert resp.status_code == 200
        assert mgr.create_session.call_args.kwargs["user_id"] == "my-api-key"

    def test_no_api_key_uses_request_user_id(self):
        mgr = _make_manager()
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", None):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post("/sessions/create", json={"user_id": "real-user-123"})
        assert resp.status_code == 200
        assert mgr.create_session.call_args.kwargs["user_id"] == "real-user-123"
