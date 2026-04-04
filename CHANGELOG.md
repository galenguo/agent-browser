# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- **StealthMiddleware** (`src/stealth/middleware.py`) — 集中隐匿层，自动包装所有浏览器操作
  - `StealthPageHandle` 装饰器：按操作类型自动注入 pre/post action 延迟
  - `_PerSessionCircuit` 熔断器：per-session 状态机（CLOSED→OPEN，阈值=5）
  - 操作分类：stealth-wrapped (goto/click/fill/scroll) vs passthrough (evaluate/title/url)
- **`stealth_mode` 配置** (`config.py`) — `full`(CloakBrowser+全栈) / `vanilla`(Playwright+延迟)
- **代码整合到 `src/`** — 所有核心实现从 `skills/` 迁移到 `src/`
  - `src/browser/backends/local.py` — LocalCDPBackend（唯一浏览器操作核心）
  - `src/browser/backends/remote.py` — RemoteAPIBackend（HTTP 传输层）
  - `src/browser/backends/__init__.py` — BrowserBackend + BrowserPageHandle ABC
  - `src/browser/daemon.py` — BrowserDaemon 单例
- **向后兼容 shim** — `skills/` 层旧路径仍可用，发出 DeprecationWarning 指向 `src/`
- **CloakBrowser 自动安装** (`ensure_cloakbrowser_installed()`) — 未检测到时自动 pip install
- **Pipeline 中间件集成** (`pipeline/steps.py`) — 所有步骤通过 StealthPageHandle 执行
- **基准测试脚本** (`scripts/baseline_measurements.py`) — 隐匿组件开销测量
- **单元测试** (`tests/test_stealth_middleware.py`) — 19 个测试覆盖熔断器/中间件/回归

### Changed
- `main.py` 从 286 行精简到 194 行（Phase 4 目标 <200）
  - 提取 `_ref_op()` 统一 ref 操作模式（click/fill/select_option）
  - 提取 `_get_page()` 统一页面获取入口
  - 移除手动 stealth 延迟调用（StealthMiddleware 自动处理）
- `pipeline/steps.py` 从 316 行精简到 282 行
  - 移除 `_stealth_delay()` 和所有手动隐匿调用
  - `step_click`: `locator().hover().click()` → `evaluate(JS)` with scrollIntoView
  - `step_type`: `keyboard.type()` → `evaluate(JS)` with focus + input events
  - `_get_page()` → `_get_handle()`: async, 通过 StealthMiddleware 路由

### Fixed
- **BUSession 泄漏** (ENG-8): `run_task()` 的 browser-use BrowserSession 现在在 try/finally 中正确关闭
- **JS 注入 via ref**: `ref` 验证从简单前缀检查升级为正则 `^@e\d+$`
- **JS 注入 via text**: 手动字符串转义替换为 `json.dumps()` 安全序列化
- **total_timeout 缺失**: Agent 任务现在有 `asyncio.wait_for()` 保护（默认 300s）

### Security
- 所有用户输入通过 `data-ab-ref` 属性定位（CSS 选择器注入防护）
- 文本内容通过 `json.dumps()` 转义后插入 JS（XSS 防护）
- 熔断器在连续失败后自动禁用隐匿（降级保护）

## [0.3.0] - 2026-04-04

### Added
- FastAPI REST API 服务端 (`src/api.py`)
- 多用户会话池管理 (`src/session/pool_manager.py`)
- RemoteAPIBackend HTTP 传输适配器
- YAML Pipeline 执行引擎
- 站点探索 + 适配器自动生成

## [0.2.0] - 2026-04-03

### Added
- CloakBrowser 反检测引擎集成
- StealthEnhancer 隐匿增强（贝塞尔鼠标、逐字输入、定时器噪声）
- BrowserDaemon 持久化连接单例
- browser-use Agent 模式
- LLM ReAct 模式

## [0.1.0] - 2026-04-02

### Added
- 初始版本：Playwright 浏览器自动化基础框架
- Session 管理、快照生成、原子操作 API
