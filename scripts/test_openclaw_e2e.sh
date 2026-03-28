#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# Agent Browser × OpenClaw E2E 测试脚本
#
# 通过 openclaw agent CLI 调用 agent-browser skill，
# 覆盖 4 个场景（5 个子测试），自动验证并输出报告。
#
# 用法：bash scripts/test_openclaw_e2e.sh
# 前提：FastAPI (localhost:8000) 和 OpenClaw Gateway 已运行
# ═══════════════════════════════════════════════════════════════
set -uo pipefail

# ─── 配置 ───
API_BASE="${API_BASE:-http://localhost:8000}"
OPENCLAW_TIMEOUT="${OPENCLAW_TIMEOUT:-180}"
OPENCLAW_TIMEOUT_LONG="${OPENCLAW_TIMEOUT_LONG:-240}"
# openclaw agent 需要 --to 参数来路由 session
OPENCLAW_TO="${OPENCLAW_TO:-+0000000001}"

# ─── 状态变量 ───
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
PASS=0
FAIL=0
TOTAL=0
declare -a REPORT_LINES=()

# ─── 颜色 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

# ─── 工具函数 ───

die() {
    echo -e "${RED}FATAL: $1${NC}" >&2
    exit 2
}

log() {
    echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $1"
}

# 从 openclaw agent 输出中提取回复文本
# JSON 可能在 stdout 或 stderr（gateway fallback 时在 stderr）
# payloads 是数组，合并所有 text 字段
extract_reply() {
    local stdout_file="$1"
    local stderr_file="$2"
    python3 -c "
import json, sys

def try_extract(content):
    start = content.find('{')
    if start == -1:
        return None
    try:
        d = json.loads(content[start:])
        # 顶层 payloads（embedded 模式）
        payloads = d.get('payloads', [])
        # 或 result.payloads（gateway 模式）
        if not payloads:
            payloads = d.get('result', {}).get('payloads', [])
        if payloads:
            texts = [p.get('text','') for p in payloads if p.get('text')]
            return ' '.join(texts)
        # fallback: result.reply 或 result.text
        r = d.get('result', {})
        if isinstance(r, dict):
            return r.get('reply', '') or r.get('text', '') or r.get('content', '')
        return json.dumps(d, ensure_ascii=False)
    except json.JSONDecodeError:
        return None

# 先尝试 stdout
with open('$stdout_file') as f:
    stdout = f.read().strip()
if stdout:
    result = try_extract(stdout)
    if result:
        print(result)
        sys.exit(0)

# 再尝试 stderr（过滤掉日志噪音）
with open('$stderr_file') as f:
    lines = f.readlines()
filtered = []
for line in lines:
    s = line.strip()
    if not s:
        continue
    # 跳过已知噪音行
    skip = False
    for noise in ['Config warn', '[plugins]', 'feishu', 'google-gemini', 'stale',
                   'Config was last', 'Gateway agent failed', 'Gateway target',
                   'Source:', 'Bind:', 'Config:']:
        if noise in s:
            skip = True
            break
    if not skip:
        filtered.append(line)
stderr_clean = ''.join(filtered).strip()
if stderr_clean:
    result = try_extract(stderr_clean)
    if result:
        print(result)
        sys.exit(0)

# 最后 fallback：拼接 stdout + stderr
print(stdout or stderr_clean or '(empty output)')
" 2>/dev/null
}

# ─── 前置检查 ───

preflight_check() {
    log "前置检查..."

    # 检查 openclaw CLI
    if ! command -v openclaw &>/dev/null; then
        die "openclaw 未安装或不在 PATH 中"
    fi
    log "  openclaw CLI: $(openclaw --version 2>/dev/null | head -1)"

    # 检查 FastAPI
    local health
    health=$(curl -sf "${API_BASE}/health" 2>/dev/null)
    if [ $? -ne 0 ]; then
        die "FastAPI 未响应 (${API_BASE}/health)。请先启动服务。"
    fi
    local api_status
    api_status=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
    if [ "$api_status" != "ok" ]; then
        die "FastAPI 状态异常: $health"
    fi
    local browser_mode
    browser_mode=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('browser_mode','unknown'))" 2>/dev/null)
    log "  FastAPI: ${GREEN}online${NC} (mode: ${browser_mode})"

    # 检查 Docker（可选，场景 1/3/4 需要）
    if command -v docker &>/dev/null && docker ps &>/dev/null; then
        log "  Docker: ${GREEN}available${NC}"
    else
        log "  Docker: ${YELLOW}not available${NC} (场景 1/3/4 可能失败)"
    fi

    echo ""
}

# ─── 核心测试函数 ───

