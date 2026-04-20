---
name: boss-screen
argument-hint: "[min_years=N] [max_years=N] [keywords=<text>] [target=N] [job_id=<text>] [--skip-cache]"
description: >
  Boss 直聘候选人智能筛选与收藏。
  流式处理：边扫描边筛选，找到目标数量即停止，最小化 token 消耗。
  支持缓存避免重复筛选，输出统计数据。
---

# Boss 直聘候选人筛选

> **CRITICAL RULE — 使用 stealth-browser CLI 命令执行所有操作**
>
> 不要写 Python 脚本，不要 import 任何模块。
> 所有浏览器操作通过 `stealth-browser` 命令执行。

## 参数解析

从 $ARGUMENTS 提取以下参数（支持 key=value 格式）：

- `min_years` — 最低工作年限（默认 1）
- `max_years` — 最高工作年限（默认 3）
- `keywords` — 筛选关键词（逗号分隔，默认 "AI,大模型,LLM,机器学习,深度学习,NLP,CV,AIGC,RAG,向量数据库"）
- `target` — 目标收藏人数（默认 3）
- `job_id` — 职位 ID（默认 "default"）
- `--skip-cache` — 跳过缓存检查（可选）

## 执行流程

### Step 1: 初始化

```bash
# 检查是否提供了参数或描述
if [ -z "$ARGUMENTS" ]; then
  cat << 'EOF'
❌ 请提供筛选条件或参数

【使用方式 1：自然语言描述】
/boss-screen 帮我筛选Boss 直聘推荐牛人中符合条件的候选人。

【筛选条件】
1. 工作经验 1～3 年（年限显示为"1年"或"2年"或"3年"，跳过 4 年及以上）
2. 有 AI 相关项目研发经验（含关键词：AI、大模型、LLM、机器学习、深度学习、NLP、CV、AIGC、RAG、向量数据库等）

【使用方式 2：参数格式】
/boss-screen min_years=1 max_years=3 keywords=AI,大模型,LLM target=5

【可用参数】
  min_years=N      - 最低工作年限（默认 1）
  max_years=N      - 最高工作年限（默认 3）
  keywords=<text>  - 筛选关键词，逗号分隔（默认 AI,大模型,LLM,机器学习,深度学习,NLP,CV,AIGC,RAG,向量数据库）
  target=N         - 目标收藏人数（默认 3）
  job_id=<text>    - 职位 ID，用于区分不同职位的缓存（默认 default）
  --skip-cache     - 跳过缓存检查，重新扫描所有候选人
EOF
  exit 0
fi

# 默认值
min_years=1
max_years=3
keywords="AI,大模型,LLM,机器学习,深度学习,NLP,CV,AIGC,RAG,向量数据库"
target=3
job_id="default"
skip_cache=false

# 解析参数
for arg in $ARGUMENTS; do
  case $arg in
    min_years=*) min_years="${arg#*=}" ;;
    max_years=*) max_years="${arg#*=}" ;;
    keywords=*) keywords="${arg#*=}" ;;
    target=*) target="${arg#*=}" ;;
    job_id=*) job_id="${arg#*=}" ;;
    --skip-cache) skip_cache=true ;;
  esac
done

echo "========== 筛选参数 =========="
echo "工作年限: ${min_years}-${max_years} 年"
echo "关键词: ${keywords}"
echo "目标收藏数: ${target}"
echo "职位 ID: ${job_id}"
echo "=============================="
echo ""

# 缓存目录（跨平台）
if [ -d "$HOME/.stealth-browser" ]; then
  CACHE_DIR="$HOME/.stealth-browser"
elif [ -d "$HOME/.cache" ]; then
  CACHE_DIR="$HOME/.cache/stealth-browser"
  mkdir -p "$CACHE_DIR"
else
  CACHE_DIR="/tmp/stealth-browser"
  mkdir -p "$CACHE_DIR"
fi
CACHE_FILE="$CACHE_DIR/boss_screening_${job_id}.json"

# 加载已处理 ID（逗号分隔字符串，传入 JS 更安全）
PROCESSED_IDS=""
if [ -f "$CACHE_FILE" ] && [ "$skip_cache" != "true" ]; then
  PROCESSED_IDS=$(jq -r '(.processed_ids // []) | join(",")' "$CACHE_FILE" 2>/dev/null || echo "")
  echo "已处理候选人数: $(echo "$PROCESSED_IDS" | tr ',' '\n' | grep -c .)"
else
  echo "跳过缓存或缓存文件不存在"
fi
echo ""

# 创建或复用 session（使用 boss，与缓存一致）
stealth-browser session create --name boss 2>/dev/null || echo "Session already exists, reusing..."
```

