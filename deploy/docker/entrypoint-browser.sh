#!/bin/bash
set -e

echo "[browser-node] Starting Agent Browser - Browser Node"
echo "[browser-node] Pod: ${POD_NAME:-unknown}"

mkdir -p /data/logs /data/profiles

# ── 1. Xvfb ──────────────────────────────────────────────────
echo "[browser-node] Starting Xvfb on :99 (1920x1080x24)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -ac &
XVFB_PID=$!
sleep 1

if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[browser-node] ERROR: Xvfb failed to start"
    exit 1
fi
echo "[browser-node] Xvfb started (pid=$XVFB_PID)"

# ── 2. x11vnc ─────────────────────────────────────────────────
echo "[browser-node] Starting x11vnc on :5900..."
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
echo "[browser-node] x11vnc started"

# ── 3. noVNC websockify ───────────────────────────────────────
echo "[browser-node] Starting noVNC on :6080..."
websockify \
    --web /usr/share/novnc \
    --heartbeat 30 \
    6080 \
    localhost:5900 \
    2>/data/logs/novnc.log &
sleep 1
echo "[browser-node] noVNC started"

# ── 4. Browser Node API ───────────────────────────────────────
echo "[browser-node] Starting Browser Node API on :8080..."
cd /app
exec python -m uvicorn agent_browser.browser.node_api:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1 \
    --log-level info \
    --access-log
