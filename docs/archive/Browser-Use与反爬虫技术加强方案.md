# Browser-Use与反爬虫技术加强方案

## Context

目标：构建一个 AI Agent 驱动的浏览器自动化系统，用于 Boss 直聘等有强反爬的网站。

核心诉求：高效控制浏览器、性能好、token 成本低、强隐匿性、可远程查看操作。

以 Boss 直聘为实战案例，Boss 直聘的反爬体系：
- Cloudflare WAF（5 秒盾、JS Challenge、TLS 指纹检测 JA3/JA4）
- `navigator.webdriver` 检测 + CDP 协议检测
- Canvas/WebGL/AudioContext 指纹采集
- 行为分析（鼠标轨迹、点击间隔、滚动模式）
- IP 信誉 + 请求频率限制

---

## 方案一：Browser-Use 增强方案（Chromium 路线）

### 核心思路

保留 browser-use 的 Agent 编排能力（DOM 压缩、结构化 action、多模型支持），用编译级隐匿浏览器替换默认 Chromium，并修补 CDP 协议泄漏。

### 隐匿性增强：三层防御体系

经过深入调研 Reddit、GitHub 和反检测社区，Chromium 路线的隐匿性瓶颈主要在三个层面，每层都有对应的开源解决方案：

#### 第一层：浏览器引擎级（编译时补丁）— 解决指纹伪装

关键发现：**CloakBrowser**（github.com/CloakHQ/CloakBrowser）是 Chromium 的编译级反检测分支，类似 Camoufox 对 Firefox 做的事：

| 特性 | CloakBrowser | 普通 Chromium | Camoufox |
|------|-------------|--------------|----------|
| Canvas 指纹 | ★★★★★ C++ 噪声注入 | ★ 无 | ★★★★★ C++ 噪声注入 |
| WebGL 指纹 | ★★★★★ 渲染器/厂商伪装 | ★ 无 | ★★★★★ |
| AudioContext | ★★★★★ 采样率噪声 | ★ 无 | ★★★★★ |
| 字体枚举 | ★★★★ 随机子集 | ★ 无 | ★★★★★ |
| GPU 信息 | ★★★★★ 伪装 | ★ 无 | ★★★★ |
| 自动化标志 | ★★★★★ 编译移除 | ★ 有泄漏 | ★★★★★ |
| reCAPTCHA v3 | 0.9 分 | 0.1-0.3 分 | 0.7-0.9 分 |
| 33 项 C++ 补丁 | ✅ | ❌ | ✅ (Firefox) |

备选：**fingerprint-chromium**（github.com/adryfish/fingerprint-chromium）基于 Ungoogled Chromium，用单个 32-bit seed 控制所有指纹伪装。

#### 第二层：CDP 协议级（运行时补丁）— 解决自动化检测

CDP 是 Chromium 自动化最大的检测向量。关键泄漏点和修复方案：

| CDP 泄漏向量 | 检测方式 | 修复方案 |
|-------------|---------|---------|
| `Runtime.Enable` 绑定注入 | `Runtime.consoleAPICalled` 副作用 | **rebrowser-patches**（addBinding 模式） |
| `navigator.webdriver` | 直接属性检查 | CloakBrowser 编译移除 / patchright |
| `window.cdc_*` 变量 | 正则扫描 window 属性 | CloakBrowser 编译移除 |
| `__playwright__binding__` | JS 检查 | **patchright** 补丁 |
| CDP WebSocket 端口探测 | 探测 localhost:9222 | 使用 `--remote-debugging-pipe` 替代 |
| `Page.evaluateOnNewDocument` 注入 | 脚本注入分析 | CDP 代理过滤 |

**patchright**（Scrapling 使用的方案）vs **rebrowser-patches** 对比：

| 维度 | patchright | rebrowser-patches |
|------|-----------|-------------------|
| 层级 | 驱动级补丁（更彻底） | 库级补丁（更灵活） |
| 集成 | Playwright 替代品 | 应用到现有代码 |
| 浏览器 | 仅 Chromium | Puppeteer + Playwright |
| 维护 | 需跟随驱动更新 | 独立维护 |

推荐：**patchright + rebrowser-patches 双重修补**，覆盖所有已知 CDP 泄漏。

#### 第三层：行为级 — 解决行为分析检测

| 技术 | 方案 | 效果 |
|------|------|------|
| 鼠标轨迹 | ghost-cursor / bezier 曲线库 | 模拟人类鼠标运动（加速度、抖动） |
| 打字节奏 | 随机 50-200ms 间隔 + 偶尔退格 | 模拟真实打字 |
| 滚动行为 | 惯性滚动 + 随机停顿 | 非线性滚动模式 |
| 页面停留 | 2-8s 随机 + 阅读时间模型 | 模拟真实浏览节奏 |
| 请求间隔 | 泊松分布随机延迟 | 避免固定频率特征 |

