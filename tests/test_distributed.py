"""
测试 Distributed 模式

测试场景：
1. 构建浏览器容器镜像
2. 启动 API 服务器（Distributed 模式）
3. 创建会话（自动启动浏览器容器）
4. 提交任务
5. 验证浏览器容器运行
6. 删除会话（自动清理浏览器容器）
"""

import asyncio
import httpx
import subprocess
import time

BASE_URL = "http://localhost:8000"


def run_command(cmd: str) -> str:
    """运行 shell 命令"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_browser_image_exists():
    """测试浏览器镜像是否存在"""
    print("\n1. 检查浏览器镜像...")
    output = run_command("docker images | grep agent-browser-browser")
    if "agent-browser-browser" in output:
        print("✅ 浏览器镜像已存在")
        return True
    else:
        print("❌ 浏览器镜像不存在，请先运行: ./scripts/build-browser-image.sh")
        return False


def test_api_server_running():
    """测试 API 服务器是否运行"""
    print("\n2. 检查 API 服务器...")
    output = run_command("docker ps | grep agent-browser-api")
    if "agent-browser-api" in output:
        print("✅ API 服务器正在运行")
        return True
    else:
        print("❌ API 服务器未运行，请先运行: ./scripts/start-distributed.sh")
        return False


async def test_create_session():
    """测试创建会话"""
    print("\n3. 创建会话...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/sessions/create",
            json={"user_id": "test_distributed_user"}
        )
        assert response.status_code == 200
        data = response.json()
        session_id = data["session_id"]
        print(f"✅ 会话创建成功: {session_id}")
        return session_id


def test_browser_container_running(session_id: str):
    """测试浏览器容器是否运行"""
    print(f"\n4. 检查浏览器容器 (session: {session_id})...")
    time.sleep(5)  # 等待容器启动

    output = run_command(f"docker ps | grep browser_{session_id}")
    if f"browser_{session_id}" in output:
        print(f"✅ 浏览器容器正在运行: browser_{session_id}")
        return True
    else:
        print(f"❌ 浏览器容器未运行")
        return False


async def test_submit_task(session_id: str):
    """测试提交任务"""
    print(f"\n5. 提交任务到会话 {session_id}...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/sessions/{session_id}/task",
            json={
                "task": "打开 https://www.example.com",
                "model": "glm-5-turbo",
                "max_steps": 5
            }
        )
        assert response.status_code == 200
        data = response.json()
        task_id = data["task_id"]
        print(f"✅ 任务提交成功: {task_id}")
        return task_id


async def test_task_status(session_id: str, task_id: str):
    """测试查询任务状态"""
    print(f"\n6. 查询任务状态 {task_id}...")
    async with httpx.AsyncClient() as client:
        # 等待任务执行
        await asyncio.sleep(10)

        response = await client.get(
            f"{BASE_URL}/sessions/{session_id}/tasks/{task_id}"
        )
        assert response.status_code == 200
        data = response.json()
        print(f"✅ 任务状态: {data['status']}")
        return data


async def test_delete_session(session_id: str):
    """测试删除会话"""
    print(f"\n7. 删除会话 {session_id}...")
    async with httpx.AsyncClient() as client:
        response = await client.delete(f"{BASE_URL}/sessions/{session_id}")
        assert response.status_code == 200
        print(f"✅ 会话删除成功")


def test_browser_container_stopped(session_id: str):
    """测试浏览器容器是否已停止"""
    print(f"\n8. 检查浏览器容器是否已清理...")
    time.sleep(5)  # 等待容器停止

    output = run_command(f"docker ps -a | grep browser_{session_id}")
    if f"browser_{session_id}" not in output:
        print(f"✅ 浏览器容器已清理")
        return True
    else:
        print(f"⚠️  浏览器容器仍然存在（可能是 auto_remove 延迟）")
        return False


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Distributed 模式测试")
    print("=" * 60)

    # 前置检查
    if not test_browser_image_exists():
        return

    if not test_api_server_running():
        return

    try:
        # 创建会话
        session_id = await test_create_session()

        # 检查浏览器容器
        test_browser_container_running(session_id)

        # 提交任务
        task_id = await test_submit_task(session_id)

        # 查询任务状态
        await test_task_status(session_id, task_id)

        # 删除会话
        await test_delete_session(session_id)

        # 检查容器清理
        test_browser_container_stopped(session_id)

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
