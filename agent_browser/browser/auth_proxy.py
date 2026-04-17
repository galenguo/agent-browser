"""Lightweight reverse proxy for browser pods.

Runs inside each browser pod on port 80, proxying to local services:

Routes:
    /health        — health check
    /cdp/{path}    — reverse proxy to Chrome CDP (127.0.0.1:{CDP_PORT})
                     Includes WebSocket upgrade support and URL rewriting
    /{path:any}    — reverse proxy to noVNC (:6080)

No API key validation — authentication is handled at the API pod layer.
Pod name randomness provides additional URL obscurity.

Usage (started by entrypoint-browser.sh):
    python -m agent_browser.browser.auth_proxy
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import time

from aiohttp import web

logger = logging.getLogger(__name__)

UPSTREAM_NOVNC = os.getenv("AUTH_PROXY_UPSTREAM", "http://127.0.0.1:6080")
CDP_PORT = os.getenv("CDP_PORT", "19222")
UPSTREAM_CDP = f"http://127.0.0.1:{CDP_PORT}"

# Track startup time for health reporting
_START_TIME = time.time()

# App-level shared HTTP session (connection pooling)
_http_session: "aiohttp.ClientSession | None" = None


async def _get_session() -> "aiohttp.ClientSession":
    """Lazy-initialised shared aiohttp session (reused across all requests)."""
    global _http_session
    import aiohttp

    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


async def _proxy(request: web.Request, upstream: str) -> web.Response:
    """Forward request to an upstream server using streaming."""
    session = await _get_session()

    url = f"{upstream}{request.path}"
    if request.query_string:
        url += f"?{request.query_string}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    body = await request.read()

    async with session.request(
        method=request.method,
        url=url,
        headers=headers,
        data=body,
    ) as resp:
        # Stream response body back to client
        stream = web.StreamResponse(
            status=resp.status,
            headers={
                k: v for k, v in resp.headers.items()
                if k.lower() == "content-type"
            },
        )
        await stream.prepare(request)
        async for chunk in resp.content.iter_any():
            await stream.write(chunk)
        await stream.write_eof()
        return stream


async def handle_cdp(request: web.Request) -> web.Response | web.WebSocketResponse:
    """Proxy CDP requests (HTTP + WebSocket) to local Chrome.

    For HTTP requests: rewrites webSocketDebuggerUrl in /json/version responses
    to point back through this proxy.

    For WebSocket upgrades: relays frames between client and Chrome.
    """
    # Detect WebSocket upgrade
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _proxy_cdp_websocket(request)

    # --- Regular HTTP request ---
    path = request.path
    if path.startswith("/cdp"):
        path = path[4:] or "/"

    upstream_url = f"{UPSTREAM_CDP}{path}"
    if request.query_string:
        upstream_url += f"?{request.query_string}"

    session = await _get_session()

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    body = await request.read()

    async with session.request(
        method=request.method,
        url=upstream_url,
        headers=headers,
        data=body,
    ) as resp:
        resp_body = await resp.read()

        # Rewrite webSocketDebuggerUrl so Playwright reconnects
        # through the proxy instead of trying 127.0.0.1 directly.
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" in content_type and "/json/version" in path:
            try:
                data = json.loads(resp_body)
                ws_url = data.get("webSocketDebuggerUrl", "")
                if ws_url:
                    ws_path = re.sub(r"^ws://[^/]+", "", ws_url)
                    data["webSocketDebuggerUrl"] = (
                        f"ws://{request.host}/cdp{ws_path}"
                    )
                    resp_body = json.dumps(data).encode()
            except Exception:
                pass  # Rewrite failed — pass through original

        return web.Response(
            status=resp.status,
            body=resp_body,
            headers={
                k: v for k, v in resp.headers.items()
                if k.lower() == "content-type"
            },
        )


async def _proxy_cdp_websocket(request: web.Request) -> web.WebSocketResponse:
    """Relay WebSocket frames between client and Chrome CDP."""
    import aiohttp

    path = request.path
    if path.startswith("/cdp"):
        path = path[4:] or "/"

    ws_upstream = f"ws://127.0.0.1:{CDP_PORT}{path}"

    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)
    logger.info("CDP WebSocket proxy established: %s", path)

    try:
        session = await _get_session()
        async with session.ws_connect(ws_upstream) as ws_server:

            async def relay_client_to_server():
                try:
                    async for msg in ws_client:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await ws_server.send_str(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await ws_server.send_bytes(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSE,
                        ):
                            break
                except Exception:
                    pass
                finally:
                    with contextlib.suppress(Exception):
                        await ws_server.close()

            async def relay_server_to_client():
                try:
                    async for msg in ws_server:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await ws_client.send_str(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await ws_client.send_bytes(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSE,
                        ):
                            break
                except Exception:
                    pass
                finally:
                    with contextlib.suppress(Exception):
                        await ws_client.close()

            await asyncio.gather(
                relay_client_to_server(),
                relay_server_to_client(),
            )
    except Exception as e:
        logger.warning("CDP WebSocket proxy error: %s", e)

    return ws_client


async def handle_novnc(request: web.Request) -> web.Response:
    """Proxy to upstream noVNC."""
    return await _proxy(request, UPSTREAM_NOVNC)


async def health_check(request: web.Request) -> web.Response:
    """Health endpoint."""
    uptime = time.time() - _START_TIME
    return web.json_response({
        "status": "ok",
        "upstream_novnc": UPSTREAM_NOVNC,
        "upstream_cdp": UPSTREAM_CDP,
        "uptime_seconds": round(uptime, 1),
    })


async def _on_startup(app: web.Application) -> None:
    """Initialize shared HTTP session on app startup."""
    await _get_session()
    logger.info("Shared HTTP session initialized")


async def _on_cleanup(app: web.Application) -> None:
    """Close shared HTTP session on app shutdown."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None
        logger.info("Shared HTTP session closed")


def create_app() -> web.Application:
    """Create and configure the reverse proxy application."""
    app = web.Application()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/health", health_check)
    app.router.add_route("*", "/cdp/{path:.*}", handle_cdp)
    app.router.add_route("*", "/cdp", handle_cdp)
    app.router.add_route("*", "/{path:.*}", handle_novnc)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = create_app()
    logger.info("Starting reverse proxy on :80 (novnc=%s, cdp=%s)",
                UPSTREAM_NOVNC, UPSTREAM_CDP)
    web.run_app(app, host="0.0.0.0", port=80, print=None)