# run_scenario <name> <message> <timeout> <keyword1> [keyword2] ...
run_scenario() {
    local name="$1"
    local message="$2"
    local timeout="$3"
    shift 3
    local keywords=("$@")

    local out_file="$TMPDIR/${name}.stdout"
    local err_file="$TMPDIR/${name}.stderr"
    local start_time
    start_time=$(date +%s)

    TOTAL=$((TOTAL + 1))
    log "场景 ${BOLD}${name}${NC} 开始... (timeout=${timeout}s)"

    # 调用 openclaw agent（用 -m 短参数 + --to 路由）
    openclaw agent \
        -m "$message" \
        --to "$OPENCLAW_TO" \
        --json \
        --timeout "$timeout" \
        > "$out_file" 2>"$err_file"
    local exit_code=$?

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # 提取回复（可能在 stdout 或 stderr）
    local reply
    reply=$(extract_reply "$out_file" "$err_file")
    local reply_preview
    reply_preview=$(echo "$reply" | python3 -c "import sys; t=sys.stdin.read().replace('\n',' '); print(t[:200])" 2>/dev/null || echo "$reply" | head -c 200)

    # 检查 openclaw 退出码（允许 exit=1 因为 gateway fallback 也返回 1）
    # 真正判断成功与否靠关键词匹配
    if [ -z "$reply" ] || [ "$reply" = "(empty output)" ]; then
        FAIL=$((FAIL + 1))
        local err_msg
        err_msg=$(grep -vE "Config warn|plugins|feishu|google-gemini|stale" "$err_file" 2>/dev/null | python3 -c "import sys; t=sys.stdin.read().replace('\n',' '); print(t[:200])" 2>/dev/null || echo "(parse error)")
        REPORT_LINES+=("${name}|FAIL|${duration}s|empty output: ${err_msg}")
        log "  ${RED}FAIL${NC} (${duration}s) empty output"
        return 1
    fi

    # 关键词验证
    local all_found=true
    local found_count=0
    local missing_keywords=()
    for kw in "${keywords[@]}"; do
        if echo "$reply" | grep -qi "$kw"; then
            found_count=$((found_count + 1))
        else
            all_found=false
            missing_keywords+=("$kw")
        fi
    done

    if $all_found; then
        PASS=$((PASS + 1))
        REPORT_LINES+=("${name}|PASS|${duration}s|${found_count}/${#keywords[@]} keywords: ${reply_preview}")
        log "  ${GREEN}PASS${NC} (${duration}s) ${found_count}/${#keywords[@]} keywords found"
        return 0
    else
        FAIL=$((FAIL + 1))
        REPORT_LINES+=("${name}|FAIL|${duration}s|missing: ${missing_keywords[*]} | got: ${reply_preview}")
        log "  ${RED}FAIL${NC} (${duration}s) missing keywords: ${missing_keywords[*]}"
        return 1
    fi
}

# ─── 测试场景 ───

scenario_1_docker_basic() {
    run_scenario \
        "1-Docker基础" \
        '使用 agent-browser skill，docker 模式打开 http://example.com，告诉我页面的 H1 标题是什么' \
        "$OPENCLAW_TIMEOUT" \
        "Example Domain"
}

scenario_2_local_mode() {
    # 注：FastAPI 当前以 docker 模式运行，local 模式需要服务以 --browser-mode local 启动
    # 此场景验证不同端点访问能力，使用 docker 模式访问 httpbin.org/get
    run_scenario \
        "2-HttpBin验证" \
        '使用 agent-browser skill，docker 模式打开 http://httpbin.org/get，告诉我页面返回的 JSON 中 url 字段的值' \
        "$OPENCLAW_TIMEOUT" \
        "httpbin"
}

scenario_3_multi_turn() {
    run_scenario \
        "3-多轮交互" \
        '使用 agent-browser skill，docker 模式，分两步操作：第一步访问 http://example.com 记录页面标题，第二步在同一个会话内再访问 http://httpbin.org/ip 记录返回的 IP 信息。最后汇总两次访问的结果告诉我。' \
        "$OPENCLAW_TIMEOUT_LONG" \
        "Example Domain" "origin"
}

