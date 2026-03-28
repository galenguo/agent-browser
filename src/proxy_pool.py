"""
代理池管理器

功能：
- 从 PROXY_LIST 环境变量（逗号分隔）或 PROXY_LIST_FILE（JSON）加载代理列表
- 轮询分配健康代理
- 后台健康检查（每 5 分钟）
- 失败标记 + cooldown 自动恢复
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 代理健康检查间隔（秒）
HEALTH_CHECK_INTERVAL = 300
# 失败后 cooldown 时间（秒）
FAILURE_COOLDOWN = 180


class ProxyPool:
    """轻量代理池，支持轮询分配和健康检查"""

    def __init__(self):
        self._proxies: list[str] = []
        self._failed: dict[str, float] = {}  # proxy -> failure_time
        self._index: int = 0
        self._health_task: Optional[asyncio.Task] = None
        self._load_proxies()

    def _load_proxies(self) -> None:
        """从环境变量或文件加载代理列表"""
        # 方式 1: PROXY_LIST 环境变量（逗号分隔）
        proxy_list = os.getenv("PROXY_LIST", "").strip()
        if proxy_list:
            self._proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]
            logger.info(f"Loaded {len(self._proxies)} proxies from PROXY_LIST env")
            return

        # 方式 2: PROXY_LIST_FILE（JSON 数组）
        proxy_file = os.getenv("PROXY_LIST_FILE", "").strip()
        if proxy_file and os.path.exists(proxy_file):
            with open(proxy_file) as f:
                data = json.load(f)
            if isinstance(data, list):
                self._proxies = [str(p) for p in data if p]
            elif isinstance(data, dict) and "proxies" in data:
                self._proxies = [str(p) for p in data["proxies"] if p]
            logger.info(f"Loaded {len(self._proxies)} proxies from {proxy_file}")
            return

        logger.info("No proxy pool configured (set PROXY_LIST or PROXY_LIST_FILE)")

    @property
    def is_configured(self) -> bool:
        """是否配置了代理池"""
        return len(self._proxies) > 0

    def get_proxy(self) -> Optional[str]:
        """获取下一个健康代理（轮询）"""
        if not self._proxies:
            return None

        now = time.time()
        # 尝试找到一个健康的代理
        for _ in range(len(self._proxies)):
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1

            # 检查是否在 cooldown 中
            fail_time = self._failed.get(proxy)
            if fail_time and now - fail_time < FAILURE_COOLDOWN:
                continue  # 跳过仍在 cooldown 的代理

            # cooldown 过期，移除失败标记
            if fail_time:
                del self._failed[proxy]

            return proxy

        # 所有代理都在 cooldown 中，返回最早失败的
        logger.warning("All proxies in cooldown, returning oldest failed proxy")
        oldest = min(self._failed, key=self._failed.get)
        del self._failed[oldest]
        return oldest

    def mark_failed(self, proxy: str) -> None:
        """标记代理为失败"""
        self._failed[proxy] = time.time()
        logger.warning(f"Proxy marked as failed: {proxy} (cooldown {FAILURE_COOLDOWN}s)")

    def start_health_check(self) -> None:
        """启动后台健康检查任务"""
        if self._proxies and not self._health_task:
            self._health_task = asyncio.create_task(self._health_check_loop())
            logger.info("Proxy health check loop started")

    async def stop(self) -> None:
        """停止健康检查"""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

    async def _health_check_loop(self) -> None:
        """后台健康检查：每 N 秒 ping 所有代理"""
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            for proxy in self._proxies:
                try:
                    healthy = await self._check_proxy(proxy)
                    if not healthy:
                        self.mark_failed(proxy)
                    elif proxy in self._failed:
                        del self._failed[proxy]
                        logger.info(f"Proxy recovered: {proxy}")
                except Exception as e:
                    logger.debug(f"Health check error for {proxy}: {e}")

    @staticmethod
    async def _check_proxy(proxy: str) -> bool:
        """检查代理是否可达"""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://httpbin.org/ip",
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    def stats(self) -> dict:
        """返回代理池状态"""
        return {
            "total": len(self._proxies),
            "healthy": len(self._proxies) - len(self._failed),
            "failed": len(self._failed),
            "failed_proxies": list(self._failed.keys()),
        }
