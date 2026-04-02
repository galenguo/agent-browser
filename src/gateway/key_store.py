"""
Gateway KeyStore - API Key 管理

使用 keys.yaml 文件存储，支持热重载。
无数据库依赖。
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class KeyInfo:
    key: str
    user: str
    quota: int  # 最大并发实例数
    enabled: bool = True


class KeyStore:
    """
    API Key 存储，从 keys.yaml 加载。
    支持热重载（调用 reload() 即可，或通过文件监听自动触发）。
    """

    DEFAULT_PATH = Path(os.environ.get("GATEWAY_KEYS_PATH", "config/keys.yaml"))

    def __init__(self, path: Optional[Path] = None):
        self.path = path or self.DEFAULT_PATH
        self._keys: Dict[str, KeyInfo] = {}
        self.reload()

    def reload(self):
        """从文件重新加载 keys"""
        if not self.path.exists():
            logger.warning(f"keys.yaml not found at {self.path}, no API keys loaded")
            self._keys = {}
            return

        with open(self.path) as f:
            data = yaml.safe_load(f) or {}

        keys = {}
        for entry in data.get("keys", []):
            k = KeyInfo(
                key=entry["key"],
                user=entry["user"],
                quota=entry.get("quota", 5),
                enabled=entry.get("enabled", True),
            )
            keys[k.key] = k

        self._keys = keys
        logger.info(f"KeyStore loaded {len(keys)} keys from {self.path}")

    def get(self, api_key: str) -> Optional[KeyInfo]:
        """获取 Key 信息（仅返回 enabled 的）"""
        info = self._keys.get(api_key)
        if info and info.enabled:
            return info
        return None

    def is_valid(self, api_key: str) -> bool:
        return self.get(api_key) is not None

    def all_keys(self) -> list[KeyInfo]:
        return [k for k in self._keys.values() if k.enabled]


def create_default_keys_yaml(path: Path):
    """生成示例 keys.yaml"""
    path.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "keys": [
            {"key": "sk_example_changeme", "user": "default", "quota": 5, "enabled": True},
        ]
    }
    with open(path, "w") as f:
        yaml.dump(example, f, default_flow_style=False, allow_unicode=True)
    logger.info(f"Created example keys.yaml at {path}")
