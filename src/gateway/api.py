"""
Gateway API 服务

职责：
- API Key 认证
- 远程浏览器资源分配/释放
- CDP WebSocket 代理（透传 + 认证）

端口：8001（独立于主 API Server 8000）

CDP URL 格式：ws://gateway:8001/cdp?apikey=xxx&instance=yyy
"""
import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import websockets
from fastapi import FastAPI, Header, HTTPException, Query, WebSocket
from pydantic import BaseModel

from .key_store import KeyStore, create_default_keys_yaml
from .state import GatewayState, InstanceRecord

logger = logging.getLogger(__name__)

# 复用 HTTP 客户端（高性能优化）
_http_client: Optional[httpx.AsyncClient] = None

# ──────────────────────────────────────────
# 初始化
# ──────────────────────────────────────────

keys_path = Path(os.environ.get("GATEWAY_KEYS_PATH", "config/keys.yaml"))
state_path = Path(os.environ.get("GATEWAY_STATE_PATH", "data/gateway_state.json"))

key_store = KeyStore(path=keys_path)
gateway_state = GatewayState(path=state_path)

GATEWAY_PUBLIC_HOST = os.environ.get("GATEWAY_PUBLIC_HOST", "localhost:8001")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    # 启动时恢复状态
    await gateway_state.start()
    # 初始化 keys.yaml（如果不存在）
    if not keys_path.exists():
        create_default_keys_yaml(keys_path)
    # 初始化复用的 HTTP 客户端
    _http_client = httpx.AsyncClient(timeout=10.0)
    yield
    # 关闭时清理
    if _http_client:
        await _http_client.aclose()
    await gateway_state.stop()


app = FastAPI(title="Agent-Browser Gateway", version="1.0.0", lifespan=lifespan)


# ──────────────────────────────────────────
# 依赖：API Key 验证
# ──────────────────────────────────────────

def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    info = key_store.get(x_api_key)
    if not info:
        # 错误消息不泄露 key 是否存在
        raise HTTPException(status_code=401, detail="Authentication failed")
    return info


# ──────────────────────────────────────────
# 浏览器启动（Docker）
# ──────────────────────────────────────────

async def _launch_docker_browser(instance_id: str) -> str:
    """
    启动 Docker 容器中的 CloakBrowser。
    返回 WebSocket URL（带 /devtools/browser/xxx）。

    性能优化：
    - 复用全局 HTTP 客户端
    - 指数退避探活（减少无效请求）
    """
    import docker
    import random

    client = docker.from_env()
    host_port = random.randint(19000, 19199)

    container = client.containers.run(
        image=os.environ.get("BROWSER_IMAGE", "agent-browser-browser:latest"),
        name=f"browser-{instance_id}",
        detach=True,
        remove=True,
        ports={"19222/tcp": host_port},
        environment={
            "CDP_PORT": "19222",
            "CDP_BIND_ADDRESS": "0.0.0.0",
        },
        labels={"agent-browser": "true", "instance-id": instance_id},
    )

    # 更激进的探活策略（总超时 ~15s）
    # 优化：快速初始探活，避免不必要的等待
    delays = [0.2, 0.3, 0.5, 0.5, 1, 1, 2, 2, 3, 4]
    for delay in delays:
        await asyncio.sleep(delay)
        container.reload()
        if container.status != "running":
            continue

        try:
            # 复用全局 HTTP 客户端，更短超时
            resp = await _http_client.get(
                f"http://localhost:{host_port}/json/version",
                timeout=1.0  # 缩短超时
            )
            if resp.status_code == 200:
                data = resp.json()
                ws_url = data.get("webSocketDebuggerUrl", "")
                if ws_url:
                    ws_url = ws_url.replace("127.0.0.1", "localhost")
                    logger.info(f"✅ Browser {instance_id} ready on :{host_port}")
                    return ws_url
        except Exception:
            pass

    # 错误消息不泄露内部信息
    raise RuntimeError("Browser instance unavailable")


async def _stop_docker_browser(container_id: str):
    """停止 Docker 容器"""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_id)
        container.stop(timeout=5)
    except Exception as e:
        logger.warning(f"Failed to stop container {container_id}: {e}")


# ──────────────────────────────────────────
# REST 端点
# ──────────────────────────────────────────

class AllocateResponse(BaseModel):
    instance_id: str
    cdp_url: str  # ws://gateway:8001/cdp?apikey=xxx&instance=yyy


class ReleaseRequest(BaseModel):
    instance_id: str


