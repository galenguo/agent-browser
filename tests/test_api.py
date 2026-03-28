"""
测试 v2 多用户会话 API

测试场景：
1. 创建会话
2. 提交任务到会话
3. 查询任务状态
4. 查询会话状态
5. 删除会话
6. 向后兼容测试（旧版 /tasks API）
"""

import asyncio
import httpx
import pytest

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_create_session():
    """测试创建会话"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/sessions/create",
            json={"user_id": "test_user_001"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["user_id"] == "test_user_001"
        return data["session_id"]


@pytest.mark.asyncio
async def test_submit_task():
    """测试提交任务"""
    # 先创建会话
    session_id = await test_create_session()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/sessions/{session_id}/task",
            json={
                "task": "打开 https://www.baidu.com 并搜索 Python",
                "model": "glm-5-turbo",
                "max_steps": 10
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["session_id"] == session_id
        return session_id, data["task_id"]


@pytest.mark.asyncio
async def test_get_task_status():
    """测试查询任务状态"""
    session_id, task_id = await test_submit_task()

    async with httpx.AsyncClient() as client:
        # 等待任务执行
        await asyncio.sleep(5)

        response = await client.get(
            f"{BASE_URL}/sessions/{session_id}/tasks/{task_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task_id
        assert data["status"] in ["running", "completed", "failed"]


@pytest.mark.asyncio
async def test_get_session_status():
    """测试查询会话状态"""
    session_id = await test_create_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert "created_at" in data
        assert "last_activity" in data


@pytest.mark.asyncio
async def test_delete_session():
    """测试删除会话"""
    session_id = await test_create_session()

    async with httpx.AsyncClient() as client:
        response = await client.delete(f"{BASE_URL}/sessions/{session_id}")
        assert response.status_code == 200

        # 验证会话已删除
        response = await client.get(f"{BASE_URL}/sessions/{session_id}")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_legacy_api():
    """测试向后兼容的旧版 API"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/tasks",
            json={
                "task": "打开 https://www.google.com",
                "model": "glm-5-turbo",
                "max_steps": 5
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "session_id" in data

        task_id = data["task_id"]

        # 查询任务状态
        await asyncio.sleep(3)
        response = await client.get(f"{BASE_URL}/tasks/{task_id}")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_health():
    """测试健康检查"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "sessions" in data
        assert "browser_mode" in data


if __name__ == "__main__":
    # 简单的手动测试
    print("Running manual tests...")

    async def run_tests():
        print("\n1. Testing health endpoint...")
        await test_health()
        print("✅ Health check passed")

        print("\n2. Testing create session...")
        session_id = await test_create_session()
        print(f"✅ Session created: {session_id}")

        print("\n3. Testing submit task...")
        session_id, task_id = await test_submit_task()
        print(f"✅ Task submitted: {task_id}")

        print("\n4. Testing legacy API...")
        await test_legacy_api()
        print("✅ Legacy API works")

        print("\n✅ All tests passed!")

    asyncio.run(run_tests())
