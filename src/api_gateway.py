"""API 网关 WebSocket 端点"""
from fastapi import FastAPI, WebSocket
from src.events import EventBus
from src.cli_handler import CLIHandler
from src.session.pool_manager import SessionPoolManager

app = FastAPI()
event_bus = EventBus()
pool_manager = SessionPoolManager()
cli_handler = CLIHandler(pool_manager)


@app.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 端点"""
    await websocket.accept()
    queue = await event_bus.subscribe(session_id)

    try:
        while True:
            event = await queue.get()
            await websocket.send_json({
                "type": event.type,
                "data": event.data
            })
    except Exception:
        pass


@app.post("/cli/execute")
async def execute_cli(command: str, session_id: str, args: dict):
    """执行 CLI 命令"""
    result = await cli_handler.execute(command, session_id, args)
    return result
