"""Agent Browser Skill 主入口"""
import asyncio
from .session_manager import SessionManager

# 全局会话管理器
_manager = SessionManager()


async def create_session(cdp_url: str = "http://127.0.0.1:19222") -> str:
    """创建会话"""
    return await _manager.create_session(cdp_url)


async def delete_session(session_id: str):
    """删除会话"""
    await _manager.delete_session(session_id)


async def open_page(session_id: str, url: str):
    """打开页面"""
    await _manager.controller.open(session_id, url)


async def snapshot(session_id: str, interactive_only: bool = False):
    """获取快照"""
    return await _manager.controller.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    """点击元素"""
    await _manager.controller.click(session_id, ref)


async def fill(session_id: str, ref: str, text: str):
    """填充输入"""
    await _manager.controller.fill(session_id, ref, text)