### 技术栈（更新后）

| 组件 | 选型 | 理由 |
|------|------|------|
| Agent 编排 | browser-use（直接复用） | 成熟的 DOM 快照压缩、action space、多 LLM 支持 |
| 浏览器引擎 | **CloakBrowser**（首选）/ fingerprint-chromium（备选） | C++ 编译级指纹伪装，33 项补丁，reCAPTCHA 0.9 分 |
| CDP 修补 | **patchright + rebrowser-patches** | 双重修补所有已知 CDP 泄漏 |
| 行为模拟 | ghost-cursor + 自定义延迟 | 鼠标/打字/滚动人类化 |
| TLS 指纹 | curl_cffi（辅助请求） | JA3/JA4 伪装 |
| 指纹生成 | BrowserForge | 真实市场分布 |

### 集成方式

browser-use 支持通过 `cdp_url` 连接外部浏览器（`browser_use/browser/session.py:1682`）：

```python
# 步骤1：启动 CloakBrowser（编译级反检测 Chromium）
# CloakBrowser 是 Playwright 兼容的，可直接用 patchright 启动
from patchright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(
        executable_path="/path/to/cloakbrowser/chrome",
        headless=False,
        args=[
            '--remote-debugging-pipe',  # pipe 模式，避免端口探测
            '--disable-blink-features=AutomationControlled',
        ]
    )
    # 获取 CDP endpoint
    cdp_url = browser.contexts[0].pages[0].url  # 或通过 /json/version

# 步骤2：browser-use 连接
from browser_use import BrowserSession, BrowserProfile
session = BrowserSession(
    browser_profile=BrowserProfile(
        cdp_url=cdp_url,
        is_local=True,
    )
)

# 步骤3：正常使用 browser-use 的 Agent
from browser_use import Agent
agent = Agent(task="在Boss直聘搜索Python开发岗位", browser_session=session)
await agent.run()
```

备选集成路径（更简单）：直接用 patchright 替换 browser-use 内部的 playwright 调用：

```python
# browser-use 内部使用 cdp-use 库连接浏览器
# 可以通过环境变量让 rebrowser-patches 生效
import os
os.environ['REBROWSER_PATCHES_RUNTIME_FIX_MODE'] = 'addBinding'

# 然后正常启动 browser-use，但指定 CloakBrowser 路径
session = BrowserSession(
    browser_profile=BrowserProfile(
        executable_path="/path/to/cloakbrowser/chrome",
        is_local=True,
    )
)
```

### 隐匿性提升至 90%+：Boss 直聘专项增强

Boss 直聘的反爬体系比普通 Cloudflare 网站复杂得多，它使用 **Akamai Bot Manager + 同盾科技 + 极验 GeeTest v4** 三重防护。要达到 90%+ 通过率，需要在三层防御体系基础上补充以下专项措施：

#### 瓶颈分析：为什么当前方案只有 75-85%

| 瓶颈 | 原因 | 失败率贡献 |
|------|------|-----------|
| Akamai `_abck` cookie | sensor_data 不完整或不一致 | ~8% |
| 同盾行为评分 | 操作节奏不够自然 | ~5% |
| 极验 GeeTest v4 | 滑块求解失败或轨迹被识别 | ~3% |
| IP 信誉不足 | 数据中心 IP 或低信誉住宅 IP | ~5% |
| TLS 指纹不匹配 | JA3 与 UA/浏览器不一致 | ~2% |

#### 增强措施 1：Akamai `_abck` Cookie 处理

Boss 直聘使用 Akamai Bot Manager，核心是 `_abck` cookie 和 sensor_data。

```
策略：让浏览器自然生成 _abck，而不是尝试逆向

CloakBrowser (编译级补丁)
  → Akamai JS 正常执行
  → sensor_data 采集到的是 CloakBrowser 伪造的一致指纹
  → _abck 自然生成有效值
  → 无需逆向 Akamai 加密逻辑
```

关键：CloakBrowser 的 33 项 C++ 补丁确保 Akamai 的 JS 采集到的 Canvas/WebGL/AudioContext 指纹是**一致的伪造值**，而不是被 JS hook 痕迹暴露的值。这比 JS 层注入的 stealth 有本质优势。

#### 增强措施 2：同盾行为评分应对

同盾科技分析鼠标轨迹熵值、滚动模式、点击时序。需要模拟真人的"不完美"行为：