### Step 2: 导航到推荐牛人页面

```bash
echo "导航到推荐牛人页面..."
stealth-browser open "https://www.zhipin.com/web/chat/recommend" --session boss
sleep 2

# 检查是否需要登录
CHECK_RESULT=$(stealth-browser check --session boss)
if echo "$CHECK_RESULT" | jq -e '.data.intervention' > /dev/null 2>&1; then
  VNC_URL=$(echo "$CHECK_RESULT" | jq -r '.data.vnc_url // ""')
  REASON=$(echo "$CHECK_RESULT" | jq -r '.data.intervention.reason // "需要登录"')
  echo ""
  echo "⚠️  需要人工介入: $REASON"
  echo "请访问以下 URL 完成登录："
  echo "$VNC_URL"
  echo ""
  echo "完成后按 Enter 继续..."
  read -r
fi

# 等待 iframe 加载
stealth-browser wait "iframe" --timeout 10000 --session boss
sleep 2
echo "页面加载完成"
echo ""
```

### Step 3: 流式筛选主循环

**架构说明**：每次循环处理一个候选人卡片（cursor 递增），初筛通过后执行两次 eval：
- Eval 1：点击名字打开详情
- sleep 2（等待详情面板渲染）
- Eval 2：提取详情 + AI 精筛 + 收藏 + 关闭

找到目标数量即停止，无需预先扫描全部候选人。

