#!/bin/bash
# 启动多用户 API V2（支持持久化 Profile）

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}启动多用户 API V2（持久化 Profile）${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查环境变量
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}错误: OPENAI_API_KEY 未设置${NC}"
    echo "请设置环境变量: export OPENAI_API_KEY=your_key"
    exit 1
fi

# 设置默认环境变量
export MAX_CONCURRENT_SESSIONS=${MAX_CONCURRENT_SESSIONS:-10}
export SESSION_IDLE_TIMEOUT=${SESSION_IDLE_TIMEOUT:-1800}  # 30分钟
export PROFILE_STORAGE=${PROFILE_STORAGE:-/data/profiles}
export PROFILE_TTL=${PROFILE_TTL:-2592000}  # 30天
export LLM_MODEL_NAME=${LLM_MODEL_NAME:-glm-4-flash}
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://open.bigmodel.cn/api/coding/paas/v4}

echo -e "${YELLOW}配置信息:${NC}"
echo "  - 最大并发 Session: $MAX_CONCURRENT_SESSIONS"
echo "  - Session 超时: $SESSION_IDLE_TIMEOUT 秒"
echo "  - Profile 存储: $PROFILE_STORAGE"
echo "  - Profile TTL: $PROFILE_TTL 秒 ($(($PROFILE_TTL / 86400)) 天)"
echo "  - LLM 模型: $LLM_MODEL_NAME"
echo "  - LLM Base URL: $OPENAI_BASE_URL"
echo ""

# 创建必要的目录
echo -e "${YELLOW}创建必要的目录...${NC}"
mkdir -p /data/profiles
mkdir -p /data/logs
echo -e "${GREEN}✓ 目录创建完成${NC}"
echo ""

# 启动 API
echo -e "${YELLOW}启动 API 服务器（端口 8001）...${NC}"
cd "$(dirname "$0")/.."
python -m uvicorn src.api_multiuser_v2:app \
    --host 0.0.0.0 \
    --port 8001 \
    --log-level info \
    --reload