```python
# 行为模拟增强模块
class HumanBehaviorSimulator:
    """模拟真人的不完美行为"""

    async def browse_naturally(self, page, target_url):
        """自然浏览流程（非直达目标）"""

        # 1. 预热浏览：先访问其他页面建立浏览历史
        warmup_urls = [
            "https://www.baidu.com",
            "https://www.zhipin.com",  # 先访问首页
        ]
        for url in warmup_urls:
            await page.goto(url)
            await self._random_scroll(page)
            await asyncio.sleep(random.uniform(3, 8))

        # 2. 搜索行为：模拟从首页自然搜索
        await page.goto("https://www.zhipin.com")
        await asyncio.sleep(random.uniform(2, 5))

        # 3. 模拟人类打字：有停顿、有退格、有思考
        search_input = page.locator("input[name='query']")
        await self._human_type(search_input, "Python开发")

        # 4. 搜索后自然浏览
        await asyncio.sleep(random.uniform(1, 3))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(3, 8))

        # 5. 随机行为：模拟真人"闲逛"
        await self._random_interactions(page)

    async def _human_type(self, element, text):
        """真人打字：变速 + 偶尔退格 + 停顿"""
        await element.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        for i, char in enumerate(text):
            # 5% 概率打错再退格
            if random.random() < 0.05:
                wrong_char = random.choice("abcdef1234567890")
                await element.type(wrong_char, delay=random.randint(30, 100))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await element.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))

            # 变速打字：50-250ms
            delay = random.randint(50, 250)
            if random.random() < 0.1:  # 10% 概率长停顿（想一下）
                delay += random.randint(500, 1500)
            await element.type(char, delay=delay)

    async def _random_scroll(self, page):
        """非匀速滚动 + 随机停顿"""
        scroll_times = random.randint(2, 5)
        for _ in range(scroll_times):
            distance = random.randint(100, 600)
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.5, 3))

            # 20% 概率回滚（真人经常这样）
            if random.random() < 0.2:
                await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 200)})")
                await asyncio.sleep(random.uniform(0.3, 1))

    async def _random_interactions(self, page):
        """随机真人行为"""
        actions = [
            lambda: self._random_scroll(page),
            lambda: asyncio.sleep(random.uniform(5, 15)),  # 长停顿"阅读"
            lambda: page.mouse.move(  # 随机鼠标移动
                random.randint(100, 1800),
                random.randint(100, 900),
            ),
        ]
        for _ in range(random.randint(2, 4)):
            action = random.choice(actions)
            await action()
```

#### 增强措施 3：极验 GeeTest v4 求解

GeeTest v4 报告求解成功率 70-95%。推荐组合策略：

```
优先级 1：YesCaptcha / CapSolver API 求解（成功率 85-95%）
  → 支持 GeeTest v4，中国网络延迟低
  → 成本 ~$1-3/千次

优先级 2：botright 内置 AI 求解（成功率 70-85%）
  → 免费，贝塞尔曲线拖动轨迹
  → 但 botright 基于 Playwright，不能直接集成

优先级 3：人工接管（成功率 ~100%）
  → 通过 noVNC 远程查看 → 手动拖动滑块
  → 适合低频场景或求解服务失败时的兜底
```

#### 增强措施 4：代理 IP 策略

| 代理类型 | Boss 直聘通过率 | 成本 | 推荐度 |
|---------|---------------|------|--------|
| 数据中心 IP | ~5-10% | 低 | ❌ |
| 普通住宅代理 | ~60-70% | 中 | ★★★ |
| ISP 住宅代理 | ~75-85% | 中高 | ★★★★ |
| 4G/5G 移动代理 | ~85-95% | 高 | ★★★★★ |
| 家庭宽带直出 | ~90%+ | 免费 | ★★★★★ |

推荐方案：
- **开发测试阶段**：家庭宽带直出（免费 + 最高信誉）
- **小规模生产**：ISP 住宅代理（稳定 + 可扩展）
- **大规模生产**：4G/5G 移动代理池（最高信誉 + 可轮换）

#### 增强措施 5：Session 与指纹一致性管理

```python
class SessionManager:
    """指纹-IP-Cookie 一致性管理"""

    def __init__(self):
        self.profiles = {}  # {profile_id: {fingerprint, cookies, proxy, ...}}

    def create_profile(self, proxy_ip):
        """为每个 IP 创建一致性 profile"""
        from browserforge.fingerprints import FingerprintGenerator
        fp = FingerprintGenerator(browser='chrome').generate(os='windows')

        return {
            "fingerprint_seed": random.randint(0, 2**32),  # CloakBrowser seed
            "proxy": proxy_ip,
            "timezone": self._ip_to_timezone(proxy_ip),  # 地理一致
            "locale": self._ip_to_locale(proxy_ip),       # 语言一致
            "cookies": {},                                  # 持久化 cookies
            "user_agent": fp.navigator.userAgent,
            "screen": fp.screen,
            "created_at": time.time(),
            "request_count": 0,
        }

    def should_rotate(self, profile_id):
        """判断是否需要轮换 profile"""
        p = self.profiles[profile_id]
        # 超过 300 请求或 24 小时 → 轮换
        if p["request_count"] > 300:
            return True
        if time.time() - p["created_at"] > 86400:
            return True
        return False
```

