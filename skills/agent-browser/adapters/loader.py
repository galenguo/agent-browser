"""适配器加载器 — 扫描 adapters/ 目录，解析 YAML，注册到内存"""
import os
import logging
from typing import Dict, List, Optional
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 内存注册表: {(site, name): adapter_dict}
_registry: Dict[tuple, dict] = {}

# 是否已加载
_loaded = False

# 默认适配器目录（相对于项目根目录）
_DEFAULT_ADAPTER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "adapters",
)


def load_adapters(adapter_dir: Optional[str] = None) -> int:
    """
    扫描适配器目录，加载所有 YAML 文件。

    Returns:
        加载的适配器数量
    """
    global _loaded, _registry

    if _loaded:
        return len(_registry)

    adapter_dir = adapter_dir or _DEFAULT_ADAPTER_DIR
    if not os.path.isdir(adapter_dir):
        logger.warning(f"Adapter directory not found: {adapter_dir}")
        return 0

    count = 0
    for root, dirs, files in os.walk(adapter_dir):
        # 跳过 _shared 目录
        if "_shared" in root:
            continue
        for fname in files:
            if not fname.endswith((".yaml", ".yml")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    adapter = yaml.safe_load(f)
                if not adapter or "site" not in adapter or "name" not in adapter:
                    logger.debug(f"Skipping invalid adapter: {fpath}")
                    continue
                key = (adapter["site"], adapter["name"])
                adapter["_file"] = fpath
                _registry[key] = adapter
                count += 1
                logger.debug(f"Loaded adapter: {key}")
            except Exception as e:
                logger.warning(f"Failed to load adapter {fpath}: {e}")

    _loaded = True
    logger.info(f"Loaded {count} adapters from {adapter_dir}")
    return count


def list_adapters() -> List[dict]:
    """列出所有已注册的适配器"""
    if not _loaded:
        load_adapters()
    return [
        {
            "site": key[0],
            "name": key[1],
            "description": adapter.get("description", ""),
            "strategy": adapter.get("strategy", "public"),
            "columns": adapter.get("columns", []),
            "args": list(adapter.get("args", {}).keys()),
        }
        for key, adapter in _registry.items()
    ]


def get_adapter(site: str, name: str) -> Optional[dict]:
    """获取指定适配器"""
    if not _loaded:
        load_adapters()
    return _registry.get((site, name))
