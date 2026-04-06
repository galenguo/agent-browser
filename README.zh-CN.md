[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/agent-browser.svg)](https://pypi.org/project/agent-browser/)
[![CI](https://github.com/galen/agent-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/galen/agent-browser/actions/workflows/ci.yml)

# Agent Browser

> 基于 [browser-use](https://github.com/browser-use/browser-use) 构建的反检测浏览器自动化框架。

Agent Browser 为 **browser-use** 增加了工业级反检测能力、YAML Pipeline 引擎、站点探索和适配器合成功能。专为遇到检测壁垒的 **browser-use 高级用户**设计。

## 核心能力

- **反检测** -- 7 层防护栈，从 C++ 指纹伪装到 AI 驱动的熔断器
- **规模化自动化** -- YAML Pipeline 引擎 v2.3，支持自动恢复、错误分类和单步调试
- **随处运行** -- CLI、REST API 或 Python 库；本地浏览器、Chrome 扩展或远程网关
- **站点探索** -- 自动 DOM 分析 + 级联 CSS 选择器生成 + YAML 适配器合成

## 快速开始

```bash
pip install agent-browser
```

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")

    data = await snapshot(session_id)
    print(f"发现 {len(data['elements'])} 个交互元素")

    await click(session_id, "@e0")       # 通过元素引用点击
    await fill(session_id, "@e1", "hello")  # 在输入框中输入文字

asyncio.run(main())
```

## 功能特性

### 反检测（7 层）

| 层 | 组件 | 作用 |
|----|------|------|
| 1 | CloakBrowser | C++ 级指纹伪装（33 项补丁） |
| 2 | patchright | 驱动级 CDP 补丁 |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复 |
| 4 | 非标准端口 19222 | 连接混淆 |
| 5 | 持久化 CDP 会话 | 防止频繁 attach/detach |
| 6 | StealthEnhancer | 类人延迟、贝塞尔鼠标曲线、逐字输入 |
| 7 | StealthMiddleware | 集中式隐匿层 + Per-session 熔断器 |

### Pipeline 引擎 v2.3

- YAML 驱动的自动化 Pipeline
- 19 种模板过滤器，支持算术表达式
- 类型化错误层级（6 个类别）
- 自动错误分类与恢复
- 单步调试器 + 断点
- JSONL 遥测执行追踪

### 多模式支持

| 模式 | 浏览器 | 智能模式 | 适用场景 |
|------|--------|---------|---------|
| CLI + local | CloakBrowser / Playwright | LLM 或 Agent | 本地开发 |
| CLI + extension | 用户 Chrome（真实指纹） | LLM 或 Agent | 生产爬取 |
| API + local | FastAPI -> 本地 CDP | LLM 或 Agent | 团队服务器 |
| API + remote | FastAPI -> Docker 网关 | LLM 或 Agent | 分布式集群 |

### 站点探索与适配器合成

- 自动 DOM 结构分析
- 级联 CSS 选择器生成
- 一键从探索结果生成 YAML 适配器

## 安装

```bash
# 基础版（仅第 6-7 层隐匿，使用标准 Playwright）
pip install agent-browser

# 完整反检测（全部 7 层，需要 CloakBrowser）
pip install agent-browser[cloak]

# 包含服务器模式（FastAPI + LLM 集成）
pip install agent-browser[full]
```

<details>
<summary>从源码安装</summary>

```bash
git clone https://github.com/galen/agent-browser.git
cd agent-browser
pip install -e ".[full]"
playwright install chromium
```

</details>

## 使用方式

### 函数式 API

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill, evaluate

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")
    data = await snapshot(session_id)

    await click(session_id, "@e0")
    await fill(session_id, "@e1", "hello world")
    title = await evaluate(session_id, "document.title")

asyncio.run(main())
```

### OOP 接口

```python
import asyncio
from agent_browser import AgentBrowser

async def main():
    async with AgentBrowser() as ab:
        await ab.create_session()
        await ab.open_page("https://example.com")
        snap = await ab.snapshot()
        await ab.click("@e0")
        result = await ab.run_task("找到搜索框并输入 'python'")
        print(result['status'])

asyncio.run(main())
```

### 服务器模式（FastAPI）

```bash
pip install agent-browser[full]
uvicorn agent_browser.api:app --port 8000
curl http://localhost:8000/health
```

**REST API 端点：**

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 服务器健康状态 + 池统计 |
| POST | `/sessions/create` | 创建会话 |
| GET | `/sessions/{id}` | 会话状态 |
| DELETE | `/sessions/{id}` | 删除会话 |
| POST | `/navigate` | 导航至 URL |
| POST | `/snapshot` | DOM 快照 |
| POST | `/click` | 按引用点击元素 |
| POST | `/fill` | 填充输入字段 |
| POST | `/evaluate` | 执行 JavaScript |
| POST | `/task` | 提交 LLM/Agent 任务 |

### Pipeline 模式

```python
from agent_browser.pipeline import PipelineExecutor

executor = PipelineExecutor(stealth_enabled=True)
result = await executor.run("adapters/my-site.yaml")
```

### 探索模式

```python
from agent_browser.explore import Explorer, Synthesizer
from agent_browser import create_session, open_page

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://target.com")

    explorer = Explorer(session_id)
    snapshot = await explorer.explore()

    # 从探索结果自动生成适配器 YAML
    adapter_yaml = Synthesizer.synthesize(snapshot)
    print(adapter_yaml)

asyncio.run(main())
```

### CLI

```bash
agent-browser --help
```

## 公共 API 参考

| 函数 | 说明 |
|------|------|
| `create_session()` | 创建浏览器会话，返回 UUID |
| `open_page(sid, url)` | 导航至 URL |
| `snapshot(sid)` | 获取 DOM 快照，含 `@eN` 元素引用 |
| `click(sid, ref)` | 按引用点击元素 (`"@e0"`) |
| `fill(sid, ref, text)` | 在输入元素中输入文本 |
| `scroll(sid, direction, amount)` | 滚动页面 |
| `select_option(sid, ref, value)` | 选择下拉选项 |
| `hover(sid, ref)` | 移动鼠标至元素中心 |
| `press_key(sid, key)` | 按下键盘按键 |
| `wait_for_selector(sel, timeout)` | 等待 CSS 选择器 |
| `go_back(sid)` | 导航后退 |
| `evaluate(sid, expr)` | 执行 JS，返回结果 |
| `run_task(sid, task, intelligence)` | LLM/Agent 自主任务 |
| `delete_session(sid)` | 释放会话资源 |
| `configure(**kwargs)` | 为下次会话更新配置 |
| `reset()` | 清除所有全局状态 |
| `setup()` | 完整首次安装验证 |

## 架构

```
agent_browser/
├── __init__.py      # 公共 API 导出 + __version__
├── main.py          # 门面 API（create_session, snapshot, click, run_task 等）
├── client.py        # AgentBrowser OOP 接口（会话跟踪，上下文管理器）
├── config.py        # SkillConfig 数据类 + 模式检测
├── browser/         # 后端 ABC + 实现（local, remote, extension）
├── stealth/         # 反检测：middleware, enhancer, actions, patches
├── pipeline/        # YAML Pipeline 引擎 v2.3
├── explore/         # 站点探索 + 适配器合成
├── adapters/        # 站点适配器加载/运行/校验
├── intelligence/    # Agent 任务执行（browser-use 集成）
├── session/         # 多用户会话管理
├── cli/             # 命令行接口（Typer）
├── llm/             # LLM 工厂（OpenAI, Anthropic, GLM）
└── utils/           # 公共工具
```

完整架构指南参见 [CLAUDE.md](CLAUDE.md)。

## 示例

参见 [`examples/`](examples/) 目录：

- [`examples/getting_started/`](examples/getting_started/) -- 基础搜索、快照探索、Agent 任务、站点示例（知乎、Bilibili、批量搜索）
- [`examples/advanced/`](examples/advanced/) -- 高级用法模式

## 与原生 browser-use 对比

| 功能 | browser-use | Agent Browser |
|------|------------|-------------|
| AI Agent 自动化 | 支持 | 支持（封装 browser-use） |
| 反检测 | 无 | 7 层防护栈 |
| 人类行为模拟 | 无 | 贝塞尔鼠标、逐字输入 |
| 熔断器 | 无 | Per-session 自动降级 |
| YAML Pipeline 引擎 | 无 | 19 种过滤器模板引擎 |
| 错误分类 | 无 | 6 类别类型化错误 |
| 自动恢复 | 无 | 按错误类别回退 |
| 站点探索 | 无 | DOM 分析 -> 适配器合成 |
| 遥测 | 无 | JSONL 执行追踪 |
| 调试器 | 无 | 单步 + 断点 |

## 依赖项

### 核心依赖（始终安装）

- `browser-use>=0.12.0` - AI 浏览器 Agent 框架
- `playwright>=1.40.0` - 浏览器自动化
- `pydantic>=2.0` - 数据校验
- `PyYAML>=6.0` - YAML 配置/Pipeline 解析
- `structlog>=24.0` - 结构化日志
- `aiohttp>=3.9.0` - 异步 HTTP 客户端

### 可选依赖

- `[cloak]` - CloakBrowser C++ 指纹 + patchright（第 1-5 层）
- `[full]` - FastAPI 服务器 + LLM 集成（langchain-openai, langchain-anthropic）

## 文档

- [架构指南](CLAUDE.md) -- 完整系统设计、模式矩阵、开发规范
- [贡献指南](CONTRIBUTING.md) -- 开发环境配置、代码风格、PR 流程
- [安全策略](SECURITY.md) -- 漏洞报告、安全最佳实践
- [部署指南](deploy/README.md) -- Docker、Kubernetes、Helm 部署
- [CHANGELOG](CHANGELOG.md) -- 版本历史

## 贡献

欢迎贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)：

- 开发环境配置
- 代码风格规范（ruff 格式化/linter）
- PR 流程
- 测试套件（868 项测试，覆盖 unit/integration/scenario/stealth/browser/skill）

## 许可证

Apache 2.0。详见 [LICENSE](LICENSE)。

## 致谢

基于以下优秀开源项目构建：

- [browser-use](https://github.com/browser-use/browser-use) -- AI 浏览器 Agent 框架（MIT）
- [Playwright](https://github.com/microsoft/playwright) -- 可靠的浏览器自动化（Apache 2.0）
- [CloakBrowser](https://github.com/nickyc975/cloakbrowser) -- C++ 反检测 Chromium（MIT）