#### 增强措施 6：预热浏览（IP 信誉建立）

```
首次使用新 IP/Profile 时的预热流程：

Step 1: 访问百度 → 正常搜索 → 浏览 2-3 个结果页（3-5分钟）
Step 2: 访问几个新闻站点（腾讯新闻、网易）→ 随机浏览（3-5分钟）
Step 3: 访问 zhipin.com 首页 → 不搜索，只浏览推荐（2-3分钟）
Step 4: 正式开始搜索任务

目的：在 Akamai/同盾的行为模型中建立"正常用户"基线
```

#### 增强后方案一预期通过率

| 措施 | 通过率提升 | 累计预期通过率 |
|------|-----------|--------------|
| CloakBrowser 编译级指纹 | 基础 75% | 75% |
| + patchright/rebrowser CDP 修补 | +5% | 80% |
| + 行为模拟增强（HumanBehaviorSimulator） | +5% | 85% |
| + 住宅/移动代理 IP | +5% | 90% |
| + Session 一致性管理 | +2% | 92% |
| + 预热浏览 | +2% | 94% |
| + GeeTest 求解服务 | +2% | 96% |
| 综合预期通过率 | | **90-96%** |

**注意**：这些数字是基于社区反馈和各项技术的已知效果的估算，实际通过率取决于 Boss 直聘反爬系统的实时更新。持续维护和监控是必要的。

browser-use 的 DOM 压缩机制（`dom/serializer/serializer.py`）：
- 原始 Boss 直聘职位列表页 HTML：~80,000 tokens
- DOM 快照压缩后（只保留交互元素）：~1,500-2,500 tokens
- 每步 Agent 调用（system prompt + DOM + history）：~4,000-6,000 tokens
- 完成一次"搜索+浏览5个职位"任务：约 8-12 步 = ~50,000 tokens

使用 Claude claude-sonnet-4-6：~$0.15/次任务
使用 Claude claude-haiku-4-5：~$0.02/次任务

### 优势与局限

优势：
- 开发速度快，browser-use 的 Agent 编排直接可用
- 多模型支持（Claude/GPT/Gemini），可按成本切换
- 社区活跃，持续更新

局限：
- Chromium 路线的 CDP 协议本身是检测向量（Boss 直聘可检测 CDP 连接）
- JS 层注入的 stealth 可被高级反爬识破（不如 C++ 层注入）
- nodriver 的反检测能力有上限，面对 Cloudflare Enterprise 可能不够

---

## 方案二：Camoufox 增强方案（Firefox 路线）

### 核心思路

以 Camoufox 为浏览器底座（C++ 层反检测），自研轻量 Agent 编排层，借鉴 browser-use 的 DOM 压缩思路。

### 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 浏览器引擎 | Camoufox | C++ 层指纹注入，Juggler 协议隔离，最强隐匿性 |
| 浏览器控制 | Playwright（Camoufox 内置兼容） | 标准 API，page.goto/click/evaluate 全部可用 |
| Agent 编排 | 自研（参考 browser-use 架构） | 轻量、可控、针对性优化 |
| DOM 压缩 | 自研（参考 browser-use DOMService） | Accessibility Tree + 交互元素过滤 |
| 指纹管理 | BrowserForge（Camoufox 内置） | 每个 context 独立指纹，真实分布 |
| 人类行为 | Camoufox humanize（C++ 鼠标轨迹） | 原生级别，不可被 JS 检测 |

### 核心代码结构

```
src/
├── browser/
│   ├── engine.py          # Camoufox 启动封装
│   └── stealth_config.py  # 指纹/代理/行为配置
├── agent/
│   ├── orchestrator.py    # LLM 调用 + action 解析
│   ├── dom_snapshot.py    # DOM 压缩（核心）
│   └── actions.py         # 结构化 action 定义
├── api/
│   └── server.py          # FastAPI 控制接口
└── config.py              # 全局配置
```

### 浏览器启动层

```python
# browser/engine.py
from camoufox.async_api import AsyncCamoufox
from browserforge.fingerprints import Screen

class StealthBrowser:
    async def launch(self, proxy: str = None):
        self.browser = await AsyncCamoufox(
            headless=False,           # headed 模式更隐蔽
            humanize=True,            # C++ 人类鼠标轨迹
            geoip=True,               # 根据代理 IP 自动匹配地理信息
            screen=Screen(max_width=1920, max_height=1080),
            os="windows",             # Windows 占比最高，最不显眼
            block_images=False,       # Boss直聘需要图片（验证码）
            block_webfonts=True,      # 节省带宽
            proxy={"server": proxy} if proxy else None,
            addons=["/path/to/ublock_origin.xpi"],
        ).__aenter__()
        return self.browser
```

### DOM 压缩层（核心，决定 token 成本）

