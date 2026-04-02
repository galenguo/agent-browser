#!/bin/bash

# Agent Browser 场景 1 完整测试脚本
# 测试：CLI + 本地浏览器 + 基本操作

set -e

cd "/Users/galen/Library/Mobile Documents/com~apple~CloudDocs/skills/agent-browser"
export PYTHONPATH="/Users/galen/Library/Mobile Documents/com~apple~CloudDocs/skills/agent-browser/src"

SESSION_NAME="test-scenario1-full"

echo "========================================="
echo "场景 1：CLI + 本地浏览器 + 基本操作"
echo "========================================="
echo ""

# 步骤 1: 创建会话
echo "步骤 1: 创建会话..."
python -m src.cli.commands session create --name "$SESSION_NAME" --browser local
echo ""

# 步骤 2: 导航到百度
echo "步骤 2: 导航到百度..."
python -m src.cli.commands navigate goto --session "$SESSION_NAME" --url https://www.baidu.com
echo ""

# 步骤 3: 提取页面标题
echo "步骤 3: 提取页面标题..."
python -m src.cli.commands extract text --session "$SESSION_NAME" --selector "title"
echo ""

# 步骤 4: 销毁会话
echo "步骤 4: 销毁会话..."
python -m src.cli.commands session destroy --session "$SESSION_NAME"
echo ""

echo "========================================="
echo "场景 1 测试完成！"
echo "========================================="
