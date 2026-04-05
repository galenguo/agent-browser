"""
浏览器资源池管理

管理远程浏览器实例，支持分配/释放。
"""
import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BrowserInstance:
    """浏览器实例"""
    instance_id: str
    cdp_url: str
    host: str
    port: int
    status: str  # "idle", "busy", "offline"
    allocated_at: Optional[str] = None
    last_ping: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class BrowserPool:
    """浏览器资源池"""

    def __init__(self):
        self.instances: Dict[str, BrowserInstance] = {}
        self._lock = asyncio.Lock()

    async def register(self, instance_id: str, cdp_url: str, host: str, port: int):
        """注册浏览器实例"""
        async with self._lock:
            self.instances[instance_id] = BrowserInstance(
                instance_id=instance_id,
                cdp_url=cdp_url,
                host=host,
                port=port,
                status="idle",
                last_ping=datetime.now().isoformat()
            )
            logger.info(f"Registered instance: {instance_id}")

    async def allocate(self) -> Optional[BrowserInstance]:
        """分配一个空闲实例"""
        async with self._lock:
            for inst in self.instances.values():
                if inst.status == "idle":
                    inst.status = "busy"
                    inst.allocated_at = datetime.now().isoformat()
                    logger.info(f"Allocated instance: {inst.instance_id}")
                    return inst
            return None

    async def release(self, instance_id: str):
        """释放实例"""
        async with self._lock:
            if instance_id in self.instances:
                self.instances[instance_id].status = "idle"
                self.instances[instance_id].allocated_at = None
                logger.info(f"Released instance: {instance_id}")

    def get_instance(self, instance_id: str) -> Optional[BrowserInstance]:
        """获取实例"""
        return self.instances.get(instance_id)

    def get_all_instances(self) -> List[BrowserInstance]:
        """获取所有实例"""
        return list(self.instances.values())

    async def restore_from_state(self, instances: List[dict]):
        """从状态恢复实例"""
        for inst_data in instances:
            # Ping CDP 端口检查存活
            if await self._ping_cdp(inst_data["cdp_url"]):
                await self.register(
                    instance_id=inst_data["instance_id"],
                    cdp_url=inst_data["cdp_url"],
                    host=inst_data["host"],
                    port=inst_data["port"]
                )
            else:
                logger.warning(f"Instance {inst_data['instance_id']} is offline, skipping")

    async def _ping_cdp(self, cdp_url: str) -> bool:
        """Ping CDP 端口检查存活"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # CDP 通常有 /json/version 端点
                version_url = cdp_url.replace("ws://", "http://").replace("/devtools/browser", "/json/version")
                async with session.get(version_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug(f"Ping failed for {cdp_url}: {e}")
            return False
