"""事件系统"""
import asyncio
from typing import Dict
from dataclasses import dataclass
from enum import Enum


class EventType(Enum):
    """事件类型"""
    COMMAND_STARTED = "command:started"
    COMMAND_COMPLETED = "command:completed"
    COMMAND_ERROR = "command:error"


@dataclass
class Event:
    """事件"""
    type: str
    data: Dict


class EventBus:
    """事件总线"""

    def __init__(self):
        self._subscribers: Dict[str, asyncio.Queue] = {}

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """订阅"""
        queue = asyncio.Queue()
        self._subscribers[session_id] = queue
        return queue

    async def emit(self, session_id: str, event: Event):
        """发送事件"""
        if session_id in self._subscribers:
            await self._subscribers[session_id].put(event)
