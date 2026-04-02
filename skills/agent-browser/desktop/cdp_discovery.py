"""CDP 自动发现 — 扫描本地端口寻找 Electron 调试端点"""
import asyncio
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# 缓存: app_name → CDP URL
_cache: Dict[str, str] = {}

# 默认扫描端口范围
DEFAULT_PORT_RANGE = range(9222, 9231)


@dataclass
class CDPInfo:
    """CDP 端点信息"""
    url: str
    app_name: str
    version: str
    web_socket_url: str


async def discover_cdp(
    port_range: Optional[range] = None,
    app_filter: Optional[str] = None,
) -> List[CDPInfo]:
    """
    扫描本地端口寻找 Electron CDP 端点。

    隐匿性:
      - 使用 HTTP /json/version 接口（标准 Chrome DevTools 协议）
      - 不注入任何代码到目标应用
      - 扫描使用串行请求 + 小延迟，避免触发安全告警
    """
    ports = port_range or DEFAULT_PORT_RANGE
    results = []

    for port in ports:
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info = _parse_version(data, port)
                        if info:
                            if app_filter and app_filter.lower() not in info.app_name.lower():
                                continue
                            results.append(info)
                            _cache[info.app_name.lower()] = info.url
                            logger.info(f"Found CDP: {info.app_name} at port {port}")
        except Exception:
            pass

        # 串行扫描间小延迟
        await asyncio.sleep(0.05)

    return results


async def get_cached_cdp(app_name: str) -> Optional[str]:
    """获取缓存的 CDP URL"""
    key = app_name.lower()
    if key in _cache:
        # 验证缓存仍然有效
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    f"{_cache[key]}/json/version",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        return _cache[key]
        except Exception:
            del _cache[key]

    # 重新发现
    results = await discover_cdp(app_filter=app_name)
    if results:
        return results[0].url
    return None


def _parse_version(data: dict, port: int) -> Optional[CDPInfo]:
    """解析 /json/version 响应"""
    browser = data.get("Browser", "")
    ws_url = data.get("webSocketDebuggerUrl", "")

    if not browser:
        return None

    # 从 Browser 字段提取应用名
    # 例: "HeadlessChrome/120.0" → Chrome
    # 例: "Chrome/120.0" → Chrome
    # 例: "Mozilla/5.0 (Macintosh; ... ) Chrome/120.0 Safari/537.36" → Chrome
    app_name = "Unknown"
    if "cursor" in browser.lower():
        app_name = "Cursor"
    elif "chrome" in browser.lower():
        app_name = "Chrome"
    elif "electron" in browser.lower():
        app_name = "Electron"
    else:
        app_name = browser.split("/")[0] if "/" in browser else browser

    return CDPInfo(
        url=f"http://127.0.0.1:{port}",
        app_name=app_name,
        version=data.get("Browser", ""),
        web_socket_url=ws_url,
    )
