#!/bin/bash
# 启动 Agent Browser Skill

echo "Starting Agent Browser..."

# 启动本地 CloakBrowser（如果需要）
if [ "$BROWSER_MODE" = "local" ]; then
    echo "Starting local CloakBrowser on port 19222..."
    # /opt/cloakbrowser/chrome --remote-debugging-port=19222 &
fi

# 启动 API Gateway（模式3）
if [ "$DEPLOYMENT_MODE" = "api_gateway" ]; then
    echo "Starting API Gateway..."
    uvicorn src.api_gateway:app --host 0.0.0.0 --port 8000
fi

echo "Agent Browser ready"
