"""
数据模型定义

包含：
- BrowserType（浏览器类型枚举）
- BrowserInstance（浏览器实例基类）
- LocalBrowserInstance（本地 Chromium 浏览器实例）
- DockerBrowserInstance（Docker 浏览器实例）
- UserSession（用户会话）
- 原子操作请求模型
- 异常类
"""

import time
import asyncio
from enum import Enum
from typing import Optional, Any, List, Dict, TYPE_CHECKING
from dataclasses import dataclass, field
from pydantic import BaseModel

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


# ============ 原子操作请求模型 (Pydantic) ============

class NavigateRequest(BaseModel):
    """页面导航请求"""
    url: str
    wait_until: str = "domcontentloaded"  # load | domcontentloaded | networkidle
    timeout: int = 30000  # ms


class ClickRequest(BaseModel):
    """点击元素请求"""
    ref: str  # 元素引用，如 @e0, @e1
    button: str = "left"  # left | right | middle
    click_count: int = 1
    delay: Optional[int] = None  # 点击延迟 ms


class FillRequest(BaseModel):
    """填充输入框请求"""
    ref: str  # 元素引用
    text: str
    clear_first: bool = True  # 是否先清空
    human_like: bool = False  # 是否模拟人类输入


class EvaluateRequest(BaseModel):
    """执行 JavaScript 请求"""
    expression: str
    return_by_value: bool = True


class ScrollRequest(BaseModel):
    """滚动请求"""
    direction: str = "down"  # up | down
    amount: int = 300  # 像素
    smooth: bool = True


class WaitRequest(BaseModel):
    """等待请求"""
    selector: Optional[str] = None  # CSS 选择器
    timeout: int = 10000  # ms
    state: str = "visible"  # visible | hidden | attached | detached


# ============ 原子操作响应模型 ============

class ElementInfo(BaseModel):
    """元素信息"""
    ref: str  # @e0, @e1...
    tag: str
    text: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    placeholder: Optional[str] = None
    href: Optional[str] = None
    is_visible: bool = True
    is_enabled: bool = True
    bounding_box: Optional[Dict] = None


class SnapshotResponse(BaseModel):
    """快照响应"""
    url: str
    title: str
    elements: List[ElementInfo]
    raw_html_size: Optional[int] = None
    snapshot_size: Optional[int] = None
