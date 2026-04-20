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

**架构说明**：每次循环批量处理 3-5 个候选人卡片，通过两层 LLM 筛选：
- Eval 1a：批量提取候选人卡片信息（3-5 个）
- Claude 决策点（批量初筛）：选择值得点击详情的候选人
- Eval 1b：逐个点击通过初筛的候选人
  - 等待详情面板渲染
  - Eval 2a：提取详情文本
  - Claude 决策点（精筛）：评估是否收藏
  - Eval 2b：执行收藏或跳过

找到目标数量即停止，两层 LLM 筛选确保候选人质量。

```bash
COLLECTED=0
REFINED_COUNT=0
CURSOR=0
SCROLL_COUNT=0
MAX_SCROLL=5
BATCH_SIZE=5
COLLECTED_LIST=""
NEW_IDS=""

echo "开始流式筛选..."
echo ""

while [ "$COLLECTED" -lt "$target" ]; do

  # ── Eval 1a: 批量提取候选人卡片信息 ──────────────────────────
  BATCH=$(stealth-browser eval "
  (() => {
    const iframe = document.querySelector('iframe');
    if (!iframe || !iframe.contentDocument) return JSON.stringify({status:'error',msg:'iframe not found'});
    const doc = iframe.contentDocument;
    const cards = Array.from(doc.querySelectorAll('.recommend-wrap [class*=\"candidate\"]')).slice(1);

    const cursor = $CURSOR;
    const batchSize = $BATCH_SIZE;
    const endIdx = Math.min(cursor + batchSize, cards.length);
    
    if (cursor >= cards.length) return JSON.stringify({status:'no_more',total:cards.length});

    const batch = [];
    for (let i = cursor; i < endIdx; i++) {
      const card = cards[i];
      const nameEl = card.querySelector('.name');
      const name = nameEl ? nameEl.textContent.trim() : '';
      if (!name) continue;

      const text = card.textContent;
      const yearsMatch = text.match(/(\d+)年/);
      const years = yearsMatch ? parseInt(yearsMatch[1]) : 0;
      const schoolMatch = text.match(/([\u4e00-\u9fa5]{2,10}(?:大学|学院|学校))/);
      const school = schoolMatch ? schoolMatch[1] : '';
      
      const snippet = text.replace(/\s+/g, ' ').substring(0, 200);
      
      batch.push({
        index: i,
        name: name,
        years: years,
        school: school,
        snippet: snippet
      });
    }

    return JSON.stringify({
      status: 'ok',
      batch: batch,
      total: cards.length,
      next_cursor: endIdx
    });
  })()
  " --session boss)

  BATCH_DATA=$(echo "$BATCH" | jq -r '.data.result // "{}"' 2>/dev/null)
  BATCH_STATUS=$(echo "$BATCH_DATA" | jq -r '.status // "error"')

  # 无更多候选人 → 滚动加载
  if [ "$BATCH_STATUS" = "no_more" ]; then
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
    continue
  fi

  if [ "$BATCH_STATUS" = "error" ]; then
    echo "批量提取失败，跳过"
    CURSOR=$((CURSOR + BATCH_SIZE))
    continue
  fi

  # ── Claude 决策点（批量初筛）────────────────────────────────
  CANDIDATES=$(echo "$BATCH_DATA" | jq -r '.batch // "[]"')
  CANDIDATE_COUNT=$(echo "$CANDIDATES" | jq 'length')

  if [ "$CANDIDATE_COUNT" -eq 0 ]; then
    echo "本批次无有效候选人，继续下一批"
    NEXT_CURSOR=$(echo "$BATCH_DATA" | jq -r '.next_cursor // 0')
    CURSOR=$NEXT_CURSOR
    continue
  fi

  echo ""
  echo "========== 批量初筛 (LLM 模式) =========="
  echo "本批次候选人数: $CANDIDATE_COUNT"
  echo ""

  # 输出每个候选人的卡片信息
  echo "$CANDIDATES" | jq -r '.[] | "[\(.index)] \(.name) | \(.years)年 | \(.school)\n  简介: \(.snippet)\n"'

  echo "筛选条件:"
  echo "- 年限要求: $min_years ~ $max_years 年"
  echo "- 关键词: $keywords"
  echo "- 岗位要求: AI 相关项目研发经验"
  echo "=========================================="
  echo ""

  # ★★★ Claude 批量初筛决策点 ★★★
  # 
  # Claude: 请根据以上候选人卡片信息，进行批量初筛
  #
  # 评估标准:
  # 1. 年限是否在要求范围内
  # 2. 简介中是否包含 AI 相关关键词
  # 3. 学校背景（985/211 优先）
  # 4. 简介中是否体现相关项目经验
  #
  # 决策规则:
  # - 选择值得点击详情的候选人索引（逗号分隔）
  # - 如果全部不符合，设置 SELECTED_INDICES=""
  # - 如果有符合的，设置 SELECTED_INDICES="0,2,4"（示例）
  #
  # 请在执行下一个 bash 代码块之前，临时执行一个命令来设置 SELECTED_INDICES 变量
  # 例如: SELECTED_INDICES="0,2"  # 理由: 候选人 0 和 2 有 AI 项目经验

  # 默认值: 如果 Claude 未设置，默认为空（跳过本批次）
  : ${SELECTED_INDICES:=""}

  if [ -z "$SELECTED_INDICES" ]; then
    echo "  ✗ 本批次无候选人通过初筛，跳过"
    NEXT_CURSOR=$(echo "$BATCH_DATA" | jq -r '.next_cursor // 0')
    CURSOR=$NEXT_CURSOR
    continue
  fi

  echo "  ✓ 通过初筛的候选人索引: $SELECTED_INDICES"
  echo ""

  # ── Eval 1b: 逐个处理通过初筛的候选人 ──────────────────────
  IFS=',' read -ra INDICES <<< "$SELECTED_INDICES"

  for idx in "${INDICES[@]}"; do
    idx=$(echo "$idx" | tr -d ' ')
    
    CAND_INFO=$(echo "$CANDIDATES" | jq -r ".[] | select(.index == $idx)")
    if [ -z "$CAND_INFO" ] || [ "$CAND_INFO" = "null" ]; then
      echo "  ✗ 候选人索引 $idx 无效，跳过"
      continue
    fi
    
    CAND_NAME=$(echo "$CAND_INFO" | jq -r '.name')
    CAND_YEARS=$(echo "$CAND_INFO" | jq -r '.years')
    CAND_SCHOOL=$(echo "$CAND_INFO" | jq -r '.school')
    CAND_INDEX=$(echo "$CAND_INFO" | jq -r '.index')
    
    echo "精筛: $CAND_NAME (${CAND_YEARS}年, $CAND_SCHOOL)"
    
    # 点击候选人打开详情
    CLICK_RESULT=$(stealth-browser eval "
    (() => {
      const iframe = document.querySelector('iframe');
      if (!iframe || !iframe.contentDocument) return JSON.stringify({status:'error',msg:'iframe not found'});
      const doc = iframe.contentDocument;
      const cards = Array.from(doc.querySelectorAll('.recommend-wrap [class*=\"candidate\"]')).slice(1);
      
      const card = cards[$CAND_INDEX];
      if (!card) return JSON.stringify({status:'error',msg:'card not found'});
      
      const nameEl = card.querySelector('.name');
      if (!nameEl) return JSON.stringify({status:'error',msg:'name element not found'});
      
      nameEl.click();
      return JSON.stringify({status:'ok'});
    })()
    " --session boss)
    
    CLICK_STATUS=$(echo "$CLICK_RESULT" | jq -r '.data.result.status // "error"')
    if [ "$CLICK_STATUS" != "ok" ]; then
      echo "  ✗ 点击失败，跳过"
      continue
    fi
    
    # 等待详情面板出现
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

    # ── Eval 2a: 提取详情文本（不执行收藏）────────────────────
    DETAIL=$(stealth-browser eval "
    (() => {
      const iframe = document.querySelector('iframe');
      if (!iframe || !iframe.contentDocument) return JSON.stringify({status:'error',msg:'iframe lost'});
      const doc = iframe.contentDocument;
      const popup = doc.querySelector('.boss-popup__content');
      if (!popup) return JSON.stringify({status:'no_popup'});

      const detailText = popup.textContent.replace(/\s+/g,' ');
      
      const extractSection = (title) => {
        const regex = new RegExp(title + '[：:]?([^]*?)(?=工作经历|项目经验|教育经历|个人优势|期望职位|$)', 'i');
        const match = detailText.match(regex);
        return match ? match[1].trim().substring(0, 400) : '';
      };
      
      return JSON.stringify({
        status: 'ok',
        full_text: detailText.substring(0, 800),
        work_exp: extractSection('工作经历'),
        project_exp: extractSection('项目经验'),
        education: extractSection('教育经历'),
        advantage: extractSection('个人优势')
      });
    })()
    " --session boss)

    DETAIL_DATA=$(echo "$DETAIL" | jq -r '.data.result // "{}"' 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$DETAIL_DATA" ] || [ "$DETAIL_DATA" = "{}" ]; then
      echo "  ✗ 详情数据解析失败"
      stealth-browser eval "
      (() => {
        const iframe = document.querySelector('iframe');
        const doc = iframe.contentDocument;
        const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
        if (closeBtn) closeBtn.click();
        return 'closed';
      })()
      " --session boss > /dev/null
      continue
    fi
    
    DETAIL_STATUS=$(echo "$DETAIL_DATA" | jq -r '.status // "error"')

    if [ "$DETAIL_STATUS" = "no_popup" ]; then
      echo "  ✗ 详情面板未出现，跳过"
      continue
    fi

    FULL_TEXT=$(echo "$DETAIL_DATA" | jq -r '.full_text // ""')
    WORK_EXP=$(echo "$DETAIL_DATA" | jq -r '.work_exp // ""')
    PROJECT_EXP=$(echo "$DETAIL_DATA" | jq -r '.project_exp // ""')
    EDUCATION=$(echo "$DETAIL_DATA" | jq -r '.education // ""')
    ADVANTAGE=$(echo "$DETAIL_DATA" | jq -r '.advantage // ""')

    # ── Claude 决策点: 评估候选人匹配度 ────────────────────────
    echo ""
    echo "=========================================="
    echo "候选人: $CAND_NAME"
    echo "年限: $CAND_YEARS 年 | 学校: $CAND_SCHOOL"
    echo ""
    echo "【工作经历】"
    echo "$WORK_EXP"
    echo ""
    echo "【项目经验】"
    echo "$PROJECT_EXP"
    echo ""
    echo "【教育经历】"
    echo "$EDUCATION"
    echo ""
    echo "【个人优势】"
    echo "$ADVANTAGE"
    echo ""
    echo "筛选条件:"
    echo "- 年限要求: $min_years ~ $max_years 年"
    echo "- 关键词: $keywords"
    echo "- 岗位要求: AI 相关项目研发经验"
    echo "=========================================="
    echo ""

    # ★★★ Claude 决策点 ★★★
    # 
    # Claude: 请根据以上候选人详情，评估其与岗位的匹配度
    #
    # 评估维度:
    # 1. 工作经历中是否有实质性的 AI 项目经验（权重 40%）
    # 2. 项目经验的技术深度和业务价值（权重 30%）
    # 3. 技术栈与岗位要求的匹配度（权重 20%）
    # 4. 教育背景和个人优势（权重 10%）
    #
    # 决策规则:
    # - 如果综合评估匹配度 >= 70 分: 在下一个 bash 代码块前执行 SHOULD_COLLECT="yes"
    # - 如果综合评估匹配度 < 70 分: 在下一个 bash 代码块前执行 SHOULD_COLLECT="no"
    #
    # 请在执行下一个 bash 代码块之前，临时执行一个命令来设置 SHOULD_COLLECT 变量
    # 例如: SHOULD_COLLECT="yes"  # 理由: 有 3 年 LLM 应用开发经验，参与过 RAG 项目

    # ── Eval 2b: 根据 Claude 决策执行收藏或跳过 ──────────────
    : ${SHOULD_COLLECT:="no"}

    if [ "$SHOULD_COLLECT" = "yes" ]; then
      echo "  ✓ Claude 评估: 符合要求，执行收藏"
      
      COLLECT_RESULT=$(stealth-browser eval "
      (() => {
        const iframe = document.querySelector('iframe');
        const doc = iframe.contentDocument;
        const likeBtn = doc.querySelector('.like-icon-and-text');
        
        if (!likeBtn) {
          const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
          if (closeBtn) closeBtn.click();
          return JSON.stringify({status:'error', msg:'收藏按钮未找到'});
        }
        
        const iconEl = likeBtn.querySelector('.like-icon');
        const btnText = likeBtn.querySelector('.btn-text');
        const alreadyFavorited = (iconEl && iconEl.className.includes('like-icon-active')) ||
                                 (btnText && btnText.textContent.trim() === '已收藏');
        
        if (alreadyFavorited) {
          const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
          if (closeBtn) closeBtn.click();
          return JSON.stringify({status:'ok', collected:true, already_favorited:true});
        }
        
        likeBtn.click();
        
        return new Promise(resolve => {
          setTimeout(() => {
            const iconEl = likeBtn.querySelector('.like-icon');
            const btnText = likeBtn.querySelector('.btn-text');
            const collected = (iconEl && iconEl.className.includes('like-icon-active')) || 
                            (btnText && btnText.textContent.trim() === '已收藏');
            
            const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
            if (closeBtn) closeBtn.click();
            
            resolve(JSON.stringify({status:'ok', collected:collected}));
          }, 1000);
        });
      })()
      " --session boss)
      
      COLLECT_STATUS=$(echo "$COLLECT_RESULT" | jq -r '.data.result.status // "error"')
      WAS_COLLECTED=$(echo "$COLLECT_RESULT" | jq -r '.data.result.collected // false')
      
      if [ "$WAS_COLLECTED" = "true" ]; then
        COLLECTED=$((COLLECTED + 1))
        REFINED_COUNT=$((REFINED_COUNT + 1))
        echo "  ★ 已收藏 [$COLLECTED/$target]"
        COLLECTED_LIST="${COLLECTED_LIST}${COLLECTED}. ${CAND_NAME} | ${CAND_YEARS}年 | ${CAND_SCHOOL}\n"
        
        if [ -z "$NEW_IDS" ]; then
          NEW_IDS="${CAND_NAME}_${CAND_INDEX}"
        else
          NEW_IDS="${NEW_IDS},${CAND_NAME}_${CAND_INDEX}"
        fi
      fi
    else
      echo "  ✗ Claude 评估: 不符合要求，跳过收藏"
      
      stealth-browser eval "
      (() => {
        const iframe = document.querySelector('iframe');
        const doc = iframe.contentDocument;
        const closeBtn = doc.querySelector('.boss-dialog__close,[class*=\"close\"]');
        if (closeBtn) closeBtn.click();
        return 'closed';
      })()
      " --session boss > /dev/null
    fi

    unset SHOULD_COLLECT
    sleep 1
  done

  NEXT_CURSOR=$(echo "$BATCH_DATA" | jq -r '.next_cursor // 0')
  CURSOR=$NEXT_CURSOR
  unset SELECTED_INDICES
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