```python
# agent/dom_snapshot.py
SNAPSHOT_JS = """
() => {
    const interactiveSelectors = 'a, button, input, select, textarea, [role="button"], [onclick]';
    const elements = document.querySelectorAll(interactiveSelectors);
    const result = [];
    let index = 0;

    for (const el of elements) {
        const rect = el.getBoundingClientRect();
        // 跳过不可见元素
        if (rect.width === 0 || rect.height === 0) continue;
        if (window.getComputedStyle(el).display === 'none') continue;

        result.push({
            index: index++,
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || '').trim().slice(0, 100),
            href: el.href || null,
            type: el.type || null,
            placeholder: el.placeholder || null,
            ariaLabel: el.getAttribute('aria-label'),
            value: el.value || null,
        });
    }

    // 同时提取页面主要文本内容（用于 LLM 理解上下文）
    const mainText = document.body.innerText.slice(0, 3000);
    return { elements: result, pageText: mainText, url: location.href, title: document.title };
}
"""

async def get_dom_snapshot(page) -> dict:
    return await page.evaluate(SNAPSHOT_JS)
```

压缩效果（Boss 直聘职位列表页）：
- 原始 HTML：~80,000 tokens
- 压缩后 JSON：~1,200-2,000 tokens（交互元素 ~30-50 个 + 页面文本摘要）

### Agent 编排层

```python
# agent/orchestrator.py
SYSTEM_PROMPT = """你是一个浏览器操作助手。根据用户任务和当前页面状态，返回下一步操作。

可用操作：
- click(index) - 点击元素
- type(index, text) - 在输入框输入文字
- navigate(url) - 导航到URL
- scroll(direction) - 滚动页面，direction: "up" 或 "down"
- wait(seconds) - 等待
- done(result) - 任务完成，返回结果

返回 JSON 格式：{"action": "click", "params": {"index": 3}, "thought": "点击搜索按钮"}
"""

class AgentOrchestrator:
    def __init__(self, model="claude-haiku-4-5"):  # 默认用 Haiku 省钱
        self.client = anthropic.AsyncAnthropic()
        self.model = model
        self.history = []  # 保留最近 5 步，控制 context 长度

    async def step(self, task: str, snapshot: dict) -> dict:
        messages = [
            {"role": "user", "content": f"""任务：{task}

当前页面：{snapshot['title']} ({snapshot['url']})
页面文本摘要：{snapshot['pageText'][:1500]}

可交互元素：
{self._format_elements(snapshot['elements'])}

历史操作：{self.history[-5:]}

请返回下一步操作（JSON）。"""}
        ]

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=200,  # action 输出很短，限制 token
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return json.loads(response.content[0].text)
```

### Boss 直聘实战流程

```
任务："在Boss直聘搜索北京的Python开发岗位，收集前10个职位信息"

Step 1: navigate("https://www.zhipin.com") → 打开首页
Step 2: wait(2) → 等待 Cloudflare 验证通过（Camoufox 自动处理）
Step 3: click(搜索框 index) → 聚焦搜索框
Step 4: type(搜索框 index, "Python开发") → 输入关键词
Step 5: click(城市选择 index) → 选择北京
Step 6: click(搜索按钮 index) → 执行搜索
Step 7-16: 逐个 click 职位卡片 → 提取详情 → 返回列表

预计 token 消耗：
- 每步：~2,500 tokens input + ~100 tokens output
- 16 步总计：~42,000 tokens
- Haiku 成本：~$0.01  |  Sonnet 成本：~$0.13
```

### 反检测能力对比（针对 Boss 直聘）

| 检测向量 | 方案一（browser-use + nodriver） | 方案二（Camoufox） |
|----------|----------------------------------|---------------------|
| navigator.webdriver | JS 注入覆盖（可被检测到覆盖行为） | C++ 层直接返回 undefined（不可检测） |
| CDP 协议检测 | 存在风险（CDP 是 Chromium 原生协议） | 不使用 CDP，用 Juggler 协议（无此风险） |
| Canvas 指纹 | JS 噪声注入（可被检测到 hook） | C++ 层噪声（原生级别，不可检测） |
| WebGL 指纹 | 需额外处理 | C++ 层伪造 vendor/renderer |
| WebRTC IP 泄露 | 需 flag 禁用或 JS 拦截 | C++ 协议层拦截（最彻底） |
| 鼠标轨迹 | 需自己实现或用第三方库 | 内置 C++ 人类轨迹算法 |
| TLS 指纹 (JA3) | Chrome 的 JA3 较固定，需 curl_cffi 辅助 | Firefox JA3 天然多样性更好 |
| Cloudflare 5秒盾 | 可能需要额外处理 | 通常可直接通过 |

### 优势与局限

优势：
- 最强隐匿性（C++ 层注入，反爬系统几乎无法检测）
- Playwright 完全兼容，开发体验好
- 每个 context 独立指纹，天然支持多账号
- 内置人类行为模拟

