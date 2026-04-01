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


# ── ReAct 辅助方法 ──

async def observe(session_id: str):
    """Observe: 获取页面状态 + 元素分析"""
    return await _manager.controller.observe(session_id)


async def reason_and_act(session_id: str, goal: str, observation: dict):
    """Reason & Act: 根据目标和观察执行操作"""
    return await _manager.controller.reason_and_act(session_id, goal, observation)


async def check_result(session_id: str, expected: str):
    """Check: 验证当前页面是否符合预期"""
    return await _manager.controller.check_result(session_id, expected)
