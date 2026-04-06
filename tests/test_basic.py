#!/usr/bin/env python3
"""
简单的功能测试脚本

测试多用户 Session Pool API 的基本功能
"""
import asyncio

import httpx


async def test_basic_functionality():
    """测试基本功能"""
    base_url = "http://localhost:8001"  # 使用不同端口避免冲突

    print("=" * 60)
    print("多用户 Session Pool API 功能测试")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. 健康检查
        print("\n1. 测试健康检查...")
        try:
            resp = await client.get(f"{base_url}/health")
            print(f"   ✅ 健康检查: {resp.json()}")
        except Exception as e:
            print(f"   ❌ 健康检查失败: {e}")
            return

        # 2. 创建会话
        print("\n2. 测试创建会话...")
        try:
            resp = await client.post(
                f"{base_url}/sessions/create",
                json={"user_id": "test_user_1", "browser_type": "local"}
            )
            session_data = resp.json()
            session_id = session_data["session_id"]
            print(f"   ✅ 会话创建成功: {session_id}")
            print(f"   CDP URL: {session_data['cdp_url']}")
        except Exception as e:
            print(f"   ❌ 会话创建失败: {e}")
            return

        # 3. 查询会话状态
        print("\n3. 测试查询会话状态...")
        try:
            resp = await client.get(f"{base_url}/sessions/{session_id}/status")
            print(f"   ✅ 会话状态: {resp.json()}")
        except Exception as e:
            print(f"   ❌ 查询失败: {e}")

        # 4. 列出所有会话
        print("\n4. 测试列出所有会话...")
        try:
            resp = await client.get(f"{base_url}/sessions")
            sessions = resp.json()
            print(f"   ✅ 当前会话数: {len(sessions)}")
        except Exception as e:
            print(f"   ❌ 列出会话失败: {e}")

        # 5. 提交任务
        print("\n5. 测试提交任务...")
        try:
            resp = await client.post(
                f"{base_url}/sessions/{session_id}/task",
                json={
                    "task": "访问 https://example.com 并获取页面标题",
                    "model": "glm-5-turbo",
                    "max_steps": 3
                }
            )
            task_data = resp.json()
            task_id = task_data["task_id"]
            print(f"   ✅ 任务提交成功: {task_id}")
        except Exception as e:
            print(f"   ❌ 任务提交失败: {e}")
            task_id = None

        # 6. 查询任务状态
        if task_id:
            print("\n6. 测试查询任务状态...")
            try:
                await asyncio.sleep(5)  # 等待任务开始执行
                resp = await client.get(
                    f"{base_url}/sessions/{session_id}/tasks/{task_id}"
                )
                print(f"   ✅ 任务状态: {resp.json()}")
            except Exception as e:
                print(f"   ❌ 查询任务失败: {e}")

        # 7. 销毁会话
        print("\n7. 测试销毁会话...")
        try:
            resp = await client.delete(f"{base_url}/sessions/{session_id}")
            print(f"   ✅ 会话销毁成功: {resp.json()}")
        except Exception as e:
            print(f"   ❌ 销毁会话失败: {e}")

        # 8. 获取统计信息
        print("\n8. 测试获取统计信息...")
        try:
            resp = await client.get(f"{base_url}/stats")
            print(f"   ✅ 统计信息: {resp.json()}")
        except Exception as e:
            print(f"   ❌ 获取统计失败: {e}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_basic_functionality())
