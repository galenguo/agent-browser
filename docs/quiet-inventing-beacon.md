# Agent Browser - Claude Code Plugin 安装计划

## Context

用户询问 agent-browser skill 是否可以安装到 Claude Code。

**当前状态：**
- agent-browser 项目已有完整的 skill 实现（`skills/agent-browser/`）
- 包含 SKILL.md、Python 模块（controller.py、session_manager.py 等）
- 已通过测试验证核心功能正常工作

**目标：**
将 agent-browser 打包为 Claude Code plugin，使其可以通过 Claude Code 的 skill 系统调用

---

## Claude Code Plugin 系统分析（已更正）

### Plugin 目录结构

Claude Code plugins 位于：`~/.claude/plugins/marketplaces/claude-plugins-official/plugins/`

**标准 plugin 结构：**
```
plugin-name/
├── .claude-plugin/
│   └── plugin.json       # Plugin 元数据
├── skills/               # Skills 目录
│   └── skill-name/
│       ├── SKILL.md      # Skill 定义（必需）
│       ├── scripts/      # Python/TS 脚本（可选）
│       ├── references/   # 参考文档（可选）
│       └── assets/       # 资源文件（可选）
├── commands/             # 可选：命令
├── .mcp.json            # 可选：MCP 配置
└── README.md            # 文档
```

### Skill 执行机制

**重要发现：**
- ✅ Skills 可以包含 Python/TypeScript 代码
- ✅ Claude 通过 bash 工具调用这些脚本
- ✅ SKILL.md 指导 Claude 何时以及如何调用脚本
- ✅ 脚本可以是任何可执行文件（Python、Shell、Node.js 等）

**示例：skill-creator**
```bash
# SKILL.md 中指导 Claude 调用 Python 脚本
python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill"
```

---

## 当前 agent-browser Skill 状态（已更正）

**已有文件：**
- `skills/agent-browser/SKILL.md` - 完整的 skill 定义
- `skills/agent-browser/*.py` - Python 模块（controller、session_manager 等）

**SKILL.md 特点：**
- 通过 FastAPI REST API 控制远程浏览器
- 使用 bash + curl 调用 API 端点
- 支持中英文触发短语
- 包含完整工作流程

**Python 模块的作用：**
- ✅ 可以被 Claude 通过 bash 调用
- ✅ 提供本地功能（如果需要）
- ✅ 当前实现依赖远程 API，Python 模块作为备选方案

**两种使用模式：**
1. **远程 API 模式**（当前 SKILL.md 描述）
   - Claude 用 curl 调用 http://localhost:8000
   - 需要运行 FastAPI 服务

2. **本地 Python 模式**（可选）
   - Claude 直接调用 Python 脚本
   - 无需 API 服务
   - 需要安装 Python 依赖

---

## 实施方案（已更正）

### 方案：创建 Claude Code Plugin

**步骤 1：创建 plugin 目录结构**
```bash
mkdir -p ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/.claude-plugin
mkdir -p ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills/agent-browser
```

**步骤 2：复制完整的 skill 目录**
```bash
# 复制整个 skill 目录（包含 Python 模块）
cp -r /Users/galen/Library/Mobile\ Documents/com~apple~CloudDocs/skills/agent-browser/skills/agent-browser/* \
  ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills/agent-browser/
```

**步骤 3：创建 plugin.json**
```json
{
  "name": "agent-browser",
  "description": "AI-driven anti-detection browser automation platform",
  "author": {
    "name": "Agent Browser Team",
    "email": "support@example.com"
  },
  "version": "1.0.0"
}
```

**步骤 4：创建 README.md**
说明 plugin 用途、安装依赖、使用方式
---

## 前置条件（已更正）

### 选项 1：使用远程 API（推荐用于生产）

**启动 Agent Browser API 服务：**
```bash
cd agent-browser
uvicorn src.api:app --port 8000
# 或使用 Docker
docker-compose up
```

### 选项 2：使用本地 Python 模块

**安装依赖：**
```bash
cd agent-browser
pip install -r requirements.txt
playwright install chromium
```

**注意：** 当前 SKILL.md 配置为使用远程 API 模式。如需使用本地 Python 模式，需要修改 SKILL.md 指导 Claude 直接调用 Python 脚本。

---

## 安装步骤（已更正）

### 方法 1：完整复制（推荐）

