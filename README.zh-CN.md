# Agent Browser

> 基于 [browser-use](https://github.com/browser-use/browser-use) 构建的反检测浏览器自动化框架。

**Note:** This is a translation of the [English README](README.md). For the latest information, please refer to the original.

## 简介

Agent Browser 为 **browser-use** 增加了工业级反检测能力、YAML 引擎、站点探索和适配器合成功能。专为遇到检测壁垒的 **browser-use 高级用户**设计。

## 核心特性

- **7 层反检测栈** — 从 C++ 指纹伪装到熔断器的完整防护
- **YAML Pipeline 引擎 v2.3** — 19 种过滤器、错误分类、自动恢复
- **站点探索模块** — 自动分析 DOM 并生成适配器
- **browser-use 原生集成** — 作为 browser-use 的反检测扩展层

## 快速开始

### 安装

```bash
# 基础版（仅第 6-7 层隐匿，使用标准 Playwright）
pip install agent-browser

# 完整反检测（全部 7 层，需要 CloakBrowser）
pip install agent-browser[cloak]

# 包含服务器模式（FastAPI + LLM 集成）
pip install agent-browser[full]
```

### 基础用法

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

async def main():
    # 创建隐匿包装的浏览器会话
    session_id = await create_session()

    # 导航到页面（自动应用隐匿延迟）
    await open_page(session_id, "https://example.com")

    # 获取页面快照（返回带 ref 的交互元素）
    data = await snapshot(session_id)
    print(f"Found {len(data['elements'])} elements")

    # 使用元素 ref 进行交互
    await click(session_id, "@e0")  # 点击第一个交互元素
    await fill(session_id, "@e1", "hello world")

asyncio.run(main())
```

## 与原生 browser-use 对比

| 功能 | browser-use | Agent Browser |
|------|------------|-------------|
| AI Agent 自动化 | 支持 | 支持（封装 browser-use） |
| 反检测 | 无 | 7 层防护栈 |
| 人类行为模拟 | 无 | 贝塞尔鼠标、逐字输入 |
| 熔断器 | 无 | Per-session 自动降级 |
| YAML Pipeline 引擎 | 无 | 19 种过滤器模板引擎 |
| 错误分类与恢复 | 无 | 6 类别类型化错误 |
| 站点探索 | 无 | DOM 分析 → 适配器生成 |

## 许可证

Apache 2.0。详见 [LICENSE](LICENSE)。
