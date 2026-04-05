"""CDP 自动发现 — 扫描本地端口寻找 Electron 调试端点"""
import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_PORT_RANGE = range(9222, 9231)

# 已知应用识别规则（按优先级匹配）
_APP_RULES: Dict[str, str] = {
    "cursor": "Cursor",
    "chrome": "Chrome",
    "electron": "Electron",
}


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
    results = []
    for port in (port_range or DEFAULT_PORT_RANGE):
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    f"http://127.0.0.1:{port}/json/version",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info = _parse_version(data, port)
                        if info and (not app_filter or app_filter.lower() in info.app_name.lower()):
                            results.append(info)
                            logger.info(f"Found CDP: {info.app_name} at port {port}")
        except Exception:
            pass
        await asyncio.sleep(0.05)
    return results


async def get_cdp(app_name: str) -> Optional[str]:
    """发现并返回指定应用的 CDP URL"""
    results = await discover_cdp(app_filter=app_name)
    return results[0].url if results else None


def _parse_version(data: dict, port: int) -> Optional[CDPInfo]:
    """解析 /json/version 响应"""
    browser = data.get("Browser", "")
    if not browser:
        return None
    lower = browser.lower()
    app_name = next((v for k, v in _APP_RULES.items() if k in lower), None)
    if not app_name:
        app_name = browser.split("/")[0] if "/" in browser else browser
    return CDPInfo(
        url=f"http://127.0.0.1:{port}",
        app_name=app_name,
        version=browser,
        web_socket_url=data.get("webSocketDebuggerUrl", ""),
    )
