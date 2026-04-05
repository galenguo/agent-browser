"""
Gateway State - 运行时状态持久化

使用内存 + JSON 快照，无数据库依赖。
重启时从快照恢复，验证容器存活性。
"""
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class InstanceRecord:
    instance_id: str
    user: str
    cdp_url: str          # 内网真实 CDP URL (ws://10.x.x.x:19222)
    container_id: str     # Docker container ID
    allocated_at: float


class GatewayState:
    """
    Gateway 运行时状态管理。
    内存存储 + 定期快照到 state.json。
    重启时从快照恢复并验证存活性。
    """

    DEFAULT_PATH = Path("data/gateway_state.json")
    SNAPSHOT_INTERVAL = 10  # 秒

    def __init__(self, path: Optional[Path] = None):
        self.path = path or self.DEFAULT_PATH
        self._instances: Dict[str, InstanceRecord] = {}
        self._snapshot_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动：从快照恢复并开始定期快照"""
        await self._restore_from_snapshot()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    async def stop(self):
        """停止：最后一次快照"""
        if self._snapshot_task:
            self._snapshot_task.cancel()
        self._save_snapshot()

    # ──────────────────────────────────────────
    # 实例管理
    # ──────────────────────────────────────────

    def add(self, record: InstanceRecord):
        self._instances[record.instance_id] = record

    def remove(self, instance_id: str) -> Optional[InstanceRecord]:
        return self._instances.pop(instance_id, None)

    def get(self, instance_id: str) -> Optional[InstanceRecord]:
        return self._instances.get(instance_id)

    def get_by_user(self, user: str) -> list[InstanceRecord]:
        return [r for r in self._instances.values() if r.user == user]

    def count_by_user(self, user: str) -> int:
        return sum(1 for r in self._instances.values() if r.user == user)

    def all_instances(self) -> list[InstanceRecord]:
        return list(self._instances.values())

    # ──────────────────────────────────────────
    # 快照
    # ──────────────────────────────────────────

    def _save_snapshot(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: asdict(v) for k, v in self._instances.items()}
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            tmp.replace(self.path)  # 原子替换
        except Exception as e:
            logger.warning(f"Failed to save state snapshot: {e}")

    async def _snapshot_loop(self):
        while True:
            await asyncio.sleep(self.SNAPSHOT_INTERVAL)
            self._save_snapshot()

    async def _restore_from_snapshot(self):
        """从快照恢复，验证容器存活性"""
        if not self.path.exists():
            logger.info("No state snapshot found, starting fresh")
            return

        try:
            with open(self.path) as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state snapshot: {e}")
            return

        restored = 0
        for instance_id, record_data in data.items():
            record = InstanceRecord(**record_data)
            alive = await self._check_alive(record)
            if alive:
                self._instances[instance_id] = record
                restored += 1
            else:
                logger.info(f"Instance {instance_id} not alive, skipping")

        logger.info(f"Restored {restored}/{len(data)} instances from snapshot")

    async def _check_alive(self, record: InstanceRecord) -> bool:
        """检查实例是否存活（ping CDP 端口）"""
        try:
            import httpx
            # CDP 的 HTTP 端点 /json/version 可用于探活
            http_url = record.cdp_url.replace("ws://", "http://").replace("wss://", "https://")
            # 取 host:port 部分
            from urllib.parse import urlparse
            parsed = urlparse(http_url)
            probe_url = f"http://{parsed.hostname}:{parsed.port}/json/version"
            async with httpx.AsyncClient() as client:
                resp = await client.get(probe_url, timeout=3)
                return resp.status_code == 200
        except Exception:
            return False