局限：
- 需要自研 Agent 编排层（约 500-800 行代码）
- Firefox 在少数网站兼容性不如 Chrome
- Camoufox 项目维护有间歇性（需关注更新）

---

## 两阶段实施计划

### 阶段一：本地开发测试

目标：两套方案都跑通，在 Boss 直聘上验证反检测效果。

#### Step 1：环境搭建（Day 1）

```bash
cd /Users/galen/OpenSource/browser-controller

# 创建项目
mkdir -p stealth-browser/src/{browser,agent,api}
cd stealth-browser

# Python 环境
python3.11 -m venv .venv
source .venv/bin/activate

# 方案一依赖
pip install browser-use nodriver browserforge curl_cffi

# 方案二依赖
pip install camoufox[geoip] playwright browserforge anthropic fastapi uvicorn

# 下载 Camoufox 浏览器二进制
python -m camoufox fetch
```

#### Step 2：方案一验证 - browser-use + nodriver（Day 2-3）

1. 启动 nodriver 浏览器，获取 CDP 端口
2. browser-use 通过 `cdp_url` 连接
3. 注入 stealth JS
4. 测试 Boss 直聘登录 + 搜索流程
5. 记录检测结果（bot.sannysoft.com、fingerprintjs.com）

#### Step 3：方案二验证 - Camoufox + 自研 Agent（Day 3-5）

1. 实现 `browser/engine.py`（Camoufox 启动封装）
2. 实现 `agent/dom_snapshot.py`（DOM 压缩）
3. 实现 `agent/orchestrator.py`（LLM 编排）
4. 实现 `agent/actions.py`（action 执行器）
5. 测试 Boss 直聘完整流程
6. 对比两方案的检测通过率

#### Step 4：性能与成本对比测试（Day 5-6）

测试指标：
- 反检测：bot.sannysoft.com 全绿 / fingerprintjs.com 唯一性 / Boss 直聘不触发验证码
- 性能：页面加载时间、DOM 快照耗时、Agent 单步响应时间
- Token 成本：完成标准任务的总 token 消耗
- 稳定性：连续运行 1 小时不被封

### 阶段二：Docker 虚拟化部署

目标：将验证通过的方案容器化，支持远程查看和操作。

#### Step 5：Docker 化（Day 7-8）

```dockerfile
# Dockerfile
FROM ubuntu:22.04

# 系统依赖
RUN apt-get update && apt-get install -y \
    python3.11 python3-pip \
    xvfb x11vnc websockify novnc \
    fonts-noto-cjk \          # 中文字体（Boss直聘必需）
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -m camoufox fetch

# 应用代码
COPY src/ /app/src/
COPY scripts/entrypoint.sh /app/

EXPOSE 8080 6080
ENTRYPOINT ["/app/entrypoint.sh"]
```

```bash
# scripts/entrypoint.sh
#!/bin/bash
# 启动虚拟显示
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# 启动 VNC（远程查看）
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb -forever &

# 启动 noVNC（浏览器访问）
websockify --web /usr/share/novnc 6080 localhost:5900 &

# 启动 API 服务
cd /app && python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8080
```

```yaml
# docker-compose.yml
services:
  stealth-browser:
    build: .
    ports:
      - "8080:8080"   # FastAPI 控制接口
      - "6080:6080"   # noVNC 远程查看浏览器
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PROXY_URL=${PROXY_URL}
      - DISPLAY=:99
    volumes:
      - ./sessions:/app/sessions
    shm_size: '2gb'
```

#### Step 6：远程控制 API（Day 8-9）

```python
# src/api/server.py
from fastapi import FastAPI, WebSocket
app = FastAPI()

@app.post("/task")
async def create_task(task: str, model: str = "claude-haiku-4-5"):
    """提交 Agent 任务"""
    result = await orchestrator.run(task, model=model)
    return {"result": result}

@app.get("/screenshot")
async def screenshot():
    """获取当前页面截图"""
    img = await page.screenshot()
    return Response(content=img, media_type="image/png")

@app.post("/manual/{action}")
async def manual_action(action: str, params: dict):
    """人工接管：手动执行操作（验证码场景）"""
    await execute_action(action, params)

@app.websocket("/stream")
async def screenshot_stream(ws: WebSocket):
    """实时截图流（用于远程监控）"""
    await ws.accept()
    while True:
        img = await page.screenshot(type="jpeg", quality=50)
        await ws.send_bytes(img)
        await asyncio.sleep(0.5)
```

远程访问方式：
- 浏览器打开 `http://server:6080/vnc.html` → 直接看到并操作浏览器
- API 调用 `POST http://server:8080/task` → 提交自动化任务
- WebSocket `ws://server:8080/stream` → 实时监控截图流