```bash
# 创建目录
mkdir -p ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/.claude-plugin
mkdir -p ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills

# 复制整个 skill 目录（包含所有 Python 文件）
cp -r "/Users/galen/Library/Mobile Documents/com~apple~CloudDocs/skills/agent-browser/skills/agent-browser" \
  ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills/

# 创建 plugin.json
cat > ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/.claude-plugin/plugin.json << 'EOF'
{
  "name": "agent-browser",
  "description": "AI-driven anti-detection browser automation platform",
  "author": {
    "name": "Agent Browser",
    "email": "support@example.com"
  },
  "version": "1.0.0"
}
EOF

# 创建 README.md
cat > ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/README.md << 'EOF'
# Agent Browser Plugin

AI-driven anti-detection browser automation for Claude Code.

## Prerequisites

Start the Agent Browser API:
```bash
uvicorn src.api:app --port 8000
```

## Usage

Trigger with phrases like:
- "帮我访问网站"
- "打开浏览器"
- "Help me automate browser"
EOF
```

### 方法 2：符号链接（开发模式）

如果需要频繁更新 skill：
```bash
ln -s /path/to/agent-browser/skills/agent-browser \
  ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills/agent-browser
```

---

## 文件内容模板

### plugin.json
```json
{
  "name": "agent-browser",
  "description": "AI-driven anti-detection browser automation for web scraping and automation tasks",
  "author": {
    "name": "Agent Browser",
    "email": "support@example.com"
  },
  "version": "1.0.0"
}
```

### README.md
```markdown
# Agent Browser Plugin

AI-driven anti-detection browser automation platform for Claude Code.

## Prerequisites

Agent Browser API must be running:
- Local: `uvicorn src.api:app --port 8000`
- Docker: `docker-compose up`

## Usage

Trigger with phrases like:
- "帮我访问 xxx 网站"
- "打开浏览器"
- "扫码登录"
- "Help me automate browser tasks"

Claude will automatically use this skill for browser automation tasks.
```
---

## 验证安装

### 1. 检查 plugin 是否被识别
重启 Claude Code 后，skill 应该自动加载。

### 2. 测试触发
在 Claude Code 中输入：
- "帮我打开 Boss直聘网站"
- "Help me automate browser tasks"

Claude 应该识别并使用 agent-browser skill。

### 3. 验证 API 调用
观察 Claude 是否：
- 使用 bash + curl 调用 API
- 创建会话并获取 session_id
- 提交任务并轮询状态

---

## 关键文件路径

**需要创建的文件：**
1. `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/.claude-plugin/plugin.json`
2. `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/skills/agent-browser/SKILL.md`
3. `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/agent-browser/README.md`

**源文件位置：**
- SKILL.md: `/Users/galen/Library/Mobile Documents/com~apple~CloudDocs/skills/agent-browser/skills/agent-browser/SKILL.md`

---

## 注意事项

1. **Python 模块不会被执行**
   - Claude Code skills 是纯 Markdown 指导
   - Python 代码（controller.py 等）不需要复制到 plugin
   - 所有功能通过 FastAPI API 提供

2. **API 服务必须运行**
   - Skill 依赖 http://localhost:8000 的 API
   - 需要先启动 agent-browser 服务

3. **Skill 触发机制**
   - 基于 SKILL.md 的 description 字段
   - Claude 自动判断何时使用
   - 无需用户显式调用

---

## 总结

**可以安装：** ✅ 是的，agent-browser 可以作为 Claude Code plugin 安装

**安装方式：**
- 创建标准 plugin 目录结构
- 复制 SKILL.md 到 plugin skills 目录
- 创建 plugin.json 和 README.md
- 重启 Claude Code

**工作原理：**
- Skill 提供 Markdown 指导给 Claude
- Claude 使用 bash + curl 调用 FastAPI API
- API 服务控制远程浏览器执行任务


---

## 注意事项

1. **Python 模块可以被使用**
   - ✅ Claude 通过 bash 工具调用 Python 脚本
   - ✅ 需要在 SKILL.md 中指导如何调用
   - ✅ 当前 SKILL.md 使用 curl 调用 API，也可以改为直接调用 Python

2. **API 服务依赖**
   - 当前配置需要 FastAPI 服务运行
   - 可选：修改 SKILL.md 改为直接调用 Python 模块

3. **Skill 触发机制**
   - 基于 SKILL.md 的 description 字段
   - Claude 自动判断何时使用
   - 支持中英文触发短语

---

## 总结

