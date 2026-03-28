#!/usr/bin/env python3
"""
快速性能压测脚本

测试 512MB 内存配置下的性能表现
"""
import asyncio
import time
import httpx


async def test_sequential_tasks(num_tasks=5):
    """顺序执行多个任务"""
    print(f"\n=== 顺序执行 {num_tasks} 个任务 ===")

    base_url = "http://localhost:8000"

    async with httpx.AsyncClient(timeout=120.0) as client:
        results = []

        for i in range(num_tasks):
            print(f"\n任务 {i+1}/{num_tasks}")

            # 提交任务
            start = time.time()
            resp = await client.post(
                f"{base_url}/tasks",
                json={
                    "task": f"访问 https://example.com 并获取页面标题（任务 {i+1}）",
                    "model": "glm-5-turbo",
                    "max_steps": 3
                }
            )
            task_data = resp.json()
            task_id = task_data["task_id"]
            print(f"  任务 ID: {task_id}")

            # 等待任务完成
            max_wait = 90
            wait_start = time.time()
            status = "running"

            while status == "running" and (time.time() - wait_start) < max_wait:
                await asyncio.sleep(3)
                resp = await client.get(f"{base_url}/tasks/{task_id}")
                task_status = resp.json()
                status = task_status["status"]

            elapsed = time.time() - start

            print(f"  状态: {status}")
            print(f"  耗时: {elapsed:.2f}s")

            results.append({
                "task_id": task_id,
                "status": status,
                "elapsed": elapsed
            })

            # 任务间隔 5 秒
            if i < num_tasks - 1:
                print("  等待 5 秒...")
                await asyncio.sleep(5)

        # 统计
        print(f"\n=== 测试结果 ===")
        completed = sum(1 for r in results if r["status"] == "completed")
        total_time = sum(r["elapsed"] for r in results)
        avg_time = total_time / len(results) if results else 0

        print(f"完成: {completed}/{num_tasks}")
        print(f"总耗时: {total_time:.2f}s")
        print(f"平均耗时: {avg_time:.2f}s")

        return results


async def test_memory_stress():
    """内存压力测试"""
    print(f"\n=== 内存压力测试 ===")

    base_url = "http://localhost:8000"

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 提交一个任务
        resp = await client.post(
            f"{base_url}/tasks",
            json={
                "task": "访问 https://www.zhipin.com 并获取页面标题",
                "model": "glm-5-turbo",
                "max_steps": 5
            }
        )
        task_data = resp.json()
        task_id = task_data["task_id"]
        print(f"任务 ID: {task_id}")

        # 监控资源使用
        import subprocess

        print("\n监控资源使用（每 3 秒采样）...")
        samples = []

        for i in range(20):  # 监控 60 秒
            try:
                result = subprocess.run(
                    ["docker", "stats", "agent-browser", "--no-stream",
                     "--format", "{{.CPUPerc}},{{.MemUsage}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    output = result.stdout.strip()
                    if output:
                        cpu, mem = output.split(',')
                        samples.append({"cpu": cpu, "memory": mem})
                        print(f"  采样 {i+1}: CPU={cpu}, 内存={mem}")
            except Exception as e:
                print(f"  采样失败: {e}")

            await asyncio.sleep(3)

        # 检查任务状态
        resp = await client.get(f"{base_url}/tasks/{task_id}")
        task_status = resp.json()
        print(f"\n任务状态: {task_status['status']}")

        return samples


async def main():
    """主函数"""
    print("=" * 60)
    print("512MB 内存配置性能压测")
    print("=" * 60)

    # 测试 1: 顺序执行任务
    try:
        await test_sequential_tasks(num_tasks=3)
    except Exception as e:
        print(f"\n顺序任务测试失败: {e}")

    # 等待 10 秒
    print("\n等待 10 秒...")
    await asyncio.sleep(10)

    # 测试 2: 内存压力测试
    try:
        await test_memory_stress()
    except Exception as e:
        print(f"\n内存压力测试失败: {e}")

    print("\n" + "=" * 60)
    print("压测完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
