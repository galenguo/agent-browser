"""Browser Node API — lightweight FastAPI for browser pod management.

Runs inside browser pods (stealth-browser-br-{N}) in distributed mode.
Exposes minimal endpoints for control plane to manage the browser lifecycle.

Endpoints:
    GET  /health          — health check + busy state
    GET  /browser/status  — current browser state
    POST /browser/start   — launch CloakBrowser, return cdp_url
    POST /browser/stop    — stop CloakBrowser, mark pod as idle
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Browser Node API", version="0.1.0")

# Module-level browser state (one browser per pod)
_playwright = None
_browser = None
_cdp_url: str | None = None
_session_id: str | None = None


# ── Request models ────────────────────────────────────────────


class StartRequest(BaseModel):
    session_id: str
    profile_dir: str = "/data/profiles"


# ── Endpoints ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pod_name": os.environ.get("POD_NAME", ""),
        "busy": _session_id is not None,
        "session_id": _session_id,
        "cdp_url": _cdp_url,
    }


@app.get("/browser/status")
async def browser_status():
    return {
        "busy": _session_id is not None,
        "session_id": _session_id,
        "cdp_url": _cdp_url,
    }


@app.post("/browser/start")
async def start_browser(req: StartRequest):
    global _playwright, _browser, _cdp_url, _session_id

    if _session_id is not None:
        raise HTTPException(status_code=409, detail=f"Pod already busy with session {_session_id}")

    from stealth_browser.browser.stealth_launcher import launch_stealth_browser

    logger.info(f"Starting browser for session {req.session_id}, profile={req.profile_dir}")
    try:
        pw, browser, cdp_url = await launch_stealth_browser(
            headless=False,
            proxy=None,
            user_data_dir=req.profile_dir,
            cdp_port=19222,
        )
    except Exception as e:
        logger.exception("Failed to launch browser")
        raise HTTPException(status_code=500, detail=str(e))

    _playwright = pw
    _browser = browser
    _cdp_url = cdp_url
    _session_id = req.session_id

    logger.info(f"Browser started: cdp_url={cdp_url}, session={req.session_id}")
    return {"cdp_url": cdp_url, "session_id": req.session_id}


@app.post("/browser/stop")
async def stop_browser():
    global _playwright, _browser, _cdp_url, _session_id

    if _session_id is None:
        return {"status": "idle"}

    logger.info(f"Stopping browser for session {_session_id}")
    try:
        if _browser:
            await _browser.close()
        if _playwright:
            await _playwright.stop()
    except Exception as e:
        logger.warning(f"Error stopping browser: {e}")
    finally:
        _playwright = None
        _browser = None
        _cdp_url = None
        _session_id = None

    return {"status": "stopped"}