```bash
COLLECTED=0
REFINED_COUNT=0
CURSOR=0
SCROLL_COUNT=0
MAX_SCROLL=5
COLLECTED_LIST=""
NEW_IDS=""

echo "开始流式筛选..."
echo ""

while [ "$COLLECTED" -lt "$target" ]; do

  # ── Eval 1: 初筛当前 cursor 位置的候选人 ──────────────────────────
  SCAN=$(stealth-browser eval "
  (() => {
    const iframe = document.querySelector('iframe');
    if (!iframe || !iframe.contentDocument) return JSON.stringify({status:'error',msg:'iframe not found'});
    const doc = iframe.contentDocument;
    const cards = Array.from(doc.querySelectorAll('.recommend-wrap [class*=\"candidate\"]')).slice(1);

    const cursor = $CURSOR;
    if (cursor >= cards.length) return JSON.stringify({status:'no_more',total:cards.length});

    const card = cards[cursor];
    const nameEl = card.querySelector('.name');
    const name = nameEl ? nameEl.textContent.trim() : '';
    if (!name) return JSON.stringify({status:'skip',reason:'no name',cursor:cursor+1});

    const candidateId = name + '_' + card.textContent.substring(0,50).replace(/\s+/g,'');
    const processedIds = '$PROCESSED_IDS'.split(',').filter(Boolean);
    if (processedIds.includes(candidateId)) return JSON.stringify({status:'skip',reason:'cached',cursor:cursor+1});

    const text = card.textContent;
    const yearsMatch = text.match(/(\d+)年/);
    const years = yearsMatch ? parseInt(yearsMatch[1]) : 0;
    if (years < $min_years || years > $max_years) return JSON.stringify({status:'skip',reason:'years',cursor:cursor+1});

    const keywords = '$keywords'.split(',').map(k=>k.trim());
    const aiMatched = keywords.filter(k=>text.includes(k));
    if (aiMatched.length === 0) return JSON.stringify({status:'skip',reason:'no keywords',cursor:cursor+1});

    const schoolMatch = text.match(/([\u4e00-\u9fa5]{2,10}(?:大学|学院|学校))/);
    const school = schoolMatch ? schoolMatch[1] : '';

    // 点击打开详情
    nameEl.click();

    return JSON.stringify({
      status:'clicked',
      cursor:cursor+1,
      id:candidateId,
      name:name,
      years:years,
      school:school,
      ai_keywords:aiMatched.join(',')
    });
  })()
  " --session boss)

  SCAN_DATA=$(echo "$SCAN" | jq -r '.data.result // "{}"' 2>/dev/null)
  if [ $? -ne 0 ] || [ -z "$SCAN_DATA" ] || [ "$SCAN_DATA" = "{}" ]; then
    echo "扫描数据解析失败，原始内容:"
    echo "$SCAN" | head -c 200
    CURSOR=$((CURSOR + 1))
    continue
  fi
  
  SCAN_STATUS=$(echo "$SCAN_DATA" | jq -r '.status // "error"')
  NEW_CURSOR=$(echo "$SCAN_DATA" | jq -r '.cursor // 0')

  # 更新 cursor
  if [ "$NEW_CURSOR" != "0" ]; then
    CURSOR=$NEW_CURSOR
  else
    CURSOR=$((CURSOR + 1))
  fi

  # 无更多候选人 → 滚动加载
  if [ "$SCAN_STATUS" = "no_more" ]; then
    if [ "$SCROLL_COUNT" -ge "$MAX_SCROLL" ]; then
      echo "已滚动 $MAX_SCROLL 次，无更多候选人，停止"
      break
    fi
    echo "滚动加载更多候选人（第 $((SCROLL_COUNT+1)) 次）..."
    stealth-browser eval "
    (() => {
      const iframe = document.querySelector('iframe');
      const doc = iframe.contentDocument;
      const container = doc.scrollingElement || doc.body;
      container.scrollTop = container.scrollHeight;
      return 'scrolled';
    })()
    " --session boss > /dev/null
    sleep 3
    SCROLL_COUNT=$((SCROLL_COUNT + 1))
    # cursor 不重置，继续从当前位置往后扫
    continue
  fi

  # 跳过（年限/关键词/缓存不符）
  if [ "$SCAN_STATUS" = "skip" ]; then
    continue
  fi

  # 错误
  if [ "$SCAN_STATUS" = "error" ]; then
    MSG=$(echo "$SCAN_DATA" | jq -r '.msg // "unknown"')
    echo "扫描错误: $MSG"
    sleep 1
    continue
  fi

  # ── 初筛通过，等待详情面板渲染 ────────────────────────────────────
  CAND_NAME=$(echo "$SCAN_DATA" | jq -r '.name')
  CAND_YEARS=$(echo "$SCAN_DATA" | jq -r '.years')
  CAND_SCHOOL=$(echo "$SCAN_DATA" | jq -r '.school')
  CAND_AI=$(echo "$SCAN_DATA" | jq -r '.ai_keywords')
  CAND_ID=$(echo "$SCAN_DATA" | jq -r '.id')

  echo "精筛: $CAND_NAME (${CAND_YEARS}年, $CAND_SCHOOL)"
  
  # 等待详情面板出现（替代固定 sleep）
  WAIT_RESULT=$(stealth-browser eval "
  (() => {
    const iframe = document.querySelector('iframe');
    if (!iframe || !iframe.contentDocument) return 'no_iframe';
    const doc = iframe.contentDocument;
    const popup = doc.querySelector('.boss-popup__content');
    return popup ? 'ready' : 'not_ready';
  })()
  " --session boss)
  
  WAIT_STATUS=$(echo "$WAIT_RESULT" | jq -r '.data.result // "error"')
  if [ "$WAIT_STATUS" != "ready" ]; then
    # 面板未出现，等待 2s 后重试一次
    sleep 2
    WAIT_RESULT=$(stealth-browser eval "
    (() => {
      const iframe = document.querySelector('iframe');
      if (!iframe || !iframe.contentDocument) return 'no_iframe';
      const doc = iframe.contentDocument;
      const popup = doc.querySelector('.boss-popup__content');
      return popup ? 'ready' : 'not_ready';
    })()
    " --session boss)
    WAIT_STATUS=$(echo "$WAIT_RESULT" | jq -r '.data.result // "error"')
    if [ "$WAIT_STATUS" != "ready" ]; then
      echo "  ✗ 详情面板加载超时，跳过"
      continue
    fi
  fi

  # ── Eval 2: 提取详情 + AI 精筛 + 收藏 + 关闭 ─────────────────────
  DETAIL=$(stealth-browser eval "
  (() => {
    const iframe = document.querySelector('iframe');
    if (!iframe || !iframe.contentDocument) return JSON.stringify({status:'error',msg:'iframe lost'});
    const doc = iframe.contentDocument;
    const popup = doc.querySelector('.boss-popup__content');
    if (!popup) return JSON.stringify({status:'no_popup'});

    const detailText = popup.textContent.replace(/\s+/g,' ');
    const aiPattern = /AI|大模型|LLM|机器学习|深度学习|NLP|CV|AIGC|RAG|向量数据库|Transformer|GPT|BERT|模型训练|模型部署|Prompt|微调|LangChain|Spring AI|智能体|Agent/i;
    const hasAI = aiPattern.test(detailText);

    let collected = false;
    let collectBtnFound = false;
    if (hasAI) {
      const likeBtn = doc.querySelector('.like-icon-and-text');
      if (likeBtn) {
        collectBtnFound = true;
        likeBtn.click();
        
        // 使用 Promise 等待状态更新
        return new Promise(resolve => {
          setTimeout(() => {
            // 检查子元素状态变化（实际变化在 .like-icon 上）
            const iconEl = likeBtn.querySelector('.like-icon');
            const btnText = likeBtn.querySelector('.btn-text');
            const collected = (iconEl && iconEl.className.includes('like-icon-active')) || 
                            (btnText && btnText.textContent.trim() === '已收藏');
            
            // 关闭详情面板
            const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
            if (closeBtn) closeBtn.click();
            
            resolve(JSON.stringify({status:'ok', has_ai:hasAI, collected:collected, btn_found:true}));
          }, 1000);
        });
      } else {
        const favBtn = Array.from(doc.querySelectorAll('button,[class*=\"btn\"],[class*=\"like\"]'))
          .find(e => e.textContent.trim().includes('收藏'));
        if (favBtn) {
          collectBtnFound = true;
          favBtn.click();
          
          return new Promise(resolve => {
            setTimeout(() => {
              // 关闭详情面板
              const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
              if (closeBtn) closeBtn.click();
              
              resolve(JSON.stringify({status:'ok', has_ai:hasAI, collected:true, btn_found:true}));
            }, 1000);
          });
        }
      }
    }

    // 关闭详情面板
    const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
    if (closeBtn) closeBtn.click();

    return JSON.stringify({status:'ok', has_ai:hasAI, collected:collected, btn_found:collectBtnFound});
  })()
  " --session boss)

  DETAIL_DATA=$(echo "$DETAIL" | jq -r '.data.result // "{}"' 2>/dev/null)
  if [ $? -ne 0 ] || [ -z "$DETAIL_DATA" ] || [ "$DETAIL_DATA" = "{}" ]; then
    echo "  ✗ 详情数据解析失败，原始内容:"
    echo "$DETAIL" | head -c 200
    continue
  fi
  
  DETAIL_STATUS=$(echo "$DETAIL_DATA" | jq -r '.status // "error"')
  HAS_AI=$(echo "$DETAIL_DATA" | jq -r '.has_ai // false')
  WAS_COLLECTED=$(echo "$DETAIL_DATA" | jq -r '.collected // false')
  BTN_FOUND=$(echo "$DETAIL_DATA" | jq -r '.btn_found // false')

  if [ "$DETAIL_STATUS" = "no_popup" ]; then
    echo "  ✗ 详情面板未出现，跳过"
    continue
  fi

  if [ "$HAS_AI" = "true" ]; then
    REFINED_COUNT=$((REFINED_COUNT + 1))
    if [ "$WAS_COLLECTED" = "true" ]; then
      COLLECTED=$((COLLECTED + 1))
      echo "  ★ 已收藏 [$COLLECTED/$target]"
      COLLECTED_LIST="${COLLECTED_LIST}${COLLECTED}. ${CAND_NAME} | ${CAND_YEARS}年 | ${CAND_SCHOOL} | ${CAND_AI}\n"
      # 追加到已处理 ID
      if [ -z "$NEW_IDS" ]; then
        NEW_IDS="$CAND_ID"
      else
        NEW_IDS="${NEW_IDS},${CAND_ID}"
      fi
    else
      if [ "$BTN_FOUND" = "true" ]; then
        echo "  ✓ 精筛通过但收藏状态未确认（可能已收藏）"
      else
        echo "  ✓ 精筛通过但收藏按钮未找到"
      fi
    fi
  else
    echo "  ✗ 精筛不通过"
  fi

  sleep 1
done
```

