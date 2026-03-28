"""
数据模型定义

包含：
- BrowserType（浏览器类型枚举）
- BrowserInstance（浏览器实例基类）
- LocalBrowserInstance（本地 Chromium 浏览器实例）
- DockerBrowserInstance（Docker 浏览器实例）
- UserSession（用户会话）
- 异常类
"""

import time
import asyncio
from enum import Enum
from typing import Optional, Any, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from playwright.async_api import Playwright, Browser


# ============ 枚举 ============

class BrowserType(str, Enum):
    """浏览器引擎类型"""
    CHROMIUM = "chromium"   # CloakBrowser + patchright（默认）


# ============ 异常类 ============

class ResourceExhaustedError(Exception):
    """资源耗尽异常（达到最大并发数）"""
    pass


class SessionNotFoundError(Exception):
    """会话不存在异常"""
    pass


# ============ 浏览器实例 ============

@dataclass
class BrowserInstance:
    """浏览器实例基类"""
    instance_id: str
    cdp_url: str
    cdp_port: int
    session_id: str
    created_at: float = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()


@dataclass
class LocalBrowserInstance(BrowserInstance):
    """本地浏览器实例（进程）"""
    playwright: Any = None  # playwright.async_api.Playwright
    browser: Any = None     # playwright.async_api.Browser


@dataclass
class DockerBrowserInstance(BrowserInstance):
    """Docker 浏览器实例（容器）"""
    container: Any = None  # docker.models.containers.Container
    container_name: str = None
    novnc_host_port: Optional[int] = None   # 已分配的宿主机 noVNC 端口（Mode B）
    # 对外暴露的公网访问信息（需配置 BROWSER_PUBLIC_HOST 环境变量）
    public_host: Optional[str] = None       # 公网 IP 或域名
    public_cdp_port: Optional[int] = None   # 公网 CDP 端口（Mode B 有，Mode D 无）
    public_novnc_port: Optional[int] = None # 公网 noVNC 端口
    novnc_url: Optional[str] = None         # 完整 noVNC 监控地址

    def __post_init__(self):
        super().__post_init__()
        if self.container_name is None:
            self.container_name = f"browser_{self.session_id}"


# ============ 用户会话 ============

@dataclass
class UserSession:
    """用户会话"""
    session_id: str
    user_id: str
    browser_instance: BrowserInstance
    profile_dir: str
    created_at: float
    last_activity: float
    tasks: dict = None  # task_id -> task_info
    task_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        if self.tasks is None:
            self.tasks = {}

    def is_idle(self, timeout: int) -> bool:
        """检查是否空闲超时"""
        return time.time() - self.last_activity > timeout

    def mark_activity(self):
        """标记活动"""
        self.last_activity = time.time()
