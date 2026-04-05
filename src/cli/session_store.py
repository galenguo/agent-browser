"""
CLI 本地会话存储

持久化 CLI 模式下的会话信息到本地 JSON 文件，
支持跨命令复用。

实际实现复用 session_manager.CLISessionManager。
"""
from src.cli.session_manager import CLISessionManager, CLISession

__all__ = ['CLISessionManager', 'CLISession']