### Step 4: 输出统计 + 更新缓存

```bash
echo ""
echo "========== 筛选统计 =========="
echo "精筛通过: $REFINED_COUNT"
echo "收藏人数: $COLLECTED / $target"
if [ "$target" -gt 0 ]; then
  COMPLETION=$(( (COLLECTED * 100) / target ))
  echo "完成度: ${COMPLETION}%"
fi
echo "=============================="
echo ""

if [ -n "$COLLECTED_LIST" ]; then
  echo "已收藏候选人:"
  printf '%b\n' "$COLLECTED_LIST"
fi

# 批量更新缓存（合并新旧 ID，避免重复写入）
if [ -n "$NEW_IDS" ]; then
  IDS_ARRAY=$(printf '%s' "$NEW_IDS" | tr ',' '\n' | jq -R . | jq -s .)
  if [ -f "$CACHE_FILE" ]; then
    jq --argjson ids "$IDS_ARRAY" \
       --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
       --argjson refined "$REFINED_COUNT" \
       --argjson collected "$COLLECTED" \
       '.processed_ids = ((.processed_ids // []) + $ids | unique) |
        .stats.total_refined_screened = $refined |
        .stats.total_collected = $collected |
        .stats.last_run = $ts' \
       "$CACHE_FILE" > "$CACHE_FILE.tmp" && mv "$CACHE_FILE.tmp" "$CACHE_FILE"
  else
    printf '{"job_id":"%s","processed_ids":%s,"stats":{"total_refined_screened":%d,"total_collected":%d,"last_run":"%s"}}\n' \
      "$job_id" "$IDS_ARRAY" "$REFINED_COUNT" "$COLLECTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$CACHE_FILE"
  fi
  echo "缓存已更新: $CACHE_FILE"
fi
```

