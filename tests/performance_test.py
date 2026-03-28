"""
性能压测脚本

测试多用户并发场景下的系统性能：
- 并发会话创建
- 并发任务执行
- 资源使用监控
- 响应时间统计
"""
import asyncio
import time
import statistics
from typing import List, Dict
import httpx


class PerformanceTest:
    """性能测试工具"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[Dict] = []

    async def test_concurrent_sessions(self, num_sessions: int = 10):
        """测试并发会话创建"""
        print(f"\n=== 测试并发创建 {num_sessions} 个会话 ===")

        async with httpx.AsyncClient(timeout=60.0) as client:
            start_time = time.time()

            tasks = []
            for i in range(num_sessions):
                task = self._create_session(client, f"user_{i}")
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            elapsed = time.time() - start_time

            # 统计结果
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            error_count = len(results) - success_count

            print(f"总耗时: {elapsed:.2f}s")
            print(f"成功: {success_count}, 失败: {error_count}")
            print(f"平均每个会话: {elapsed/num_sessions:.2f}s")

            return {
                "test": "concurrent_sessions",
                "num_sessions": num_sessions,
                "elapsed": elapsed,
                "success": success_count,
                "error": error_count,
                "avg_per_session": elapsed/num_sessions
            }

    async def _create_session(self, client: httpx.AsyncClient, user_id: str):
        """创建单个会话"""
        response = await client.post(
            f"{self.base_url}/sessions/create",
            json={"user_id": user_id, "browser_type": "local"}
        )
        response.raise_for_status()
        return response.json()

    async def test_concurrent_tasks(
        self,
        num_tasks: int = 10,
        task_description: str = "访问 https://example.com 并获取页面标题"
    ):
        """测试并发任务执行"""
        print(f"\n=== 测试并发执行 {num_tasks} 个任务 ===")

        async with httpx.AsyncClient(timeout=300.0) as client:
            # 先创建会话
            print("创建测试会话...")
            session_resp = await self._create_session(client, "perf_test_user")
            session_id = session_resp["session_id"]
            print(f"会话创建成功: {session_id}")

            # 并发提交任务
            start_time = time.time()

            tasks = []
            for i in range(num_tasks):
                task = self._submit_task(
                    client,
                    session_id,
                    f"{task_description} (任务 {i+1})"
                )
                tasks.append(task)

            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            submit_elapsed = time.time() - start_time

            # 等待所有任务完成
            print("等待任务完成...")
            task_ids = [r["task_id"] for r in task_results if not isinstance(r, Exception)]

            completed = 0
            max_wait = 300  # 最多等待 5 分钟
            wait_start = time.time()

            while completed < len(task_ids) and (time.time() - wait_start) < max_wait:
                await asyncio.sleep(5)

                # 检查任务状态
                status_tasks = [
                    self._get_task_status(client, session_id, task_id)
                    for task_id in task_ids
                ]
                statuses = await asyncio.gather(*status_tasks, return_exceptions=True)

                completed = sum(
                    1 for s in statuses
                    if not isinstance(s, Exception) and s.get("status") in ["completed", "failed"]
                )

                print(f"已完成: {completed}/{len(task_ids)}")

            total_elapsed = time.time() - start_time

            # 清理会话
            await client.delete(f"{self.base_url}/sessions/{session_id}")

            print(f"提交耗时: {submit_elapsed:.2f}s")
            print(f"总耗时: {total_elapsed:.2f}s")
            print(f"完成任务: {completed}/{len(task_ids)}")

            return {
                "test": "concurrent_tasks",
                "num_tasks": num_tasks,
                "submit_elapsed": submit_elapsed,
                "total_elapsed": total_elapsed,
                "completed": completed,
                "success_rate": completed / len(task_ids) if task_ids else 0
            }

    async def _submit_task(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        task: str
    ):
        """提交单个任务"""
        response = await client.post(
            f"{self.base_url}/sessions/{session_id}/task",
            json={
                "task": task,
                "model": "glm-5-turbo",
                "max_steps": 3
            }
        )
        response.raise_for_status()
        return response.json()

    async def _get_task_status(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        task_id: str
    ):
        """获取任务状态"""
        response = await client.get(
            f"{self.base_url}/sessions/{session_id}/tasks/{task_id}"
        )
        response.raise_for_status()
        return response.json()

    async def test_resource_usage(self, duration: int = 60):
        """测试资源使用情况"""
        print(f"\n=== 监控资源使用 {duration}s ===")

        import subprocess

        samples = []
        start_time = time.time()

        while (time.time() - start_time) < duration:
            try:
                # 获取容器资源使用
                result = subprocess.run(
                    ["docker", "stats", "agent-browser", "--no-stream", "--format", "{{.CPUPerc}},{{.MemUsage}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    output = result.stdout.strip()
                    if output:
                        cpu, mem = output.split(',')
                        samples.append({
                            "timestamp": time.time(),
                            "cpu": cpu,
                            "memory": mem
                        })

            except Exception as e:
                print(f"监控错误: {e}")

            await asyncio.sleep(5)

        print(f"采集了 {len(samples)} 个样本")

        return {
            "test": "resource_usage",
            "duration": duration,
            "samples": samples
        }

    async def run_all_tests(self):
        """运行所有测试"""
        print("=" * 60)
        print("开始性能压测")
        print("=" * 60)

        results = []

        # 测试 1: 并发会话创建
        try:
            result = await self.test_concurrent_sessions(num_sessions=5)
            results.append(result)
        except Exception as e:
            print(f"测试失败: {e}")
            results.append({"test": "concurrent_sessions", "error": str(e)})

        # 测试 2: 并发任务执行
        try:
            result = await self.test_concurrent_tasks(num_tasks=3)
            results.append(result)
        except Exception as e:
            print(f"测试失败: {e}")
            results.append({"test": "concurrent_tasks", "error": str(e)})

        # 测试 3: 资源使用监控
        try:
            result = await self.test_resource_usage(duration=30)
            results.append(result)
        except Exception as e:
            print(f"测试失败: {e}")
            results.append({"test": "resource_usage", "error": str(e)})

        print("\n" + "=" * 60)
        print("压测完成")
        print("=" * 60)

        return results


async def main():
    """主函数"""
    tester = PerformanceTest()
    results = await tester.run_all_tests()

    # 打印汇总
    print("\n=== 测试汇总 ===")
    for result in results:
        print(f"\n{result.get('test', 'unknown')}:")
        for key, value in result.items():
            if key != 'test' and key != 'samples':
                print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