scenario_4_concurrent() {
    log "场景 ${BOLD}4-独立Session${NC} 开始... (顺序执行，验证 FastAPI 独立 session 隔离)"
    local start_time
    start_time=$(date +%s)

    # 用随机 --to 确保每次运行创建全新 OpenClaw session（避免脏状态）
    # 注：OpenClaw gateway 不支持真正并发连接，故顺序执行；
    # FastAPI 层面的 session 隔离通过两次独立调用验证。
    local rand_a=$(( RANDOM % 9000 + 1000 ))
    local rand_b=$(( RANDOM % 9000 + 1000 ))

    log "  执行 4A-UUID..."
    openclaw agent \
        -m '使用 agent-browser skill，docker 模式访问 http://httpbin.org/uuid，告诉我页面返回的 uuid 值' \
        --to "+100000${rand_a}" \
        --json \
        --timeout "$OPENCLAW_TIMEOUT" \
        > "$TMPDIR/4A.stdout" 2>"$TMPDIR/4A.stderr" || true

    log "  执行 4B-IP..."
    openclaw agent \
        -m '使用 agent-browser skill，docker 模式访问 http://httpbin.org/ip，告诉我页面返回的 IP 地址' \
        --to "+100000${rand_b}" \
        --json \
        --timeout "$OPENCLAW_TIMEOUT" \
        > "$TMPDIR/4B.stdout" 2>"$TMPDIR/4B.stderr" || true

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log "场景 4 总耗时 ${duration}s"

    # 验证两个结果
    _validate_concurrent "4A-独立UUID" "$TMPDIR/4A.stdout" "$TMPDIR/4A.stderr" "$start_time" "uuid"
    _validate_concurrent "4B-独立IP" "$TMPDIR/4B.stdout" "$TMPDIR/4B.stderr" "$start_time" "ip"
}

_validate_concurrent() {
    local name="$1"
    local out_file="$2"
    local err_file="$3"
    local start_time="$4"
    shift 4
    local keywords=("$@")

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    TOTAL=$((TOTAL + 1))

    local reply
    reply=$(extract_reply "$out_file" "$err_file")
    local reply_preview
    reply_preview=$(echo "$reply" | python3 -c "import sys; t=sys.stdin.read().replace('\n',' '); print(t[:200])" 2>/dev/null || echo "")

    if [ -z "$reply" ] || [ "$reply" = "(empty output)" ]; then
        FAIL=$((FAIL + 1))
        REPORT_LINES+=("${name}|FAIL|${duration}s|empty output")
        log "  ${RED}FAIL${NC} ${name}: empty output"
        return 1
    fi

    local all_found=true
    local found_count=0
    local missing_keywords=()
    for kw in "${keywords[@]}"; do
        if echo "$reply" | grep -qi "$kw"; then
            found_count=$((found_count + 1))
        else
            all_found=false
            missing_keywords+=("$kw")
        fi
    done

    if $all_found; then
        PASS=$((PASS + 1))
        REPORT_LINES+=("${name}|PASS|${duration}s|${found_count}/${#keywords[@]} keywords: ${reply_preview}")
        log "  ${GREEN}PASS${NC} ${name} (${found_count}/${#keywords[@]} keywords)"
        return 0
    else
        FAIL=$((FAIL + 1))
        REPORT_LINES+=("${name}|FAIL|${duration}s|missing: ${missing_keywords[*]} | got: ${reply_preview}")
        log "  ${RED}FAIL${NC} ${name}: missing keywords: ${missing_keywords[*]}"
        return 1
    fi
}

# ─── 报告输出 ───

print_report() {
    echo ""
    echo "================================================================="
    echo " Agent Browser x OpenClaw E2E Test Report"
    echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================="
    echo ""
    printf " %-14s | %-6s | %-8s | %s\n" "Scenario" "Status" "Duration" "Notes"
    echo "----------------|--------|----------|----------------------------------"

    for line in "${REPORT_LINES[@]}"; do
        local name status duration notes
        IFS='|' read -r name status duration notes <<< "$line"
        local status_display
        if [ "$status" = "PASS" ]; then
            status_display="${GREEN}PASS${NC}"
        else
            status_display="${RED}FAIL${NC}"
        fi
        printf " %-14s | ${status_display}%-2s | %-8s | %.60s\n" "$name" "" "$duration" "$notes"
    done

    echo ""
    echo "================================================================="
    if [ $FAIL -eq 0 ]; then
        echo -e " Result: ${GREEN}${PASS}/${TOTAL} PASSED${NC}    Exit code: 0"
    else
        echo -e " Result: ${RED}${PASS}/${TOTAL} PASSED, ${FAIL} FAILED${NC}    Exit code: 1"
    fi
    echo "================================================================="
    echo ""
    echo "Logs: $TMPDIR"
}

# ─── Main ───

main() {
    echo ""
    echo "================================================================="
    echo " Agent Browser x OpenClaw E2E Test"
    echo "================================================================="
    echo ""

    preflight_check

    # 顺序执行场景 1~3
    scenario_1_docker_basic || true
    echo ""

    scenario_2_local_mode || true
    echo ""

    scenario_3_multi_turn || true
    echo ""

    # 执行场景 4（顺序验证独立 session 隔离）
    scenario_4_concurrent
    echo ""

    # 输出报告
    print_report

    # 退出码
    if [ $FAIL -eq 0 ]; then
        exit 0
    else
        exit 1
    fi
}

main "$@"