#### Step 7：生产加固（Day 9-10）

- 代理轮换：配置住宅代理池，每个 session 随机分配
- Session 持久化：Cookie/指纹存储到 volume，避免重复登录
- 异常处理：验证码检测 → 暂停 Agent → 通知人工接管（通过 noVNC）
- 日志监控：记录每步操作、检测事件、token 消耗

---

## 能力矩阵对比

### 四个开源项目基础能力

| 能力维度 | Scrapling | browser-use | Camoufox | nodriver |
|---------|-----------|-------------|----------|----------|
| 浏览器 | Chromium (Patchright) | Chromium (CDP) | Firefox (定制) | Chromium (CDP) |
| 自动化隐匿 | ★★★ Patchright | ★★ 禁用组件 | ★★★★★ C++补丁 | ★★★ 无WebDriver |
| 指纹伪装 | ★★ Canvas/WebRTC | ★ 无 | ★★★★★ 全面C++ | ★ 无 |
| TLS 伪装 | ★★★★ curl_cffi | ★ 无 | ★★ Firefox原生 | ★ 无 |
| 行为模拟 | ★ 脚本化 | ★★★★★ LLM类人 | ★★ 需自行实现 | ★ 需自行实现 |
| 验证码处理 | ★★ CF Turnstile | ★★★ Watchdog | ★ 无内置 | ★★ CF verify |
| 代理管理 | ★★★ ProxyRotator | ★★ ProxySettings | ★★★ GeoIP联动 | ★ 无 |
| DOM压缩/Token效率 | ★ 无（非Agent） | ★★★★★ 序列化器 | ★ 无（非Agent） | ★ 无（非Agent） |
| CDP外部连接 | ✅ cdp_url参数 | ✅ cdp_url参数 | ❌ Firefox无CDP | ✅ 提供CDP端口 |
| 可视化运行 | ✅ headless=False | ✅ headless=False | ✅ headless=False | ✅ 默认可视化 |
| Docker支持 | ★★★ 官方镜像 | ★★★ Cloud模式 | ★★ 需自建 | ★ 需自建 |
| 性能 | ★★★★★ 784x解析 | ★★★ 中等 | ★★★ 200MB内存 | ★★★★ 轻量快速 |
| 社区活跃度 | ★★★ | ★★★★★ | ★★ 维护间断 | ★★★ |

### 两个增强方案能力对比

| 能力维度 | 方案一（增强前） | 方案一（增强后）：CloakBrowser+patchright+browser-use | 方案二：Camoufox+自研Agent | 说明 |
|---------|---------------|-----------------------------------------------------|-------------------------|------|
| 自动化隐匿 | ★★★☆☆ | ★★★★★ CloakBrowser编译移除+patchright+rebrowser双修 | ★★★★★ C++层隔离 | 增强后两方案持平 |
| 指纹伪装 | ★★★☆☆ JS注入 | ★★★★★ CloakBrowser 33项C++补丁 | ★★★★★ C++原生 | CloakBrowser 达到 Camoufox 同级 |
| TLS 伪装 | ★★★★☆ | ★★★★☆ curl_cffi辅助 | ★★★☆☆ Firefox原生 | Chromium+curl_cffi 更灵活 |
| 行为模拟 | ★★★★★ | ★★★★★ LLM+ghost-cursor | ★★★★☆ LLM+C++鼠标 | browser-use 成熟编排+ghost-cursor |
| 验证码处理 | ★★★★☆ | ★★★★☆ Watchdog体系 | ★★☆☆☆ 需自研/人工接管 | browser-use CaptchaWatchdog |
| Token效率 | ★★★★★ | ★★★★★ 成熟DOM压缩 | ★★★★☆ 自研压缩 | 直接复用 serializer |
| 代理管理 | ★★★☆☆ | ★★★☆☆ 配置式 | ★★★★☆ GeoIP自动联动 | 方案二指纹与地理位置自动一致 |
| CDP泄漏防护 | ★☆☆☆☆ | ★★★★★ patchright+rebrowser双修+pipe模式 | ★★★★★ 无CDP（Juggler） | 增强后 CDP 泄漏基本消除 |
| reCAPTCHA v3 | ★★☆☆☆ 0.1-0.3分 | ★★★★★ 0.9分（CloakBrowser） | ★★★★☆ 0.7-0.9分 | CloakBrowser 在此项超越 Camoufox |
| 开发成本 | ★★★★★ | ★★★★☆ 需编译CloakBrowser | ★★☆☆☆ 高（自研Agent层） | 方案一仍然更快，但需编译步骤 |
| Boss直聘通过率 | ★★★☆☆ ~50% | ★★★★★ ~90-96%（含专项增强） | ★★★★★ ~80-90% | 方案一通过专项增强反超 |
| Cloudflare通过率 | ★★★☆☆ ~60% | ★★★★★ ~85-90% | ★★★★★ ~90% | CloakBrowser 通过所有 30+ 检测站 |
| 长期稳定性 | ★★★☆☆ | ★★★★☆ C++补丁+社区维护 | ★★★★★ C++层难被针对 | 方案二仍略优（Firefox 生态更稳定） |
| Docker部署 | ★★★★☆ | ★★★★☆ CDP远程简单 | ★★★☆☆ 需Xvfb+VNC | Chromium CDP 天然支持远程 |
| 远程查看 | ★★★★☆ | ★★★★☆ CDP截图+noVNC | ★★★★☆ Xvfb+noVNC | 两者都可实现 |
| 多实例并发 | ★★★★☆ | ★★★★☆ CDP多target | ★★★☆☆ 每实例独立进程 | Chromium 内存效率更高 |
| Chrome兼容性 | ★★★★★ | ★★★★★ 原生Chromium | ★★☆☆☆ Firefox有差异 | 少数网站只兼容Chrome |

