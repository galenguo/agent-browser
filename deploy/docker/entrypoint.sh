#!/bin/bash
set -e

echo "[entrypoint-v2] Starting Agent Browser - Multi-User Sessions (v2)"

# ── 1. 启动 Xvfb 虚拟显示 ──────────────────────────────────────
echo "[entrypoint-v2] Starting Xvfb on :99 (1920x1080x24)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -ac &
XVFB_PID=$!
sleep 1

# 验证 Xvfb 启动成功
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[entrypoint-v2] ERROR: Xvfb failed to start"
    exit 1
fi
echo "[entrypoint-v2] Xvfb started (pid=$XVFB_PID)"

# ── 2. 启动 x11vnc VNC 服务 ────────────────────────────────────
echo "[entrypoint-v2] Starting x11vnc on :5900..."
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
    2>/data/logs/x11vnc.log &
sleep 1
echo "[entrypoint-v2] x11vnc started"

# ── 3. 启动 noVNC Web 查看器 ───────────────────────────────────
echo "[entrypoint-v2] Starting noVNC on :6080..."
websockify \
    --web /usr/share/novnc \
    --heartbeat 30 \
    6080 \
    localhost:5900 \
    2>/data/logs/novnc.log &
sleep 1
echo "[entrypoint-v2] noVNC started → http://<host>:6080/vnc.html"

# ── 4. 启动 FastAPI v2 API 服务 ───────────────────────────────
echo "[entrypoint-v2] Starting FastAPI v2 API server on :8000..."
echo "[entrypoint-v2] Deployment mode: ${DEPLOYMENT_MODE:-all-in-one}"
echo "[entrypoint-v2] Browser mode: ${BROWSER_MODE:-local}"
echo "[entrypoint-v2] Max sessions: ${MAX_SESSIONS:-10}"
echo "[entrypoint-v2] Remote access:"
echo "  noVNC:       http://<host>:6080/vnc.html"
echo "  API v2:      http://<host>:8000/sessions/create"
echo "  Health:      http://<host>:8000/health"
echo "  Legacy API:  http://<host>:8000/tasks (backward compatible)"

cd /app
exec python -m uvicorn agent_browser.api.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    --access-log
