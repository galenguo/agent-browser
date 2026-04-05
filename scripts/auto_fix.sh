#!/bin/bash
# 自动化测试修复脚本
# 对应 §12.3 自动化修复流程
#
# 使用方式：
#   bash scripts/auto_fix.sh

set -e

echo "开始自动修复流程..."

# 1. 运行测试并捕获失败
echo "📋 运行测试..."
pytest tests/ -v --tb=short > test_results.txt 2>&1 || true

# 2. 分析失败原因
if grep -q "TimeoutError" test_results.txt; then
    echo "⚠️  检测到超时错误，建议增加超时时间"
fi

if grep -q "ConnectionError" test_results.txt; then
    echo "⚠️  检测到连接错误，检查服务状态"
fi

if grep -q "ImportError" test_results.txt; then
    echo "⚠️  检测到导入错误，检查依赖安装"
    echo "   尝试: pip install -r requirements.txt"
fi

# 3. 统计结果
TOTAL=$(grep -c "PASSED\|FAILED" test_results.txt || echo "0")
PASSED=$(grep -c "PASSED" test_results.txt || echo "0")
FAILED=$(grep -c "FAILED" test_results.txt || echo "0")

echo ""
echo "📊 测试结果: ${PASSED} passed, ${FAILED} failed, ${TOTAL} total"

if [ "$FAILED" -eq 0 ]; then
    echo "✅ 所有测试通过"
else
    echo "❌ ${FAILED} 个测试失败"
    echo ""
    echo "失败的测试："
    grep "FAILED" test_results.txt || true
    echo ""
    echo "重新运行失败的测试: pytest tests/ --lf -v"
fi

echo ""
echo "修复完成"