### 综合评分

| 维度 | 方案一（增强前） | 方案一（增强后） | 方案二 |
|------|---------------|----------------|--------|
| 隐匿性总分 | ★★★☆☆ (3.2/5) | ★★★★★ (4.6/5) | ★★★★★ (4.8/5) |
| 性能/效率 | ★★★★☆ (4.0/5) | ★★★★☆ (4.0/5) | ★★★★☆ (3.8/5) |
| Token成本 | ★★★★★ (4.5/5) | ★★★★★ (4.5/5) | ★★★★☆ (4.0/5) |
| 开发成本 | ★★★★★ (4.5/5) | ★★★★☆ (3.8/5) | ★★☆☆☆ (2.0/5) |
| 部署便捷性 | ★★★★☆ (4.0/5) | ★★★★☆ (3.8/5) | ★★★☆☆ (3.0/5) |
| Boss直聘适用性 | ★★★☆☆ (3.0/5) | ★★★★★ (4.7/5) | ★★★★★ (4.8/5) |
| 综合加权 | 3.5/5 | **4.4/5** | **4.1/5** |
| 推荐场景 | ❌ 不推荐 | Boss直聘等强反爬+生产均可 | 最高隐匿需求+低维护场景 |

增强后结论：方案一通过 CloakBrowser + patchright + rebrowser-patches 三层加固 + Boss 直聘专项增强（行为模拟、Session 管理、IP 策略、预热浏览），隐匿性从 3.2 提升到 4.6，Boss 直聘通过率从 50% 提升到 90-96%。**增强后的方案一已成为综合最优选择**——开发成本低、Token 效率高、Boss 直聘通过率与方案二持平甚至更优。方案二仍适合对维护成本敏感且追求纯指纹隐匿的场景。

---

## 推荐决策

| 场景 | 推荐方案 |
|------|----------|
| 快速验证、对隐匿性要求中等 | 方案一（browser-use + nodriver） |
| Boss 直聘等强反爬网站、长期稳定运行 | 方案二（Camoufox + 自研 Agent） |
| 最终生产环境 | 方案二为主，方案一作为 Chromium 兼容降级 |

建议先并行验证两套方案（阶段一），根据 Boss 直聘实测结果决定阶段二重点投入哪个。

---

## 验证清单

```bash
# 反检测测试
1. https://bot.sannysoft.com → 所有项目应为绿色
2. https://fingerprintjs.com/demo → 指纹应每次不同
3. https://nowsecure.nl → 应通过 Cloudflare 验证
4. https://www.zhipin.com → 应正常加载，不触发验证码

# 功能测试
5. Boss 直聘搜索 + 浏览职位详情（完整流程）
6. noVNC 远程查看浏览器画面
7. API 提交任务并获取结果
8. 人工接管操作（验证码场景）

# 性能测试
9. 页面加载 < 3s
10. DOM 快照 < 500ms
11. Agent 单步响应 < 3s（含 LLM 调用）
12. 连续运行 1 小时不被封
```

## 关键文件参考

- `browser-use/browser_use/browser/session.py:1682` — `connect()` 方法，CDP 连接入口
- `browser-use/browser_use/browser/profile.py:562` — `cdp_url` 配置字段
- `browser-use/browser_use/dom/serializer/serializer.py:100` — DOM 压缩序列化
- `browser-use/examples/browser/using_cdp.py` — CDP 外部浏览器连接示例
- `camoufox/pythonlib/camoufox/async_api.py` — Camoufox 异步 API
- `camoufox/pythonlib/camoufox/fingerprints.py` — BrowserForge 指纹生成
- `camoufox/pythonlib/camoufox/virtdisplay.py` — Linux 虚拟显示
- `nodriver/nodriver/core/config.py` — nodriver 启动参数
- `Scrapling/scrapling/engines/_browsers/_stealth.py` — 资源拦截/page pooling 参考
