# autoresearch — Agent Browser 自主优化

## Setup

与用户确认后:
1. 创建分支: `git checkout -b autoresearch/<tag>` (tag 基于日期，如 `apr2`)
2. 读取所有 in-scope 文件获取上下文
3. 运行基准: `python benchmark.py`，记录基线到 `results.tsv`
4. 确认 setup 完成后开始实验循环

## 优化目标

**主指标: success_rate (越高越好)**
通过 `python benchmark.py | grep success_rate` 读取。

**次要指标**: avg_steps (越低越好), avg_time_seconds (越低越好), passed_tests (越高越好)

**测试范围**: 10 个场景分类，20+ 测试用例，全部通过 skill 接口执行：
1. 会话生命周期 (create/delete/reconnect)
2. 基础导航 (百度/Bing/GitHub)
3. 搜索交互 (百度搜索 ai coding 提取前5条)
4. 数据提取 (标题/元素/结果列表)
5. 多步复合 (完整搜索+提取+整理)
6. 多标签页 (并行站点操作)
7. 远程 CDP 连接
8. 错误处理 (无效ref/不存在session/无效URL)
9. 反检测验证 (指纹检查/自动化检测)
10. 多站点覆盖 (百度/Bing/淘宝/知乎/GitHub)

## In-Scope 文件（Agent 可以修改）

### Skill 接口层 (最常修改)
- `skills/agent-browser/controller.py` — 浏览器控制器（snapshot/click/fill 实现）
- `skills/agent-browser/refs_generator.py` — 元素引用生成
- `skills/agent-browser/session_manager.py` — 会话管理
- `skills/agent-browser/SKILL.md` — Skill 声明式指令（参考 openclaw ReAct 模式）

### Agent 层
- `src/agent/runner.py` — Agent 执行逻辑、提示模板、动作注册
- `src/core/stealth_actions.py` — 隐身动作覆写
- 新增 `src/agent/prompts.py` — 提示模板（browser-use 有 9 种变体）

### 浏览器控制
- `src/core/browser_controller.py` — 原子操作实现

### 行为模拟
- `src/browser/human_behavior.py` — 类人行为模拟参数

### DOM 处理 (新增模块)
- 新增 `src/dom/service.py` — 多树合并 DOM 服务
- 新增 `src/dom/serializer.py` — LLM 友好 DOM 序列化

### Agent 增强 (新增模块)
- 新增 `src/agent/loop_detector.py` — 动作循环检测
- 新增 `src/agent/planner.py` — 任务规划系统

## Read-Only 文件（禁止修改）

- `benchmark.py` — 评估脚本（指标来源，公平性保证）
- `AUTORESEARCH.md` — 本文件（实验规则）
- `results.tsv` — 结果日志（Agent 只追加，不修改已有行）
- `src/browser/stealth_launcher.py` — 反检测栈核心（5层防护）
- `src/browser/instance_pool.py` — 浏览器实例池
- `src/session/session_manager.py` — 指纹-IP-Cookie 一致性
- `src/session/profile_manager.py` — 配置文件管理
- `src/config/manager.py` — 配置系统
- `skills/agent-browser/main.py` — Skill 入口（公共 API 接口）
- `pyproject.toml` — 项目依赖
- `requirements.txt` — 依赖锁定

## 实验

每个实验:
1. 修改一个或少量文件（原子变更）
2. `git add` + `git commit -m "experiment: <描述>"`
3. 运行: `python benchmark.py > run.log 2>&1`（重定向输出，不要刷屏上下文）
4. 读取结果: `grep "^success_rate:" run.log`
5. 改进 → 保留 commit; 退步 → `git reset --hard HEAD~1`
6. 记录到 `results.tsv`（不 commit 此文件）

## results.tsv 格式

```
commit	success_rate	avg_steps	avg_time	status	description
a1b2c3d	0.850000	12.3	5.1	baseline	初始基线
b2c3d4e	0.950000	10.1	4.8	keep	优化 DOM 序列化减少噪音
c3d4e5f	0.800000	14.5	6.2	discard	移除等待策略导致不稳定
```

字段:
- commit: 7 字符 git hash
- success_rate: 加权成功率 (0.0 - 1.0)
- avg_steps: 平均步骤数
- avg_time: 平均耗时秒
- status: baseline / keep / discard / crash
- description: 一句话描述实验内容

## 实验方向（已验证的高价值方向）

### A. Skill ReAct 模式优化（参考 openclaw skills/）
- 重写 SKILL.md 为声明式 ReAct 指令
- 新增 observe/reason_and_act/check_result 方法
- 参考 `references/openclaw/skills/gh-issues/SKILL.md` 的分阶段模式

### B. DOM 序列化优化（参考 browser-use dom/service.py）
- 当前仅用 Playwright 单一树 → browser-use 三树合并
- 参考 `references/browser-use/browser_use/dom/service.py`

### C. Agent 提示优化（参考 browser-use agent/system_prompts/）
- 当前硬编码单一提示 → 9 种变体
- 参考 `references/browser-use/browser_use/agent/system_prompts/`

### D. 行为参数调优
- 当前手工设定 → autoresearch 自动搜索最优参数
- 修改 `src/browser/human_behavior.py` 的延迟、速度、滚动参数

## 简洁性原则

等价结果下，更简单的代码更优:
- 删除代码得到相同结果 = **必须保留**
- 0.01 的 success_rate 提升如果增加 50 行复杂代码 = 可能不值得
- 优先尝试"删除 X 能否保持 success_rate"而非"添加 Y 能否提升"

## NEVER STOP

实验循环开始后**不要暂停**。不要问"要继续吗？"。自主运行直到被手动中断 (Ctrl+C)。

如果感觉陷入停滞:
- 重新读取 in-scope 文件寻找新灵感
- 参考 `references/` 目录中的 browser-use / openclaw 源码
- 尝试更激进的架构变更（不只是参数调整）
- 回到基线，换一个实验方向

你是自主研究员。你的目标是找到最简洁、最有效的代码让 benchmark.py 的 success_rate 达到 0.95+。
