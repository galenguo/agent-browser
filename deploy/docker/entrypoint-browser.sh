#!/bin/bash
set -e

echo "[browser-container] Starting standalone browser container"
echo "[browser-container] CDP_PORT=${CDP_PORT:-19222}"
echo "[browser-container] PROFILE_STORAGE=${PROFILE_STORAGE:-/data/profiles}"

# ── 1. 启动 Xvfb 虚拟显示 ──────────────────────────────────────
echo "[browser-container] Starting Xvfb on :99 (1920x1080x24)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -ac &
XVFB_PID=$!
sleep 1

if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[browser-container] ERROR: Xvfb failed to start"
    exit 1
fi
echo "[browser-container] Xvfb started (pid=$XVFB_PID)"

# ── 2. 启动 x11vnc VNC 服务（用于远程查看浏览器画面）────────────
echo "[browser-container] Starting x11vnc on :5900..."
x11vnc \
    -display :99 \
    -forever \
    -shared \
    -rfbport 5900 \
    -nopw \
    -xkb \
    -noxrecord \
    -noxfixes \
    -noxdamage \
    -wait 5 \
    -noncache \
    2>/tmp/x11vnc.log &
sleep 1
echo "[browser-container] x11vnc started"

# ── 3. 启动 noVNC Web 查看器 ─────────────────────────────────────
echo "[browser-container] Starting noVNC on :6080..."
websockify \
    --web /usr/share/novnc \
    --heartbeat 30 \
    6080 \
    localhost:5900 \
    2>/tmp/novnc.log &
sleep 1
echo "[browser-container] noVNC started → http://<host>:6080/vnc.html"

# ── 3.5 启动反向代理（CDP + noVNC）───────────────
echo "[browser-container] Starting reverse proxy on :80..."
python -m agent_browser.browser.auth_proxy \
    > /tmp/auth_proxy.log 2>&1 &
AUTH_PID=$!
sleep 1
if ! kill -0 $AUTH_PID 2>/dev/null; then
    echo "[browser-container] ERROR: Auth proxy failed to start"
    cat /tmp/auth_proxy.log
    exit 1
fi
echo "[browser-container] Auth proxy started (pid=$AUTH_PID) → http://<host>:80"

# ── 4. 启动 CloakBrowser ───────────────────────────────────────
echo "[browser-container] Starting CloakBrowser..."
echo "[browser-container] Profile directory: ${PROFILE_STORAGE}"

cat > /tmp/start_browser.py <<'PYTHON_SCRIPT'
import asyncio
import os
import sys
sys.path.insert(0, '/app/src')
from agent_browser.browser.stealth_launcher import launch_stealth_browser

async def main():
    profile_dir = os.getenv('PROFILE_STORAGE', '/data/profiles')
    cdp_port = int(os.getenv('CDP_PORT', '19222'))

    print(f"[browser-container] Launching browser with profile: {profile_dir}")
    print(f"[browser-container] CDP port: {cdp_port}")

    playwright, browser, cdp_url = await launch_stealth_browser(
        headless=False,
        user_data_dir=profile_dir,
        cdp_port=cdp_port,
    )

    print(f"[browser-container] ✅ Browser started: {cdp_url}")
    print(f"[browser-container] Keeping browser alive...")

    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        print("[browser-container] Shutting down...")
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())
PYTHON_SCRIPT

exec python /tmp/start_browser.py
