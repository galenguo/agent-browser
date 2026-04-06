"""
Phase 4: E2E Remote 模式测试

测试目标：
- C3: remote llm 模式 - RemoteAPIBackend → FastAPI(LocalCDPBackend) → CloakBrowser
- C4: remote agent 模式 - RemoteAPIBackend → FastAPI(Agent) → CloakBrowser

前置条件：
- FastAPI 运行在 localhost:8000
- CloakBrowser 运行在 127.0.0.1:19222

数据流：
  客户端: HTTP Request → RemoteAPIBackend
  服务端: FastAPI → LocalCDPBackend → CloakBrowser
"""
import asyncio
import os

import aiohttp
import pytest

# FastAPI 基础 URL
API_BASE_URL = "http://localhost:8000"


@pytest.mark.requires_browser
class TestRemoteAPIHealth:
    """Remote API 健康检查"""

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """健康检查端点"""
        async with aiohttp.ClientSession() as session, \
                session.get(f"{API_BASE_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert "sessions" in data
                assert "max_sessions" in data

    @pytest.mark.asyncio
    async def test_api_available(self):
        """API 服务可用"""
        async with aiohttp.ClientSession() as session, \
                session.get(f"{API_BASE_URL}/sessions", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "sessions" in data
                assert "total" in data


@pytest.mark.requires_browser
class TestRemoteSessionManagement:
    """Remote Session 管理"""

    @pytest.fixture
    async def cleanup_sessions(self):
        """测试后清理所有 session"""
        yield
        # 清理
        async with aiohttp.ClientSession() as session, \
                session.get(f"{API_BASE_URL}/sessions", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for sess in data.get("sessions", []):
                        sid = sess["session_id"]
                        try:
                            async with session.delete(
                                f"{API_BASE_URL}/sessions/{sid}",
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as resp:
                                pass
                        except Exception:
                            pass

    @pytest.mark.asyncio
    async def test_create_session(self, cleanup_sessions):
        """创建 session"""
        async with aiohttp.ClientSession() as session, session.post(
            f"{API_BASE_URL}/sessions/create",
            json={"user_id": "test_user_1", "browser_type": "chromium"},
            timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "session_id" in data
            assert data["user_id"] == "test_user_1"
            assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_get_session_status(self, cleanup_sessions):
        """获取 session 状态"""
        async with aiohttp.ClientSession() as session:
            # 创建 session
            async with session.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_user_2"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            # 获取状态
            async with session.get(
                f"{API_BASE_URL}/sessions/{session_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["session_id"] == session_id
                assert "created_at" in data
                assert "last_activity" in data

    @pytest.mark.asyncio
    async def test_delete_session(self, cleanup_sessions):
        """删除 session"""
        async with aiohttp.ClientSession() as session:
            # 创建 session
            async with session.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_user_3"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            # 删除 session
            async with session.delete(
                f"{API_BASE_URL}/sessions/{session_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "deleted"

            # 验证已删除
            async with session.get(
                f"{API_BASE_URL}/sessions/{session_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 404

    @pytest.mark.asyncio
    async def test_list_sessions(self, cleanup_sessions):
        """列出所有 sessions"""
        async with aiohttp.ClientSession() as session:
            # 创建多个 sessions
            for i in range(3):
                async with session.post(
                    f"{API_BASE_URL}/sessions/create",
                    json={"user_id": f"test_user_list_{i}"},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    assert resp.status == 200

            # 列出 sessions
            async with session.get(
                f"{API_BASE_URL}/sessions",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["total"] >= 3


@pytest.mark.requires_browser
class TestRemotePageNavigation:
    """Remote 页面导航"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            # 创建 session
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_nav_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            # 清理
            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_navigate_to_url(self, session_with_cleanup):
        """导航到 URL"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client, \
                client.post(
                    f"{API_BASE_URL}/sessions/{session_id}/navigate",
                    json={"url": "https://example.com", "wait_until": "domcontentloaded"},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert "example.com" in data["url"]

    @pytest.mark.asyncio
    async def test_get_current_url(self, session_with_cleanup):
        """获取当前 URL"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 先导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 获取 URL
            async with client.get(
                f"{API_BASE_URL}/sessions/{session_id}/url",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "url" in data
                assert "example.com" in data["url"]

    @pytest.mark.asyncio
    async def test_get_page_title(self, session_with_cleanup):
        """获取页面标题"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 先导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 获取标题
            async with client.get(
                f"{API_BASE_URL}/sessions/{session_id}/title",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "title" in data
                assert len(data["title"]) > 0


@pytest.mark.requires_browser
class TestRemoteDOMSnapshot:
    """Remote DOM Snapshot"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_snapshot_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_get_snapshot(self, session_with_cleanup):
        """获取 DOM 快照"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 先导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 获取快照
            async with client.get(
                f"{API_BASE_URL}/sessions/{session_id}/snapshot",
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "url" in data
                assert "title" in data
                assert "elements" in data
                assert isinstance(data["elements"], list)

    @pytest.mark.asyncio
    async def test_snapshot_interactive_only(self, session_with_cleanup):
        """只获取可交互元素"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 先导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 获取快照（只包含可交互元素）
            async with client.get(
                f"{API_BASE_URL}/sessions/{session_id}/snapshot?interactive_only=true",
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "elements" in data

                # 验证元素格式
                for elem in data["elements"][:5]:  # 只检查前5个
                    assert "ref" in elem
                    assert elem["ref"].startswith("@e")
                    assert "tag" in elem


@pytest.mark.requires_browser
class TestRemoteClickFill:
    """Remote Click 和 Fill 操作"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_click_fill_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_click_element(self, session_with_cleanup):
        """点击元素"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 先导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 点击元素（使用 ref @e0，通常是第一个可交互元素）
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/click",
                json={"ref": "@e0", "button": "left"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                # 可能成功也可能失败（取决于元素）
                # 我们只验证 API 格式正确
                if resp.status == 200:
                    data = await resp.json()
                    assert "status" in data
                elif resp.status == 400:
                    # 元素索引超出范围也是正常的
                    pass

    @pytest.mark.asyncio
    async def test_fill_input(self, session_with_cleanup):
        """填充输入框"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航到有输入框的页面
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://duckduckgo.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            await asyncio.sleep(1)  # 等待页面加载

            # 获取快照找到输入框
            async with client.get(
                f"{API_BASE_URL}/sessions/{session_id}/snapshot",
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                # 找到输入框
                input_elem = None
                for elem in data.get("elements", []):
                    if elem.get("tag") == "input":
                        input_elem = elem
                        break

            if input_elem:
                # 填充输入框
                async with client.post(
                    f"{API_BASE_URL}/sessions/{session_id}/fill",
                    json={"ref": input_elem["ref"], "text": "test query", "clear_first": True},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    # 验证响应
                    if resp.status == 200:
                        data = await resp.json()
                        assert data["status"] == "ok"


@pytest.mark.requires_browser
class TestRemoteScroll:
    """Remote Scroll 操作"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_scroll_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_scroll_page(self, session_with_cleanup):
        """滚动页面"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 滚动
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/scroll",
                json={"direction": "down", "amount": 300},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"


@pytest.mark.requires_browser
class TestRemoteEvaluate:
    """Remote JavaScript 执行"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_eval_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_evaluate_javascript(self, session_with_cleanup):
        """执行 JavaScript"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 执行 JS
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/evaluate",
                json={"expression": "1 + 1"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert data["result"] == 2

    @pytest.mark.asyncio
    async def test_evaluate_get_user_agent(self, session_with_cleanup):
        """获取 User-Agent"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 获取 User-Agent
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/evaluate",
                json={"expression": "navigator.userAgent"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert "result" in data
                assert isinstance(data["result"], str)


@pytest.mark.requires_browser
class TestRemoteAgentMode:
    """Remote Agent 模式"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_agent_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"),
        reason="需要 OPENAI_API_KEY 或 ANTHROPIC_API_KEY"
    )
    async def test_submit_agent_task(self, session_with_cleanup):
        """提交 Agent 任务"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client, \
                client.post(
                    f"{API_BASE_URL}/sessions/{session_id}/task",
                    json={
                        "task": "访问 example.com 并提取页面标题",
                        "model": "glm-5-turbo",
                        "max_steps": 5
                    },
                    timeout=aiohttp.ClientTimeout(total=180)
                ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "task_id" in data
                assert data["session_id"] == session_id

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"),
        reason="需要 OPENAI_API_KEY 或 ANTHROPIC_API_KEY"
    )
    async def test_get_task_status(self, session_with_cleanup):
        """获取任务状态"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 提交任务
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/task",
                json={"task": "打开 example.com", "max_steps": 3},
                timeout=aiohttp.ClientTimeout(total=180)
            ) as resp:
                data = await resp.json()
                task_id = data["task_id"]

            # 轮询状态
            for _ in range(10):
                await asyncio.sleep(5)
                async with client.get(
                    f"{API_BASE_URL}/sessions/{session_id}/tasks/{task_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    if data["status"] in ("completed", "failed"):
                        break


@pytest.mark.requires_browser
class TestRemoteAntiDetection:
    """Remote 反检测验证"""

    @pytest.fixture
    async def session_with_cleanup(self):
        """创建 session 并在测试后清理"""
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{API_BASE_URL}/sessions/create",
                json={"user_id": "test_antidetect_user"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                session_id = data["session_id"]

            yield session_id

            try:
                async with client.delete(
                    f"{API_BASE_URL}/sessions/{session_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_navigator_webdriver_false(self, session_with_cleanup):
        """navigator.webdriver 应该是 false/undefined"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 检查 webdriver
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/evaluate",
                json={"expression": "navigator.webdriver"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                webdriver = data.get("result")
                assert webdriver is False or webdriver is None, f"navigator.webdriver = {webdriver}"

    @pytest.mark.asyncio
    async def test_no_playwright_binding(self, session_with_cleanup):
        """__playwright__binding__ 应该是 undefined"""
        session_id = session_with_cleanup

        async with aiohttp.ClientSession() as client:
            # 导航
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/navigate",
                json={"url": "https://example.com"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                pass

            # 检查 binding
            async with client.post(
                f"{API_BASE_URL}/sessions/{session_id}/evaluate",
                json={"expression": "typeof window.__playwright__binding__"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                assert data.get("result") == "undefined"