@app.post("/allocate", response_model=AllocateResponse)
async def allocate_browser(x_api_key: str = Header(..., alias="X-API-Key")):
    """分配一个远程浏览器实例"""
    key_info = require_api_key(x_api_key)

    # 检查配额
    current = gateway_state.count_by_user(key_info.user)
    if current >= key_info.quota:
        raise HTTPException(
            status_code=429,
            detail=f"Quota exceeded: {current}/{key_info.quota} instances in use"
        )

    instance_id = str(uuid.uuid4())[:8]

    # 启动 Docker 浏览器
    real_cdp_url = await _launch_docker_browser(instance_id)

    record = InstanceRecord(
        instance_id=instance_id,
        user=key_info.user,
        cdp_url=real_cdp_url,
        container_id=f"browser-{instance_id}",
        allocated_at=time.time(),
    )
    gateway_state.add(record)

    # 返回指向 Gateway 代理的 cdp_url
    proxy_url = f"ws://{GATEWAY_PUBLIC_HOST}/cdp?apikey={x_api_key}&instance={instance_id}"

    logger.info(f"Allocated instance {instance_id} for user {key_info.user}")
    return AllocateResponse(instance_id=instance_id, cdp_url=proxy_url)


@app.post("/release")
async def release_browser(
    body: ReleaseRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """释放浏览器实例"""
    key_info = require_api_key(x_api_key)

    record = gateway_state.get(body.instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Instance not found")
    if record.user != key_info.user:
        raise HTTPException(status_code=403, detail="Not your instance")

    gateway_state.remove(body.instance_id)
    await _stop_docker_browser(record.container_id)

    logger.info(f"Released instance {body.instance_id} for user {key_info.user}")
    return {"status": "released", "instance_id": body.instance_id}


@app.get("/instances")
async def list_instances(x_api_key: str = Header(..., alias="X-API-Key")):
    """列出当前用户的实例"""
    key_info = require_api_key(x_api_key)
    instances = gateway_state.get_by_user(key_info.user)
    return {
        "user": key_info.user,
        "quota": key_info.quota,
        "instances": [
            {
                "instance_id": r.instance_id,
                "allocated_at": r.allocated_at,
            }
            for r in instances
        ]
    }


@app.get("/health")
async def health():
    return {"status": "ok", "instances": len(gateway_state.all_instances())}


# ──────────────────────────────────────────
# CDP HTTP 发现端点
# ──────────────────────────────────────────

@app.get("/json/version")
async def cdp_discovery(
    apikey: str = Query(...),
    instance: str = Query(...),
):
    """
    CDP HTTP 发现端点。
    Playwright connect_over_cdp 会先请求这个端点获取 webSocketDebuggerUrl。
    """
    # 验证 API Key
    if not key_store.is_valid(apikey):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 获取实例信息
    record = gateway_state.get(instance)
    if not record:
        raise HTTPException(status_code=404, detail="Instance not found")

    # 返回代理后的 WebSocket URL
    proxy_ws_url = f"ws://{GATEWAY_PUBLIC_HOST}/cdp?apikey={apikey}&instance={instance}"

    return {
        "Browser": "Chrome/145.0.7632.159",
        "Protocol-Version": "1.3",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "webSocketDebuggerUrl": proxy_ws_url,
    }


# ──────────────────────────────────────────
# CDP WebSocket 代理
# ──────────────────────────────────────────

@app.websocket("/cdp")
async def cdp_proxy(
    websocket: WebSocket,
    apikey: str = Query(...),
    instance: str = Query(...),
):
    """
    CDP WebSocket 代理。
    客户端连接到 ws://gateway:8001/cdp?apikey=xxx&instance=yyy
    Gateway 验证 apikey 后透传到真实浏览器的 CDP 端口。
    """
    # 验证 API Key
    if not key_store.is_valid(apikey):
        await websocket.close(code=1008, reason="Invalid API key")
        return

    # 获取真实 CDP URL
    record = gateway_state.get(instance)
    if not record:
        await websocket.close(code=1008, reason="Instance not found")
        return

    await websocket.accept()
    logger.debug(f"CDP proxy: {instance} → {record.cdp_url}")

    # 连接到真实浏览器并双向转发
    try:
        async with websockets.connect(record.cdp_url) as browser_ws:
            await asyncio.gather(
                _forward_client_to_browser(websocket, browser_ws),
                _forward_browser_to_client(browser_ws, websocket),
                return_exceptions=True,
            )
    except Exception as e:
        logger.debug(f"CDP proxy closed: {e}")


async def _forward_client_to_browser(client_ws: WebSocket, browser_ws):
    """客户端 → 浏览器"""
    try:
        while True:
            data = await client_ws.receive_text()
            await browser_ws.send(data)
    except Exception:
        pass


async def _forward_browser_to_client(browser_ws, client_ws: WebSocket):
    """浏览器 → 客户端"""
    try:
        async for message in browser_ws:
            await client_ws.send_text(message)
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