**可以安装：** ✅ 是的，agent-browser 可以作为 Claude Code plugin 安装

**安装方式：**
1. 复制整个 skill 目录到 plugin 位置（包含 Python 文件）
2. 创建 plugin.json 和 README.md
3. 启动 API 服务（或修改 SKILL.md 直接调用 Python）
4. 重启 Claude Code

**工作原理：**
- SKILL.md 提供指导给 Claude
- Claude 使用 bash + curl 调用 API（当前配置）
- 或 Claude 使用 bash + python 直接调用脚本（可选）
- API/脚本控制浏览器执行任务

**优势：**
- 完整的 Python 模块可以复用
- 灵活的调用方式（API 或直接调用）
- 与现有实现完全兼容

---

## 问题澄清

### 问题 1：关于"远程 API"的理解

**澄清：** "远程 API" 是指通过 HTTP API 调用，**不是指必须部署在远程服务器**。

**部署选项：**

1. **本地 Mac mini 直接运行**（推荐个人使用）
   ```bash
   cd agent-browser
   uvicorn src.api:app --port 8000
   # API 地址：http://localhost:8000
   ```

2. **本地 Docker 运行**
   ```bash
   docker-compose up
   # API 仍然是 http://localhost:8000
   ```

3. **远程服务器部署**
   ```bash
   # 部署后修改 SKILL.md 中的 API 地址
   # http://localhost:8000 -> http://your-server:8000
   ```

**关键点：** 
- ✅ 可以在本地 Mac mini 运行 API
- ✅ 可以用 Docker 在本地运行
- ✅ 也可以部署到远程服务器
- "远程"指的是通过网络协议（HTTP）调用，不是物理位置


### 问题 2：本地 Python 模式与 browser-use 的关系

**澄清：** 本地 Python 模式**仍然依赖** browser-use 框架。

**当前架构：**
```
agent-browser/
├── src/
│   ├── api.py              # FastAPI 服务（选项1使用）
│   ├── agent/
│   │   └── runner.py       # 使用 browser-use
│   └── browser/
│       └── controller.py   # 浏览器控制
└── skills/agent-browser/
    ├── SKILL.md            # Skill 定义
    ├── controller.py       # 简化的控制器
    └── session_manager.py  # 会话管理
```

**两种模式对比：**

| 特性 | 选项1：API 模式 | 选项2：本地 Python 模式 |
|------|----------------|----------------------|
| 调用方式 | curl → FastAPI → browser-use | python → 直接调用 Python 模块 |
| browser-use | ✅ 依赖（在 src/agent/runner.py） | ✅ 依赖（如果使用 AI agent 功能） |
| 部署位置 | 本地/Docker/远程 | 本地 |
| 适用场景 | 生产、多用户 | 开发、单用户 |

**重要说明：**
- `skills/agent-browser/*.py` 是**简化版本**，主要用于基础浏览器控制
- 如果需要 AI agent 能力（browser-use），仍需使用 `src/` 下的完整实现
- 选项2可以不依赖 browser-use，但功能会受限（只有基础的 CDP 控制）


### 问题 3：Claude Code 与 OpenClaw 的兼容性

**答案：** ✅ 同一个 skill 可以同时适配 Claude Code 和 OpenClaw

**原因：**
1. **相同的 SKILL.md 格式**
   - 两者都使用 SKILL.md 作为 skill 定义
   - Frontmatter 格式相同（name、description）
   - 都通过 description 触发

2. **相同的执行机制**
   - 都通过 bash 工具调用外部命令
   - 都支持 Python/Shell 脚本
   - 都可以调用 HTTP API

3. **目录结构差异**
   - Claude Code: `~/.claude/plugins/.../skills/agent-browser/`
   - OpenClaw: `~/.openclaw/skills/agent-browser/`

**实现方式：**

**方案 1：分别安装**
```bash
# Claude Code
cp -r skills/agent-browser ~/.claude/plugins/.../skills/

# OpenClaw
cp -r skills/agent-browser ~/.openclaw/skills/
```

**方案 2：符号链接（推荐）**
```bash
# 保持一份源文件，两处链接
ln -s /path/to/agent-browser/skills/agent-browser \
  ~/.claude/plugins/.../skills/agent-browser

ln -s /path/to/agent-browser/skills/agent-browser \
  ~/.openclaw/skills/agent-browser
```

**优势：**
- ✅ 一份代码，两处使用
- ✅ 更新一次，两边同步
- ✅ 无需维护两份副本