## 缓存文件格式

路径: `$CACHE_DIR/boss_screening_{job_id}.json`

```json
{
  "job_id": "ai_engineer",
  "processed_ids": [
    "韩康宇_12-18K韩康宇刚刚活跃24岁3年本科",
    "陈鹏_面议陈鹏24岁2年本科离职"
  ],
  "stats": {
    "total_refined_screened": 5,
    "total_collected": 3,
    "last_run": "2026-04-20T10:30:00Z"
  }
}
```

## 错误处理

- **登录拦截**: 检测到 `intervention` 字段时，输出 VNC URL 并等待用户确认
- **iframe 未找到**: 报错并跳过当前候选人
- **详情面板未出现**: 跳过该候选人，继续下一个
- **收藏按钮未找到**: 记录精筛通过但收藏失败，继续执行
- **无更多候选人**: 最多滚动 5 次，超出则停止

## Boss 直聘页面结构备忘

```
主页面: https://www.zhipin.com/web/chat/recommend
└── iframe（推荐牛人 frame）
    ├── .recommend-wrap
    │   └── [class*="candidate"]（候选人卡片，第一个是头部，slice(1) 跳过）
    │       ├── .name（候选人姓名，可点击打开详情）
    │       ├── 年龄/年限/学历标签
    │       └── .geek-desc .content（简介文字）
    └── 详情弹窗（点击名字后出现）
        ├── .boss-popup__content（整体内容区）
        │   ├── .like-icon-and-text（收藏按钮）
        │   ├── .boss-dialog__close（关闭按钮）
        │   └── iframe[src*="c-resume"]（嵌套简历 iframe，通常未加载完）
        └── .resume-right-side（经历概览，在 .boss-popup__content 内）
```

## 优化说明

相比旧版本的改进：

1. **流式处理**：不再批量提取所有候选人，边扫描边筛选，找到目标数量即停止
2. **2 次 eval/候选人**（旧版 4 次）：Eval1 初筛+点击，sleep 2，Eval2 精筛+收藏+关闭
3. **自动滚动循环**：不足时自动滚动，最多 5 次，无需手动重跑
4. **修复 9 个 bug**：
   - `.data.result` 嵌套 JSON 正确解析
   - `while IFS= read -r` 替代 `for` 循环（中文字符安全）
   - `[[ ]]` 替代 `[ ]` 做 glob 匹配
   - `grep -E` 替代 `grep -P`（macOS 兼容）
   - bash 整数运算替代 `bc`
   - `printf '%b\n'` 替代 `echo -e`
   - session 名统一为 `boss`
   - 缓存批量写入替代逐条写入
   - **收藏状态检测修复**：检查子元素 `.like-icon-active` 和文本"已收藏"（2026-04-20）
