"""BrowserController — 包装 BrowserSession 提供统一操作接口

桥接 browser-use 的 BrowserSession 和 CLI/API 的原子操作。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ActionResult:
    """原子操作结果"""
    status: str = "ok"
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"status": self.status}
        if self.error:
            d["error"] = self.error
        if self.data:
            d["data"] = self.data
        return d


class BrowserController:
    """浏览器操作控制器

    包装 browser-use BrowserSession，提供类型化的操作接口。
    用于 CLI 命令和 SessionManager 的会话上下文。
    """

    def __init__(self, browser_session, session_id: str):
        self._session = browser_session
        self.session_id = session_id

    @property
    def session(self):
        return self._session
