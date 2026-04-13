# Browser-Use与反爬虫技术分析报告

## Context

本项目 `browser-controller` 包含 4 个浏览器自动化项目（Scrapling、browser-use、Camoufox、nodriver）。本报告以 Boss 直聘（zhipin.com）为典型高防护目标，结合中文爬虫社区（CSDN、掘金、知乎、FreeBuf）的实战经验，给出 Chromium 和 Firefox 两条最佳技术路线。

---

## 一、Boss 直聘反爬体系深度分析

### 1.1 多层防护栈

Boss 直聘使用的不是单一反爬系统，而是**多厂商多层级联防**：

```
┌─────────────────────────────────────────────────────────────┐
│                  Boss 直聘反爬体系                            │
│                                                             │
│  第 5 层  ┌─────────────────────────────────────────────┐  │
│  行为分析  │ 同盾科技 (TongDun) 行为生物识别              │  │
│           │ ・鼠标轨迹熵值分析                           │  │
│           │ ・滚动/点击时序模式                          │  │
│           │ ・页面停留时间分布                           │  │
│           └─────────────────────────────────────────────┘  │
│                                                             │
│  第 4 层  ┌─────────────────────────────────────────────┐  │
│  动态令牌  │ wt 参数 (自研) + __zp_stoken__ (同盾SDK)    │  │
│           │ ・wt: 每次请求动态生成，绑定会话+指纹+时间戳 │  │
│           │ ・zp_stoken: 同盾SDK加密指纹令牌             │  │
│           │ ・反调试: 检测 DevTools 打开状态              │  │
│           └─────────────────────────────────────────────┘  │
│                                                             │
│  第 3 层  ┌─────────────────────────────────────────────┐  │
│  验证码    │ 极验 (GeeTest) v4 滑块验证码                 │  │
│           │ ・拼图滑块 + 鼠标加速度曲线分析              │  │
│           │ ・影子验证码（后台静默行为评分）              │  │
│           └─────────────────────────────────────────────┘  │
│                                                             │
│  第 2 层  ┌─────────────────────────────────────────────┐  │
│  设备指纹  │ 同盾 + 自研 指纹采集                         │  │
│           │ ・Canvas / WebGL / AudioContext / 字体枚举    │  │
│           │ ・navigator 全属性 + 屏幕 + 时区 + 语言      │  │
│           │ ・WebRTC 本地 IP 泄漏检测                    │  │
│           └─────────────────────────────────────────────┘  │
│                                                             │
│  第 1 层  ┌─────────────────────────────────────────────┐  │
│  网络层    │ Akamai Bot Manager + 自研 IP 风控            │  │
│           │ ・_abck cookie / sensor data                 │  │
│           │ ・TLS/JA3 指纹检测                           │  │
│           │ ・数据中心 IP 段预封禁                       │  │
│           │ ・请求频率异常检测                           │  │
│           └─────────────────────────────────────────────┘  │
│                                                             │
│  第 0 层  ┌─────────────────────────────────────────────┐  │
│  自动化检测│ navigator.webdriver / CDP 泄漏检测           │  │
│           │ ・Playwright/Selenium 特征检测               │  │
│           │ ・Chrome DevTools Protocol 痕迹              │  │
│           └─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 关键技术挑战

| 挑战 | 说明 | 难度 |
|------|------|------|
| `wt` 参数 | 动态反爬令牌，绑定会话+指纹+时间戳，混淆 JS 生成 | ★★★★★ |
| `__zp_stoken__` | 同盾 SDK 加密指纹令牌，绑定浏览器指纹 | ★★★★★ |
| 极验滑块 | GeeTest v4 拼图验证码 + 鼠标轨迹分析 | ★★★★ |
| TLS 指纹 | JA3/JA4 检测，Python requests 直接被拦 | ★★★ |
| 设备指纹 | Canvas/WebGL/Audio 多维指纹采集 | ★★★ |
| IP 风控 | 数据中心 IP 预封，住宅 IP 频率限制 | ★★★ |
| 登录要求 | 详细数据需登录，账号频繁操作会被封 | ★★★ |

### 1.3 社区实测成功率（2025）

| 方案 | 成功率 | 说明 |
|------|--------|------|
| Python requests 裸请求 | ~0% | 立即被拦 |
| Selenium headless | ~5% | 1-2 页即被检测 |
| Playwright + stealth 插件 | ~30-40% | 中等防护可过 |
| DrissionPage / Camoufox 非 headless | ~40-60% | 社区推荐 |
| 上述 + 中国住宅代理 | ~60-70% | 显著提升 |
| 上述 + 4G/5G 移动代理 | ~70-80% | 移动 IP 信誉最高 |
| 上述 + 验证码服务 | ~80-85% | 接近上限 |

---

## 二、本项目 4 个工具能力矩阵

| 能力 | Scrapling | browser-use | Camoufox | nodriver |
|------|-----------|-------------|----------|---------|
| 浏览器 | Chromium (Patchright) | Chromium (CDP) | Firefox (定制) | Chromium (CDP) |
| 自动化隐匿 | ★★★ Patchright | ★★ 禁用组件 | ★★★★★ C++补丁 | ★★★ 无WebDriver |
| 指纹伪装 | ★★ Canvas/WebRTC | ★ 无 | ★★★★★ 全面C++ | ★ 无 |
| TLS 伪装 | ★★★★ curl_cffi | ★ 无 | ★★ Firefox原生 | ★ 无 |
| 行为模拟 | ★ 脚本化 | ★★★★★ LLM类人 | ★★ 需自行实现 | ★ 需自行实现 |
| 验证码处理 | ★★ CF Turnstile | ★★★ Watchdog | ★ 无内置 | ★★ CF verify |
| 代理管理 | ★★★ ProxyRotator | ★★ ProxySettings | ★★★ GeoIP联动 | ★ 无 |
| CDP 外部连接 | ✅ cdp_url 参数 | ✅ cdp_url 参数 | ❌ Firefox无CDP | ✅ 提供CDP端口 |
| 可视化运行 | ✅ headless=False | ✅ headless=False | ✅ headless=False | ✅ 默认可视化 |

---

## 三、社区推荐工具引入与对比

### 3.1 四个社区工具评估

| 工具 | 类型 | 是否引入 | 理由 |
|------|------|---------|------|
| **DrissionPage** | 浏览器自动化 | ✅ **强烈推荐** | 中国社区首推，独有的 MixPage 混合模式，Boss 直聘实战验证 |
| **botright** | Playwright + CAPTCHA | ✅ **推荐** | 内置极验/hCaptcha AI 求解 + 贝塞尔曲线鼠标模拟，填补 Camoufox 的空缺 |
| **rebrowser-patches** | CDP 泄漏修复 | ⚠️ **可选** | patchright（已在 Scrapling 中）覆盖相同问题且更全面；nodriver 无需此修复 |
| **tls-client** | TLS 指纹伪装 | ⚠️ **可选** | curl_cffi（已在 Scrapling 中）功能更强、维护更活跃；仅在需自定义 JA3 时有价值 |

### 3.2 DrissionPage — 中国社区首推工具

**GitHub**: [g1879/DrissionPage](https://github.com/g1879/DrissionPage) — 11,000+ stars
**安装**: `pip install DrissionPage`

**核心特性**:
- **CDP 直连**（非 WebDriver），无 `navigator.webdriver` 泄漏
- **无需 chromedriver**，与 nodriver 类似的架构优势
- **MixPage 混合模式（独有杀手级功能）**: 浏览器模式登录 → 无缝切换 HTTP 模式采集，Cookie 自动共享
- **中国网站社区支持最强**: 掘金、CSDN、知乎 有大量 Boss 直聘实战教程

**与 nodriver 的关键区别**:

| 特性 | DrissionPage | nodriver |
|------|-------------|---------|
| 协议 | CDP | CDP |
| 混合 HTTP+浏览器模式 | ✅ **MixPage（独有）** | ❌ |
| 异步 | 部分 | 全异步 (asyncio) |
| 中国网站社区 | ★★★★★ | ★★ |
| Cloudflare 绕过 | ★★★ | ★★★★ |
| API 风格 | 同步为主 | 异步为主 |

**MixPage 混合模式工作原理**:
```
┌─────────────────────────────────────────────────────┐
│  DrissionPage MixPage 混合模式                       │
│                                                     │
│  阶段 1: 浏览器模式 ('d' 模式)                       │
│  ┌───────────────────────────────────────────────┐  │
│  │ page = MixPage('d')                          │  │
│  │ page.get("https://zhipin.com/login")         │  │
│  │ # 微信扫码登录 / 手机验证码                   │  │
│  │ # wt / zp_stoken 由 JS 自然生成              │  │
│  │ # 同盾 SDK 采集到真实浏览器指纹               │  │
│  └──────────────┬────────────────────────────────┘  │
│                 │ Cookie 自动共享                    │
│                 ↓                                    │
│  阶段 2: HTTP 模式 ('s' 模式)                        │
│  ┌───────────────────────────────────────────────┐  │
│  │ page.change_mode('s')  # 无缝切换!            │  │
│  │ page.get("https://zhipin.com/api/data")      │  │
│  │ data = page.json  # 高速 HTTP 请求            │  │
│  │ # 复用浏览器登录的 Cookie                     │  │
│  │ # 无需再过反爬检测                           │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  优势: 浏览器解决登录+反爬 → HTTP 高速采集           │
└─────────────────────────────────────────────────────┘
```

**Boss 直聘实战代码**:
```python
from DrissionPage import ChromiumPage

page = ChromiumPage()
page.get("https://www.zhipin.com/web/geek/job?query=Python")

# 等待页面加载 (wt/zp_stoken 由 JS 自然生成)
page.wait.load_start()

# 提取职位列表
jobs = page.eles('css:.job-card-wrapper')
for job in jobs:
    title = job.ele('css:.job-name').text
    company = job.ele('css:.company-name').text
    salary = job.ele('css:.salary').text
    print(f"{title} | {company} | {salary}")
```

### 3.3 botright — CAPTCHA + 人类行为模拟

**GitHub**: [Vinyzu/botright](https://github.com/Vinyzu/botright) — 866 stars
**安装**: `pip install botright && playwright install chromium`

**核心特性**:
- **Playwright 的 drop-in 替代**，增加隐匿层
- **内置 AI CAPTCHA 求解**（无需付费第三方服务）
- **贝塞尔曲线鼠标移动**（加速→减速+抖动）
- **打字模拟**（变速 + 偶尔打错退格）
- **滚动模拟**（懒加载触发 + 非匀速）

**CAPTCHA 支持**:

| 验证码类型 | 支持 |
|-----------|------|
| hCaptcha | ✅ AI 图像识别 + 音频回退 |
| reCAPTCHA v2/v3 | ✅ |
| GeeTest 滑块 | ✅ |
| FunCaptcha | ✅ |
| Cloudflare Turnstile | ❌ |

**与 Camoufox 的互补关系**:
```
Camoufox: 指纹隐匿 ★★★★★ | CAPTCHA ❌ | 行为模拟 ❌
botright: 指纹隐匿 ★★★   | CAPTCHA ✅ | 行为模拟 ✅

→ 互补: Camoufox 的指纹 + botright 的行为/CAPTCHA
  (但两者无法直接组合，因为一个是 Firefox 一个是 Chromium)
```

**代码示例**:
```python
import botright, asyncio

async def scrape_with_human_behavior():
    client = await botright.Botright()
    browser = await client.newBrowser()
    page = await browser.new_page()

    await page.goto("https://www.zhipin.com")

    # 贝塞尔曲线鼠标移动 + 点击 (像真人一样)
    await page.click("#search-input")

    # 模拟真人打字 (变速, 偶尔停顿)
    await page.type("#search-input", "Python开发", delay=80)

    # 模拟真人滚动 (触发懒加载)
    await page.human_scroll()

    # 自动检测并解决极验滑块
    # botright 内置 AI 求解，无需第三方服务
    await page.solve_geetest()

    await browser.close()
    await client.close()
```

### 3.4 rebrowser-patches — CDP 泄漏修复

**GitHub**: [rebrowser/rebrowser-patches](https://github.com/rebrowser/rebrowser-patches) — 1,300 stars
**安装**: `pip install rebrowser-playwright`  (Python 版)

**修复的核心问题**: Playwright/Puppeteer 调用 `Runtime.Enable` 时会在 `window` 上注入可检测的绑定对象。

**与本项目的关系**:
- **Scrapling 已用 patchright**（覆盖 Runtime.Enable + 更多泄漏）→ rebrowser-patches 冗余
- **nodriver 不调用 Runtime.Enable**（纯 CDP 直连）→ 无需修复
- **仅当你想对原生 Playwright（非 patchright）打补丁时才需要**

### 3.5 tls-client — TLS 指纹伪装

**GitHub**: [bogdanfinn/tls-client](https://github.com/bogdanfinn/tls-client)
**安装**: `pip install tls-client`

**与 curl_cffi 对比**:

| 维度 | tls-client | curl_cffi (已在 Scrapling 中) |
|------|-----------|------------------------------|
| JA3 | ✅ | ✅ |
| JA4 | 部分 | ✅ 更完整 |
| HTTP/2 帧伪装 | 部分 | ✅ 更精确 |
| 异步 | ❌ | ✅ asyncio |
| 维护 | ⚠️ PyPI 最后更新 2023.11 | ✅ 非常活跃 |
| 自定义 JA3 | ✅ 容易 | ⚠️ 较复杂 |

**结论**: curl_cffi 已在项目中且更强。tls-client 的唯一优势是更容易注入完全自定义的 JA3 字符串。

---

## 四、完整工具能力矩阵（8 个工具）

| 能力 | nodriver | Camoufox | Scrapling | browser-use | DrissionPage | botright | rebrowser | tls-client |
|------|---------|----------|-----------|-------------|-------------|---------|-----------|-----------|
| 浏览器 | Chrome | Firefox | Chrome | Chrome | Chrome | Chrome | Chrome | - (HTTP) |
| 自动化隐匿 | ★★★ | ★★★★★ | ★★★ | ★★ | ★★★ | ★★★ | ★★★ | - |
| 指纹伪装 | ★ | ★★★★★ | ★★ | ★ | ★ | ★★★ | ★★ | - |
| TLS 伪装 | ★ | ★★ | ★★★★ | ★ | ★ | ★ | ★ | ★★★★ |
| 行为模拟 | ★ | ★ | ★ | ★★★★★ | ★★ | ★★★★ | ★ | - |
| CAPTCHA | ★★ CF | ❌ | ★★ CF | ★★★ | ★ | ★★★★ | ★ | - |
| 混合模式 | ❌ | ❌ | ❌ | ❌ | ✅ **独有** | ❌ | ❌ | - |
| 中国网站社区 | ★★ | ★★ | ★★ | ★★ | ★★★★★ | ★★ | ★★ | ★★ |

---

## 五、Chromium 最佳技术路线

### 5.1 三套 Chromium 方案（按场景选择）

**方案 C1: DrissionPage — Boss 直聘首选（中国社区实战验证）**
```
DrissionPage MixPage 混合模式
  + 浏览器模式登录 → HTTP 模式批量采集
  + 住宅 IP 直出 + 速率控制
```

**方案 C2: nodriver + browser-use — AI Agent 类人交互**
```
nodriver (启动层, 无 WebDriver)
  + browser-use (LLM 驱动类人行为)
  + Scrapling curl_cffi (TLS 伪装 HTTP 层, 可选)
  + 住宅 IP 直出 + 速率控制
```

**方案 C3: botright — 内置 CAPTCHA + 行为模拟**
```
botright (Playwright + 贝塞尔曲线 + AI CAPTCHA)
  + 内置极验/hCaptcha 求解
  + 住宅 IP 直出 + 速率控制
```

**方案选择指南**:
- 用 **DrissionPage (C1)** 当: Boss 直聘等中国网站、需要登录后采集、追求稳定性
- 用 **nodriver + browser-use (C2)** 当: 需要 AI 驱动的复杂交互、多步骤流程
- 用 **botright (C3)** 当: 频繁遇到验证码、需要内置行为模拟、不想用付费验证码服务

### 5.2 方案 C1 架构图: DrissionPage (Boss 直聘首选)

```
┌──────────────────────────────────────────────────────────────────┐
│           DrissionPage 混合模式 — Boss 直聘采集                    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  阶段 1: 浏览器模式 (MixPage 'd' 模式)                 │     │
│  │                                                        │     │
│  │  page = MixPage('d')                                  │     │
│  │  page.get("https://www.zhipin.com")                   │     │
│  │                                                        │     │
│  │  ・真实 Chrome 进程 (CDP 连接, 非 WebDriver)           │     │
│  │  ・headless=False → 可视化，VNC 远程查看               │     │
│  │  ・wt / zp_stoken 由 JS 自然生成                      │     │
│  │  ・同盾 SDK 采集到真实浏览器指纹                       │     │
│  │  ・手动扫码登录 → 获得完整 Cookie                     │     │
│  │                                                        │     │
│  │  遇到极验滑块 →                                       │     │
│  │  ・YesCaptcha / botright.solve_geetest() 求解          │     │
│  └──────────────────┬─────────────────────────────────────┘     │
│                     │ Cookie 自动共享 (无缝)                     │
│                     ↓                                            │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  阶段 2: HTTP 模式 (MixPage 's' 模式)                  │     │
│  │                                                        │     │
│  │  page.change_mode('s')                                │     │
│  │  page.get("https://www.zhipin.com/wapi/...")           │     │
│  │  data = page.json                                     │     │
│  │                                                        │     │
│  │  ・高速 HTTP 请求 (无浏览器开销)                       │     │
│  │  ・复用浏览器获得的全部 Cookie                         │     │
│  │  ・包括 zp_token + __zp_stoken__                      │     │
│  │  ・注意: wt 参数仍需从浏览器获取                      │     │
│  └──────────────────┬─────────────────────────────────────┘     │
│                     │                                            │
│                 家庭宽带公网 IP                                   │
│                     ↓                                            │
│              zhipin.com                                          │
└──────────────────────────────────────────────────────────────────┘
```

### 5.3 方案 C2 架构图: nodriver + browser-use (AI Agent)

```
┌──────────────────────────────────────────────────────────────────────┐
│              Chromium 路线：Boss 直聘采集架构                          │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  第 1 层: nodriver 隐匿启动                                 │     │
│  │                                                            │     │
│  │  browser = await Browser.create(                           │     │
│  │      headless=False,          # 可视化 + 更难检测           │     │
│  │      port=9222,               # 暴露 CDP 端口              │     │
│  │  )                                                         │     │
│  │                                                            │     │
│  │  核心优势:                                                 │     │
│  │  ・无 WebDriver → navigator.webdriver = undefined          │     │
│  │  ・无 ChromeDriver 二进制 → 文件系统无痕迹                 │     │
│  │  ・直接 CDP → 最小自动化暴露面                             │     │
│  │  ・verify_cf() → 内置 Cloudflare 绕过                     │     │
│  └──────────────────┬─────────────────────────────────────────┘     │
│                     │ CDP: ws://localhost:9222                       │
│                     │                                                │
│  ┌──────────────────↓─────────────────────────────────────────┐     │
│  │  第 2 层: 页面交互 (两种模式可选)                            │     │
│  │                                                            │     │
│  │  模式 A: nodriver 直接操作 (简单场景)                       │     │
│  │  ┌────────────────────────────────────────────────────┐   │     │
│  │  │  tab = await browser.get("https://www.zhipin.com") │   │     │
│  │  │  # nodriver 自动处理: wt 参数由页面 JS 生成         │   │     │
│  │  │  # zp_stoken 由同盾 SDK 在浏览器内自动生成          │   │     │
│  │  │  # → 无需逆向，让浏览器自然运行                     │   │     │
│  │  └────────────────────────────────────────────────────┘   │     │
│  │                                                            │     │
│  │  模式 B: browser-use AI Agent (复杂交互)                   │     │
│  │  ┌────────────────────────────────────────────────────┐   │     │
│  │  │  session = BrowserSession(cdp_url="http://:9222")  │   │     │
│  │  │  agent = Agent(task="搜索Python岗位,翻页,提取",     │   │     │
│  │  │               llm=ChatOpenAI(model="gpt-4o"))      │   │     │
│  │  │  # LLM 驱动 → 非线性操作 → 类人行为               │   │     │
│  │  │  # 自带 CAPTCHA Watchdog → 自动检测验证码          │   │     │
│  │  └────────────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────────────┘     │
│                     │                                                │
│  ┌──────────────────↓─────────────────────────────────────────┐     │
│  │  第 3 层: 极验滑块处理                                      │     │
│  │                                                            │     │
│  │  检测到 GeeTest 滑块 →                                     │     │
│  │  ┌────────────────────────────────────────────────────┐   │     │
│  │  │  方案 1: 第三方服务 (推荐)                          │   │     │
│  │  │  ・YesCaptcha (中国社区首选, 支持极验 v4)           │   │     │
│  │  │  ・CapSolver (国际服务, GeeTest v4)                │   │     │
│  │  │  ・图鉴 TTShitu (国内服务, 快速)                   │   │     │
│  │  ├────────────────────────────────────────────────────┤   │     │
│  │  │  方案 2: OpenCV 自解 (省钱但准确率较低)             │   │     │
│  │  │  ・截图 → cv2.Canny 边缘检测 → 定位缺口            │   │     │
│  │  │  ・贝塞尔曲线拖动轨迹 (加速→减速+抖动)            │   │     │
│  │  └────────────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────────────┘     │
│                     │                                                │
│  ┌──────────────────↓─────────────────────────────────────────┐     │
│  │  第 4 层: 行为模拟 + 速率控制                               │     │
│  │                                                            │     │
│  │  ResidentialIPRateLimiter:                                 │     │
│  │  ・请求间隔: 5-15 秒随机 (Boss 直聘社区建议 ≥3 秒)        │     │
│  │  ・每会话: ≤30 页 → 休息 10-20 分钟                       │     │
│  │  ・每日: ≤300 请求 (住宅单 IP 保守策略)                   │     │
│  │  ・避开高峰: 9:00-18:00 CST                               │     │
│  │                                                            │     │
│  │  人类行为模拟:                                             │     │
│  │  ・贝塞尔曲线鼠标移动 (可视化窗口可观察)                  │     │
│  │  ・非匀速滚动 (快→慢→停→快)                              │     │
│  │  ・随机停顿 "阅读" 3-20 秒                                │     │
│  │  ・偶尔回退/重访 (真人行为)                               │     │
│  └────────────────────────────────────────────────────────────┘     │
│                     │                                                │
│                 家庭宽带公网 IP (天然住宅 IP)                         │
│                     ↓                                                │
│              zhipin.com (Boss 直聘)                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 执行步骤

**步骤 1: 环境安装**
```bash
pip install nodriver browser-use scrapling[all]
# browser-use 的 LLM 支持 (可选, 用于 AI Agent 模式)
export OPENAI_API_KEY="sk-..."
```

**步骤 2: nodriver 启动可视化浏览器**
```python
import nodriver as uc
import asyncio, random

async def launch():
    browser = await uc.Browser.create(
        headless=False,                     # 可视化: 看到浏览器
        browser_args=[
            "--window-size=1920,1080",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--lang=zh-CN",                 # 中文环境, 与 Boss 直聘匹配
        ],
    )
    return browser
```

**步骤 3: 让浏览器自然生成 wt 和 zp_stoken**
```python
async def browse_boss(browser):
    """关键: 不要逆向 wt/zp_stoken, 让浏览器自然生成"""
    tab = await browser.get("https://www.zhipin.com")
    await asyncio.sleep(random.uniform(3, 6))

    # 如果需要登录 — 手动扫码或 Cookie 注入
    # Boss 直聘需要登录才能看到完整信息

    # 搜索岗位 — 模拟真人操作
    search_box = await tab.find("搜索职位")
    if search_box:
        await search_box.click()
        await asyncio.sleep(random.uniform(0.5, 1.5))

        # 逐字符输入 (模拟打字)
        for char in "Python开发":
            await tab.send_keys(char)
            await asyncio.sleep(random.uniform(0.05, 0.2))

        await asyncio.sleep(random.uniform(0.5, 1.0))
        await tab.send_keys("\n")  # 回车搜索

    # 等待结果加载 — wt 参数由页面 JS 自动生成
    await asyncio.sleep(random.uniform(3, 8))

    # 提取数据
    return await extract_jobs(tab)
```

**步骤 4: 极验滑块处理**
```python
async def handle_geetest(tab, solver_api_key):
    """检测并处理极验滑块验证码"""
    # 检测是否出现滑块
    slider = await tab.find(".geetest_slider_button", timeout=3)
    if not slider:
        return  # 没有验证码

    # 方案 1: 第三方服务 (推荐)
    import capsolver
    capsolver.api_key = solver_api_key

    # 截取验证码图片信息
    gt = await tab.evaluate("document.querySelector('[data-captcha-id]')?.dataset?.captchaId")

    solution = capsolver.solve({
        "type": "GeeTestTaskProxyLess",
        "websiteURL": "https://www.zhipin.com",
        "gt": gt,
        "version": 4,
    })

    # 注入解决方案
    await tab.evaluate(f"""
        // 调用极验回调函数注入 token
        window.captchaObj?.verify()
    """)

    # 方案 2: OpenCV 自解 (备选)
    # screenshot = await tab.save_screenshot()
    # gap_x = detect_gap_position(screenshot)  # OpenCV 边缘检测
    # await bezier_drag(tab, slider, gap_x)     # 贝塞尔曲线拖动
```

**步骤 5: 人类行为模拟**
```python
async def simulate_human(tab):
    """可视化窗口中能看到这些模拟操作"""
    # 随机滚动浏览结果
    for _ in range(random.randint(2, 5)):
        scroll = random.randint(200, 500)
        await tab.evaluate(f"window.scrollBy(0, {scroll})")
        await asyncio.sleep(random.uniform(1, 4))  # "阅读"停顿

    # 随机点击一个职位查看详情 (真人行为)
    if random.random() < 0.3:
        links = await tab.select_all(".job-card-left")
        if links:
            target = random.choice(links)
            await target.click()
            await asyncio.sleep(random.uniform(5, 15))  # "阅读"职位详情
            await tab.back()  # 返回列表
            await asyncio.sleep(random.uniform(1, 3))
```

**步骤 6: browser-use AI Agent 模式 (复杂交互)**
```python
from browser_use import Agent, BrowserSession
from langchain_openai import ChatOpenAI

async def ai_agent_mode(browser_port=9222):
    """用 AI Agent 接管浏览器 — 最强行为隐匿"""
    session = BrowserSession(
        cdp_url=f"http://localhost:{browser_port}",
    )
    agent = Agent(
        task="""
        在 Boss 直聘上搜索"Python 开发"岗位：
        1. 进入 zhipin.com
        2. 在搜索框输入"Python开发"并搜索
        3. 浏览搜索结果，记录每个岗位的：职位名称、公司、薪资、地点
        4. 翻到下一页，继续记录
        5. 共收集 3 页结果
        注意：操作要自然，每个页面多看几秒
        """,
        llm=ChatOpenAI(model="gpt-4o"),
        browser_session=session,
    )
    result = await agent.run(max_steps=50)
    return result
```

---

## 六、Firefox 最佳技术路线

### 6.1 推荐工具组合

```
Camoufox (38 个 C++ 级指纹补丁)
  + Playwright API (Camoufox 返回标准 Playwright 对象)
  + 极验滑块求解服务
  + 住宅 IP 直出
  + 速率控制 + 人类行为模拟
```

**选择理由（社区共识）**：
- **Camoufox > vanilla Firefox + playwright-stealth**: Camoufox 的指纹伪装在 C++ 引擎层实现，JS 层完全无法检测到伪装痕迹
- **Firefox > Chromium 的指纹维度**: 很多反爬系统（包括同盾）主要维护 Chromium 自动化的特征库，Firefox 自动化特征库相对薄弱
- **Firefox 的 TLS 指纹天然不同**: Firefox 的 JA3 与 Chrome 不同，部分网站只针对 Chrome 自动化的 JA3 做拦截
- **劣势**: Boss 直聘的 JS SDK 可能对 Firefox 兼容性略差；Camoufox 无法被 CDP 工具（browser-use/nodriver）驱动

### 6.2 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│              Firefox 路线：Boss 直聘采集架构                           │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  第 1 层: Camoufox 启动 (C++ 级隐匿)                       │     │
│  │                                                            │     │
│  │  async with AsyncCamoufox(                                │     │
│  │      headless=False,       # 可视化                        │     │
│  │      os="windows",         # 伪装为 Windows (最常见)       │     │
│  │      # 不设 proxy → 家庭宽带 IP 直出                      │     │
│  │  ) as browser:                                            │     │
│  │                                                            │     │
│  │  C++ 补丁自动生效:                                         │     │
│  │  ┌──────────────────────────────────────────────────┐     │     │
│  │  │ ・navigator-spoofing    → UA/platform/cores 伪装 │     │     │
│  │  │ ・canvas-spoofing       → Canvas 渲染随机化      │     │     │
│  │  │ ・webgl-spoofing        → WebGL 参数伪装        │     │     │
│  │  │ ・audio-fingerprint     → AudioContext 噪声      │     │     │
│  │  │ ・anti-font-fingerprint → 字体间距种子           │     │     │
│  │  │ ・screen-spoofing       → 屏幕/DPR 伪装         │     │     │
│  │  │ ・webrtc-ip-spoofing    → WebRTC IP 防泄漏       │     │     │
│  │  │ ・leak-fixes            → Playwright 痕迹消除    │     │     │
│  │  └──────────────────────────────────────────────────┘     │     │
│  │                                                            │     │
│  │  BrowserForge 自动生成:                                    │     │
│  │  ・真实市场份额分布的 User-Agent                           │     │
│  │  ・与 OS 匹配的字体子集 (含 CreepJS 标记字体)              │     │
│  │  ・一致的 WebGL 参数                                       │     │
│  └──────────────────┬─────────────────────────────────────────┘     │
│                     │ Playwright API (page 对象)                     │
│                     │                                                │
│  ┌──────────────────↓─────────────────────────────────────────┐     │
│  │  第 2 层: Playwright 页面操作                               │     │
│  │                                                            │     │
│  │  page = await browser.new_page()                          │     │
│  │  await page.goto("https://www.zhipin.com")                │     │
│  │                                                            │     │
│  │  # wt / zp_stoken 由浏览器内 JS 自然生成                  │     │
│  │  # 同盾 SDK 采集到的指纹 → 全部是 Camoufox 伪造的一致指纹  │     │
│  │  # → 同盾认为这是一个真实的 Windows Firefox 用户            │     │
│  │                                                            │     │
│  │  操作方式:                                                 │     │
│  │  ・page.fill() / page.click() / page.keyboard.type()      │     │
│  │  ・page.mouse.move() → 贝塞尔曲线移动                     │     │
│  │  ・page.evaluate() → 提取页面数据                          │     │
│  └────────────────────────────────────────────────────────────┘     │
│                     │                                                │
│  ┌──────────────────↓─────────────────────────────────────────┐     │
│  │  第 3 层: 极验滑块 + 行为控制 (同 Chromium 路线)            │     │
│  │                                                            │     │
│  │  ・极验滑块: YesCaptcha / CapSolver / OpenCV 自解          │     │
│  │  ・速率控制: 5-15 秒间隔, ≤30 页/会话, ≤300 请求/天       │     │
│  │  ・人类行为: 滚动、停顿、偶尔查看详情页                    │     │
│  └────────────────────────────────────────────────────────────┘     │
│                     │                                                │
│                 家庭宽带公网 IP                                       │
│                     ↓                                                │
│              zhipin.com (Boss 直聘)                                   │
│              同盾 SDK 看到: "真实 Windows Firefox 用户"                │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.3 执行步骤

**步骤 1: 环境安装**
```bash
pip install "camoufox[geoip]" browserforge
python -m camoufox fetch    # 下载定制 Firefox 二进制
```

**步骤 2: Camoufox 可视化启动**
```python
from camoufox.async_api import AsyncCamoufox
import asyncio, random

async def launch_camoufox():
    return AsyncCamoufox(
        headless=False,      # 可视化: 看到 Firefox 窗口
        os="windows",        # 伪装为 Windows (Boss 直聘用户最多的 OS)
        # 不设 proxy → 家庭宽带 IP 直出
    )
```

**步骤 3: 完整采集流程**
```python
async def scrape_boss_firefox():
    async with AsyncCamoufox(headless=False, os="windows") as browser:
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        # 访问 Boss 直聘
        await page.goto("https://www.zhipin.com", wait_until="networkidle")
        await asyncio.sleep(random.uniform(3, 6))

        # 搜索岗位 — 使用 Playwright 原生 API
        search_input = page.locator("input[name='query']")
        await search_input.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # 逐字符输入 (模拟真人打字速度)
        for char in "Python开发":
            await page.keyboard.type(char, delay=random.randint(50, 200))

        await asyncio.sleep(random.uniform(0.5, 1.0))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(3, 8))

        # 提取职位列表
        jobs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('.job-card-wrapper')).map(card => ({
                title: card.querySelector('.job-name')?.textContent?.trim(),
                company: card.querySelector('.company-name')?.textContent?.trim(),
                salary: card.querySelector('.salary')?.textContent?.trim(),
                location: card.querySelector('.job-area')?.textContent?.trim(),
                tags: Array.from(card.querySelectorAll('.tag-list span')).map(t => t.textContent?.trim()),
            }))
        """)

        # 人类行为: 滚动 + 停顿
        for _ in range(random.randint(2, 4)):
            await page.evaluate(f"window.scrollBy(0, {random.randint(300, 600)})")
            await asyncio.sleep(random.uniform(2, 5))

        return jobs
```

---

## 七、两条路线对比与选择

### 7.1 对比表

| 维度 | Chromium 路线 (nodriver) | Firefox 路线 (Camoufox) |
|------|--------------------------|-------------------------|
| **指纹隐匿深度** | ★★★ (启动参数级) | ★★★★★ (C++ 引擎级) |
| **同盾 SDK 对抗** | ★★★ (无 webdriver, 但指纹可能被关联) | ★★★★★ (全面伪造指纹, SDK 采集到假数据) |
| **TLS 指纹** | ★★ (Chrome 默认, + curl_cffi 补充) | ★★★ (Firefox 原生 TLS, 检测库较少) |
| **AI Agent 能力** | ★★★★★ (browser-use CDP 直连) | ★ (无法被 CDP 工具驱动) |
| **社区成熟度** | ★★★★ (nodriver 社区活跃) | ★★★ (Camoufox 较新但增长快) |
| **调试便捷性** | ★★★★ (CDP 工具丰富) | ★★ (Playwright API 为主) |
| **极验兼容性** | ★★★★★ (Chrome 是主流浏览器) | ★★★ (极验对 Firefox 兼容性略差) |
| **部署复杂度** | ★★★★★ (pip install 即可) | ★★★ (需要下载定制 Firefox) |

### 7.2 选择建议

```
Boss 直聘采集 → 选择路线决策树:

Q1: 有中国网站反爬实战经验吗？
  ├── 新手 → DrissionPage (C1) — 社区教程最多，MixPage 最易上手
  │
  └── 有经验 → Q2: 最看重什么？
                │
                ├── 指纹隐匿深度 → Camoufox (Firefox 路线)
                │   同盾 SDK 完全被骗, CreepJS 通过率最高
                │
                ├── AI 类人行为 → nodriver + browser-use (C2)
                │   LLM 驱动最像真人
                │
                ├── 内置验证码 → botright (C3)
                │   极验/hCaptcha 免费 AI 求解
                │
                └── 部署简单 → DrissionPage (C1)
                    pip install 即用, 中文文档
```

### 7.3 混合方案: Camoufox 突破 + curl_cffi 批量

```
┌─────────────────────────────────────────────────────────────┐
│              混合路线 (两条路线取长补短)                       │
│                                                             │
│  阶段 1: Camoufox 突破                                      │
│  ・AsyncCamoufox(headless=False) 可视化登录                 │
│  ・通过同盾检测, 获得有效 Cookie                            │
│  ・让页面自然生成 wt / zp_stoken                            │
│  ・导出 Cookie + Session 状态                               │
│                                                             │
│  阶段 2: curl_cffi 高速采集 (可选, 仅对 API 端点有效)       │
│  ・impersonate="chrome120" 伪装 TLS                         │
│  ・注入 Camoufox 获得的 Cookie                              │
│  ・高并发请求 API 端点                                      │
│  ・Cookie 过期 → 回到阶段 1 刷新                            │
│                                                             │
│  注意: Boss 直聘的 wt 参数是会话绑定的,                      │
│  curl_cffi 直接请求可能仍需有效 wt,                          │
│  所以大多数场景建议全程在浏览器内操作                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 八、可视化 + 住宅 IP 部署方案

### 8.1 部署架构

```
┌──────────────────────────────────────────────────────────────┐
│              家庭 Mac / PC 部署                                │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Python 爬虫进程                                    │     │
│  │  ・nodriver/Camoufox headless=False                │     │
│  │  ・浏览器窗口在桌面可视化运行                       │     │
│  │  ・你在屏幕上实时看到爬虫操作                       │     │
│  └──────────────────┬─────────────────────────────────┘     │
│                     │                                        │
│  ┌──────────────────↓─────────────────────────────────┐     │
│  │  远程查看 (当你不在电脑前)                           │     │
│  │                                                    │     │
│  │  Mac: 系统设置 → 共享 → 屏幕共享 → 开启            │     │
│  │  连接: vnc://你的Mac局域网IP:5900                   │     │
│  │                                                    │     │
│  │  推荐: 安装 Tailscale (免费 P2P VPN)               │     │
│  │  ・两台设备登录同一 Tailscale 账号                  │     │
│  │  ・用 Tailscale IP 连接 VNC → 安全 + 不用端口映射  │     │
│  └────────────────────────────────────────────────────┘     │
│                     │                                        │
│              家庭宽带公网 IP → zhipin.com                     │
│              (天然住宅 IP, 高信誉)                            │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 住宅 IP 速率控制（Boss 直聘专用）

```python
class BossZhipinRateLimiter:
    """Boss 直聘专用速率控制 — 基于社区经验"""

    def __init__(self):
        self.page_count = 0
        self.daily_count = 0
        self.session_limit = 30        # 每会话最多 30 页
        self.daily_limit = 300         # 每天最多 300 请求
        self.min_interval = 5          # 最小 5 秒 (社区建议 ≥3 秒)
        self.max_interval = 15         # 最大 15 秒

    async def wait(self):
        self.page_count += 1
        self.daily_count += 1

        # 每日限量
        if self.daily_count >= self.daily_limit:
            print("达到每日限量, 明天继续")
            raise StopIteration

        # 会话休息 (模拟真人: 浏览一会后去做别的事)
        if self.page_count % self.session_limit == 0:
            rest = random.uniform(15, 30)  # 休息 15-30 分钟
            print(f"会话休息 {rest:.0f} 分钟...")
            await asyncio.sleep(rest * 60)

        # 请求间隔
        delay = random.uniform(self.min_interval, self.max_interval)
        if random.random() < 0.15:        # 15% 概率长停顿
            delay += random.uniform(15, 45)  # "去喝杯水"
        await asyncio.sleep(delay)
```

### 8.3 各项目可视化参数

| 项目 | 可视化参数 | 默认值 |
|------|-----------|--------|
| nodriver | `headless=False` | **False** (默认可视化) |
| Camoufox | `headless=False` | True |
| Scrapling | `headless=False` | True |
| browser-use | `headless=False` | True |

---

## 九、社区最佳实践总结

### 9.1 Boss 直聘采集核心原则

1. **全程浏览器内操作** — 不要尝试逆向 `wt` 和 `zp_stoken`，让浏览器 JS 自然生成
2. **非 headless 运行** — headless 有多个可检测特征，非 headless 更安全
3. **慢速低频** — 单住宅 IP 每天 ≤300 请求，间隔 ≥5 秒
4. **登录态管理** — Cookie 有效期内复用，过期后重新登录（手动扫码最安全）
5. **极验滑块交给服务** — YesCaptcha/CapSolver 自动解决，省时省力
6. **住宅 IP 是基石** — 数据中心 IP 直接被封，住宅 IP 信誉高
7. **人类行为不可省** — 鼠标移动、滚动、停顿、偶尔查看详情

### 9.2 社区推荐的验证码服务

| 服务 | 极验支持 | 国内速度 | 价格 |
|------|---------|---------|------|
| **YesCaptcha** | v3/v4 ✅ | ★★★★★ | 中 |
| **图鉴 TTShitu** | v3/v4 ✅ | ★★★★★ | 低 |
| **CapSolver** | v4 ✅ | ★★★ | 中 |
| **2Captcha** | v4 ✅ | ★★ | 中 |

### 9.3 指纹检测工具

| 工具 | 用途 | 网址 |
|------|------|------|
| **CreepJS** | 最全面的指纹一致性检测 | abrahamjuliot.github.io/creepjs |
| **BrowserLeaks** | WebRTC/Canvas/WebGL 泄漏 | browserleaks.com |
| **Pixelscan** | 自动化检测 + 指纹评分 | pixelscan.net |
| **bot.sannysoft.com** | 经典 bot 检测套件 | bot.sannysoft.com |

### 9.4 本项目关键文件索引

| 文件 | 作用 |
|------|------|
| `Scrapling/scrapling/engines/constants.py` | 95 条 Chrome 隐匿参数 |
| `Scrapling/scrapling/fetchers/stealth_chrome.py` | StealthyFetcher 主类 |
| `Scrapling/scrapling/engines/toolbelt/proxy_rotation.py` | 代理轮转 |
| `browser-use/browser_use/browser/session.py` | BrowserSession CDP 连接 |
| `browser-use/browser_use/agent/service.py` | AI Agent 循环 |
| `camoufox/patches/` | 38 个 C++ 反指纹补丁 |
| `camoufox/pythonlib/camoufox/fingerprints.py` | 指纹生成引擎 |
| `nodriver/nodriver/core/config.py` | nodriver 配置 |
| `nodriver/nodriver/core/tab.py` | verify_cf() + 页面操作 |

---

## 十、引入社区工具到本项目

### 10.1 安装命令

```bash
# 已有项目
pip install nodriver scrapling[all] "camoufox[geoip]" browser-use

# 新引入社区工具
pip install DrissionPage                    # 中国社区首推
pip install botright && playwright install   # CAPTCHA + 行为模拟
pip install rebrowser-playwright             # CDP 泄漏修复 (可选)
pip install tls-client                       # TLS 伪装 (可选)

# Camoufox Firefox
python -m camoufox fetch
```

### 10.2 源码 clone (可选对比分析)

```bash
cd /Users/galen/OpenSource/browser-controller
git clone https://github.com/g1879/DrissionPage.git
git clone https://github.com/Vinyzu/botright.git
git clone https://github.com/rebrowser/rebrowser-patches.git
```

---

## 十一、最终推荐方案

### Boss 直聘推荐优先级

| 优先级 | 方案 | 工具组合 | 适用场景 |
|--------|------|---------|---------|
| **1 (首选)** | DrissionPage C1 | DrissionPage MixPage + 住宅 IP | 日常采集、登录后数据提取 |
| **2** | Camoufox Firefox | AsyncCamoufox + 住宅 IP | 遇到严格指纹检测时 |
| **3** | AI Agent C2 | nodriver + browser-use | 复杂多步骤交互 |
| **4** | botright C3 | botright + 内置 CAPTCHA | 频繁遇到验证码 |
| **5** | 混合方案 | Camoufox 突破 + curl_cffi 批量 | 需要高并发批量采集 |

---

## 十二、通用浏览器控制统一架构

### 12.1 核心设计思想

**问题**: 4 个项目各有所长，但独立使用时都有短板：
- Scrapling: 反检测强，但无 AI Agent 能力
- browser-use: AI Agent 强，但反检测/指纹几乎为零
- nodriver: 隐匿启动好，但无解析/AI 能力
- Camoufox: 指纹最强，但 Firefox 无法被 CDP 工具驱动

**关键发现**: Scrapling（Patchright）和 browser-use（cdp-use）底层都基于 **CDP 协议**。它们可以**共享同一个浏览器实例** — 一个负责隐匿启动+反检测，另一个负责 AI 驱动+智能交互。

**设计原则**:
- **一个浏览器实例，多个控制层** — 通过 CDP 共享
- **脚本优先，AI 兜底** — 已知页面用脚本（零 token），异常才启 AI
- **反检测与 AI 能力解耦** — 各工具只做自己最擅长的事

### 12.2 统一架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    统一浏览器控制架构                                      │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  第 0 层: 隐匿启动层 (选一)                                     │     │
│  │                                                                │     │
│  │  ┌─ Chromium 路线 ──────────────────────────────────────────┐ │     │
│  │  │                                                          │ │     │
│  │  │  方案 A: nodriver 启动 (最轻量)                          │ │     │
│  │  │  browser = await Browser.create(headless=False, port=9222)│ │     │
│  │  │  ・无 WebDriver → 最小暴露面                             │ │     │
│  │  │  ・暴露 CDP: ws://localhost:9222                         │ │     │
│  │  │                                                          │ │     │
│  │  │  方案 B: Scrapling 启动 (最强反检测) ← 需小改造          │ │     │
│  │  │  session = StealthySession(headless=False)               │ │     │
│  │  │  cdp_url = session.get_cdp_url()  # 暴露 CDP 端口       │ │     │
│  │  │  ・Patchright 95 条隐匿参数                              │ │     │
│  │  │  ・Canvas 噪声 + WebRTC 阻断 + CF 求解                  │ │     │
│  │  │                                                          │ │     │
│  │  └──────────────────────────────���───────────────────────────┘ │     │
│  │                                                                │     │
│  │  ┌─ Firefox 路线 ──────────────────────────────────────────┐  │     │
│  │  │  Camoufox (独立运行, 无法 CDP 共享)                      │  │     │
│  │  │  ・38 个 C++ 补丁 → 指纹伪装最强                        │  │     │
│  │  │  ・通过 Playwright API 直接控制                          │  │     │
│  │  │  ・无法接入 browser-use (无 CDP)                         │  │     │
│  │  └──────────────────────────────────────────────────────────┘  │     │
│  └──────────────────────┬──────────────────────────────���──────────┘     │
│                         │ CDP: ws://localhost:9222                       │
│                         │ (Chromium 路线)                                │
│  ┌──────────────────────↓─────────────────────────────────────────┐     │
│  │  第 1 层: 智能路由层 (Orchestrator)                             │     │
│  │                                                                │     │
│  │  输入: URL + 任务描述                                          │     │
│  │    │                                                           │     │
│  │    ├── 页面结构已知？ ──→ 是 ──→ 第 2 层: 脚本直取 (零 token)  │     │
│  │    │                                                           │     │
│  │    ├── 需要 JS 渲染但结构简单？ ──→ 第 3 层: Scrapling 解析    │     │
│  │    │                                                           │     │
│  │    ├── 需要复杂交互？ ──→ 第 4 层: AI Agent (browser-use)      │     │
│  │    │                                                           │     │
│  │    └── 纯 API 请求？ ──→ 第 5 层: curl_cffi HTTP (最快)       │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  第 2 层: 脚本直取 (零 LLM 成本, 毫秒级)                      │     │
│  │                                                                │     │
│  │  nodriver tab.evaluate() / Playwright page.evaluate()         │     │
│  │  ・已知 CSS 选择器直接提取                                     │     │
│  │  ・零 token 消耗                                               │     │
│  │  ・复用同一浏览器实例                                          │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  第 3 层: Scrapling 解析 (零 LLM 成本, 强力解析)               │     │
│  │                                                                │     │
│  │  StealthyFetcher.fetch(url, cdp_url="ws://localhost:9222")    │     │
│  │  ・复用同一浏览器 (通过 CDP)                                   │     │
│  │  ・CSS/XPath/自适应选择器                                      │     │
│  │  ・自动处理 Cloudflare                                         │     │
│  │  ・零 token 消耗                                               │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  第 4 层: AI Agent (仅在必要时启用, 优化 token)                 │     │
│  │                                                                │     │
│  │  session = BrowserSession(cdp_url="ws://localhost:9222")      │     │
│  │  agent = Agent(                                               │     │
│  │      task="...",                                              │     │
│  │      llm=Gemini_Flash,            # 廉价模型优先              │     │
│  │      use_vision=False,            # 关闭截图省 token          │     │
│  │      include_attributes=[精简],   # 最少 DOM 属性             │     │
│  │      max_input_tokens=8000,       # 限制上下文                │     │
│  │      max_actions_per_step=10,     # 批量操作                  │     │
│  │  )                                                            │     │
│  │  ・复用同一浏览器 (通过 CDP)                                   │     │
│  │  ・继承启动层的所有反检测配置                                   │     │
│  │  ・LLM 驱动的类人行为                                          │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌───────────────��────────────────────────────────────────────────┐     │
│  │  第 5 层: curl_cffi HTTP 直请求 (最快, 零浏览器开销)           │     │
│  │                                                                │     │
│  │  Scrapling StealthyRequests(impersonate="chrome120")          │     │
│  │  ・TLS 指纹伪装 (JA3/JA4)                                     │     │
│  │  ・可注入浏览器 Cookie                                         │     │
│  │  ・适合 API 端点批量请求                                       │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  横切关注点                                                    │     │
│  │                                                                │     │
│  │  ・速率控制: 5-15 秒间隔 + 会话休息 + 每日限量                │     │
│  │  ・验证码处理: nodriver verify_cf / botright / YesCaptcha     │     │
│  │  ・可视化: headless=False + macOS 屏幕共享 / VNC              │     │
│  │  ・住宅 IP: 家庭宽带直出 (天然高信誉)                         │     │
│  └────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
```

### 12.3 各层能力互补矩阵

```
                    隐匿启动  指纹伪装  TLS伪装  行为模拟  Token成本  速度
                    ────────  ────────  ───────  ───────  ────────  ────
第0层 nodriver      ★★★      ★         ★        ★        零        快
第0层 Scrapling启动  ★★★★     ★★★      ★        ★        零        快
第0层 Camoufox      ★★★★★    ★★★★★    ★★★     ★        零        中
第2层 脚本直取       -         -         -        -        零        极快
第3层 Scrapling解析  -         -         -        ★        零        快
第4层 AI Agent      -         -         -        ★★★★★   高(可优化)  慢
第5层 curl_cffi     -         -         ★★★★    -        零        极快

组合后:             ★★★★     ★★★      ★★★★    ★★★★★   低        自适应
```

### 12.4 关键改造: Scrapling 暴露 CDP 端口

**改动量**: 仅需在 `StealthySession` 中添加一个方法（约 5 行代码）

**文件**: `Scrapling/scrapling/engines/_browsers/_stealth.py`

```python
# 需要添加的方法:
class StealthySession:
    # ... 现有代码 ...

    def get_cdp_url(self) -> str:
        """暴露 CDP WebSocket URL, 供 browser-use 等外部工具连接"""
        if self._config.cdp_url:
            return self._config.cdp_url
        if hasattr(self, 'browser') and self.browser:
            # Patchright/Playwright 的 Browser 对象提供此方法
            endpoints = self.browser.contexts[0].browser.new_browser_cdp_session()
            # 或直接从启动参数获取 debugging port
            return f"ws://127.0.0.1:{self._debug_port}"
        raise RuntimeError("No browser session available")
```

### 12.5 统一架构完整代码

```python
import asyncio
import random
from typing import Optional, Any

class UnifiedBrowserController:
    """
    统一浏览器控制架构
    ・一个浏览器实例, 多个控制层共享
    ・脚本优先, AI 兜底 → 最低 token 成本
    ・反检测能力来自启动层, 所有层自动继承
    """

    def __init__(self, headless=False, captcha_key=None):
        self.headless = headless
        self.captcha_key = captcha_key
        self.browser = None
        self.cdp_url = None
        self.rate_limiter = RateLimiter()

    # ─── 第 0 层: 隐匿启动 ──────────────────────────

    async def start_with_nodriver(self):
        """nodriver 启动 (最轻量, 推荐)"""
        import nodriver as uc
        self.browser = await uc.Browser.create(
            headless=self.headless,
            port=9222,
            browser_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--lang=zh-CN",
                "--window-size=1920,1080",
            ],
        )
        self.cdp_url = f"http://localhost:9222"
        return self

    async def start_with_scrapling(self):
        """Scrapling 启动 (更强反检测, 需小改造)"""
        from scrapling import StealthySession
        self.session = StealthySession(
            headless=self.headless,
            hide_canvas=True,
            block_webrtc=True,
        )
        await self.session.start()
        self.cdp_url = self.session.get_cdp_url()  # 需要的改造
        return self

    # ─── 第 2 层: 脚本直取 (零 token) ──────────────

    async def script_extract(self, url: str, js_code: str) -> Any:
        """已知页面结构 → JS 直接提取, 零 LLM 成本"""
        await self.rate_limiter.wait()
        tab = await self.browser.get(url)
        await asyncio.sleep(random.uniform(2, 5))
        return await tab.evaluate(js_code)

    # ─── 第 3 层: Scrapling 解析 (零 token) ────────

    async def scrapling_fetch(self, url: str) -> 'Response':
        """复用浏览器, Scrapling 强力解析"""
        await self.rate_limiter.wait()
        from scrapling import StealthyFetcher
        return StealthyFetcher.fetch(url, cdp_url=self.cdp_url)

    # ─── 第 4 层: AI Agent (仅在必要时) ────────────

    async def ai_agent(self, task: str, model="gpt-4o-mini") -> Any:
        """复杂交互 → AI Agent 接管, 优化 token"""
        from browser_use import Agent, BrowserSession
        from langchain_openai import ChatOpenAI

        session = BrowserSession(cdp_url=self.cdp_url)
        agent = Agent(
            task=task,
            llm=ChatOpenAI(model=model),
            browser_session=session,
            # ── Token 优化配置 ──
            use_vision=False,
            include_attributes=['aria-label', 'placeholder', 'role', 'title'],
            max_input_tokens=8000,
            max_actions_per_step=10,
        )
        return await agent.run(max_steps=20)

    # ─── 第 5 层: HTTP 直请求 (最快) ──────────────

    async def http_fetch(self, url: str, cookies=None) -> Any:
        """纯 HTTP + TLS 伪装, 零浏览器开销"""
        from curl_cffi import requests
        return requests.get(
            url,
            impersonate="chrome120",
            cookies=cookies,
        )

    # ─── 智能路由 ─────────────────────────────────

    async def smart_scrape(self, url: str, selectors: dict = None,
                           task: str = None) -> Any:
        """
        智能路由: 自动选择最优层
        ・有 selectors → 脚本直取 (零 token)
        ・无 selectors 但有 task → AI Agent (优化 token)
        ・API 端点 → HTTP 直请求 (最快)
        """
        # API 端点 → 直接 HTTP
        if "/api/" in url or "/wapi/" in url:
            cookies = await self._export_cookies()
            return await self.http_fetch(url, cookies)

        # 有已知选择器 → 脚本直取
        if selectors:
            js = self._build_extract_js(selectors)
            return await self.script_extract(url, js)

        # 先尝试 Scrapling 解析
        try:
            resp = await self.scrapling_fetch(url)
            if resp.status == 200 and len(resp.text) > 100:
                return resp
        except Exception:
            pass

        # 兜底: AI Agent
        if task:
            return await self.ai_agent(task)

        raise ValueError("需要提供 selectors 或 task")

    def _build_extract_js(self, selectors: dict) -> str:
        """将选择器字典转为 JS 提取代码"""
        fields = ", ".join(
            f"'{k}': el.querySelector('{v}')?.textContent?.trim()"
            for k, v in selectors.items()
        )
        container = selectors.get('_container', '*')
        return f"""
            () => Array.from(document.querySelectorAll('{container}'))
                .map(el => ({{ {fields} }}))
                .filter(item => Object.values(item).some(v => v))
        """

    async def _export_cookies(self) -> dict:
        """从浏览器导出 Cookie 给 HTTP 层使用"""
        tab = list(self.browser.tabs)[0] if self.browser else None
        if tab:
            cookies = await tab.evaluate("""
                () => document.cookie.split(';').reduce((acc, c) => {
                    const [k, v] = c.trim().split('=');
                    acc[k] = v;
                    return acc;
                }, {})
            """)
            return cookies
        return {}


class RateLimiter:
    """住宅 IP 专用速率控制"""
    def __init__(self):
        self.count = 0
    async def wait(self):
        self.count += 1
        if self.count % 30 == 0:
            await asyncio.sleep(random.uniform(600, 1200))  # 10-20分钟休息
        else:
            await asyncio.sleep(random.uniform(5, 15))
```

### 12.6 Boss 直聘实战示例

```python
async def scrape_boss_unified():
    # 启动: nodriver 隐匿浏览器 (可视化, 住宅 IP 直出)
    ctrl = UnifiedBrowserController(headless=False)
    await ctrl.start_with_nodriver()

    # ── 场景 1: 已知结构的职位列表 → 脚本直取 (零 token) ──
    jobs = await ctrl.smart_scrape(
        url="https://www.zhipin.com/web/geek/job?query=Python",
        selectors={
            '_container': '.job-card-wrapper',
            'title': '.job-name',
            'company': '.company-name',
            'salary': '.salary',
            'location': '.job-area',
        },
    )
    print(f"脚本提取: {len(jobs)} 个职位, 零 token 消耗")

    # ── 场景 2: 需要登录 → AI Agent 接管 (少量 token) ──
    await ctrl.smart_scrape(
        url="https://www.zhipin.com/web/user/login",
        task="扫描页面上的登录二维码区域并等待用户扫码登录完成",
    )
    # 预估成本: ~$0.02 (廉价模型 + 优化配置)

    # ── 场景 3: 职位详情 API → HTTP 直请求 (零 token, 最快) ──
    for job_id in job_ids:
        detail = await ctrl.smart_scrape(
            url=f"https://www.zhipin.com/wapi/zpgeek/job/detail?securityId={job_id}",
        )
        # curl_cffi TLS 伪装, 复用浏览器 Cookie
```

### 12.7 成本对比

```
┌──────────────────────────────────────────────────��─────┐
│     统一架构 vs 纯 AI Agent 成本对比                     │
│                                                        │
│  场景: 采集 Boss 直聘 1000 个职位                       │
│                                                        │
│  纯 browser-use AI Agent (未优化):                      │
│  ・每页 LLM 调用: ~5000 tokens × 3 步                  │
│  ・1000 页 × $0.30/页 = $300                           │
│                                                        │
│  统一架构:                                              │
│  ├── 900 页已知结构 → 脚本直取: $0                     │
│  ├── 50 页需要交互 → AI Agent (优化): 50 × $0.03 = $1.5│
│  ├── 50 页异常/验证码 → AI Agent: 50 × $0.05 = $2.5   │
│  └── API 端点批量 → curl_cffi: $0                      │
│                                                        │
│  总计: $4 vs $300 — 节省 98.7%                         │
│                                                        │
│  同时获得:                                              │
│  ✓ Scrapling/nodriver 的反检测能力                     │
│  ✓ browser-use 的 AI 类人行为 (仅在需要时)             │
│  ✓ curl_cffi 的 TLS 伪装                               ��
│  ✓ 可视化运行 + 住宅 IP                                │
└────────────────────────────────────────────────────────┘
```

### 12.8 Camoufox Firefox 路线的统一架构变体

Camoufox 无法通过 CDP 与 browser-use 共享，但可以采用类似分层思想：

```python
async def camoufox_unified(url, selectors=None, task=None):
    """Firefox 路线的统一架构 — 通过 Playwright API 而非 CDP"""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=False, os="windows") as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")

        # 脚本直取 (零 token)
        if selectors:
            js = build_extract_js(selectors)
            return await page.evaluate(js)

        # Playwright 原生操作 (零 token)
        if task == "simple_navigation":
            await page.click("selector")
            return await page.content()
```

### 12.9 browser-use 内部优化深度配置

基于源码分析的 browser-use 高级优化配置，最大限度降低 token 消耗：

#### browser-use 关键扩展点

| 扩展点 | 文件 | 优化效果 |
|--------|------|---------|
| **自定义零 token Action** | `tools/service.py` | 注册 CSS 选择器提取 Action，绕过 LLM |
| **DOM 属性过滤** | `agent/views.py` | `include_attributes` 减少 DOM 序列化 |
| **消息压缩** | `agent/views.py` | `message_compaction` 自动压缩历史 |
| **iframe 跳过** | `dom/service.py` | `max_iframes=0` 跳过 iframe 处理 |
| **绘制顺序跳过** | `dom/service.py` | `paint_order_filtering=False` 省 CPU |
| **视口阈值** | `dom/service.py` | `viewport_threshold=None` 减少计算 |

#### 自定义零 Token 数据提取 Action

browser-use 的 `Tools` 支持 `@action` 装饰器注册自定义操作。注册一个 CSS 选择器提取 Action 可以完全跳过 LLM 调用：

```python
from browser_use.tools.service import Tools

# 注册自定义零 token 提取 Action
@tools.registry.action(
    'Extract data using CSS selectors - no LLM needed, instant result'
)
async def css_extract(params, browser_session):
    """零 token: 纯 JS 执行，不经过 LLM"""
    cdp = browser_session._cdp_client
    result = await cdp.send.Runtime.evaluate(params={
        'expression': f"""
            Array.from(document.querySelectorAll('{params.container}'))
            .map(el => ({{
                {', '.join(f"'{k}': el.querySelector('{v}')?.textContent?.trim()"
                           for k, v in params.fields.items())}
            }}))
        """,
        'returnByValue': True,
    })
    return result
```

#### 消息压缩配置（防止 token 膨胀）

```python
from browser_use.agent.views import AgentSettings, MessageCompactionSettings

settings = AgentSettings(
    message_compaction=MessageCompactionSettings(
        enabled=True,
        compact_every_n_steps=5,      # 每 5 步压缩一次历史
        trigger_token_count=5000,     # 5000 token 触发压缩
        keep_last_items=3,            # 只保留最近 3 条
    ),
)
```

#### 极简 Agent 配置（最低 token 消耗）

```python
agent = Agent(
    task="...",
    llm=llm,
    browser_session=session,

    # ── Token 极限优化 ──
    use_vision=False,                    # 不发送截图 (省 1000-3000 token/步)
    use_thinking=False,                  # 不生成推理过程 (省输出 token)
    enable_planning=False,               # 不生成计划 (省输出 token)

    # ── DOM 精简 ──
    include_attributes=['id', 'class', 'href'],  # 最少属性
    max_clickable_elements_length=8000,           # 限制可点击元素列表

    # ── 上下文管理 ──
    max_input_tokens=8000,               # 强制限制输入 token
    max_error_length=200,                # 限制错误信息长度

    # ── 效率 ──
    max_actions_per_step=10,             # 批量操作减少轮次
)
```

### 12.10 完整的高性能方案代码

```python
"""
高性能浏览器控制方案
・一个浏览器实例, 多层控制共享 CDP
・脚本优先 (90% 零 token), AI 兜底 (10% 低 token)
・nodriver 隐匿启动 + browser-use AI + Scrapling 解析 + curl_cffi HTTP
・可视化运行 + 住宅 IP 直出
"""

import asyncio
import random
import nodriver as uc
from typing import Optional, Any, Dict, List

class StealthBrowserController:
    """
    统一浏览器控制器
    ・反检测: nodriver 无 WebDriver + Chrome 隐匿参数
    ・AI 能力: browser-use Agent (仅在需要时启用, 优化 token)
    ・解析: CSS/XPath 脚本直取 (零 token)
    ・HTTP: curl_cffi TLS 伪装 (零浏览器开销)
    ・可视化: headless=False + VNC 远程查看
    ・住宅 IP: 家庭宽带直出
    """

    def __init__(self, headless=False):
        self.headless = headless
        self.browser = None
        self.cdp_port = 9222
        self.request_count = 0

    # ═══ 启动层 ═══

    async def start(self):
        """nodriver 隐匿启动浏览器"""
        self.browser = await uc.Browser.create(
            headless=self.headless,
            port=self.cdp_port,
            browser_args=[
                "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--lang=zh-CN",
                "--force-color-profile=srgb",
                "--font-render-hinting=none",
            ],
        )
        print(f"浏览器已启动, CDP: http://localhost:{self.cdp_port}")
        return self

    # ═══ 脚本直取层 (零 token) ═══

    async def extract(self, url: str, container: str,
                      fields: Dict[str, str]) -> List[dict]:
        """
        CSS 选择器直取 — 零 LLM token 消耗
        container: 容器选择器 (如 '.job-card-wrapper')
        fields: {字段名: CSS选择器} (如 {'title': '.job-name'})
        """
        await self._rate_limit()
        tab = await self.browser.get(url)
        await asyncio.sleep(random.uniform(2, 5))

        # 模拟人类滚动
        for _ in range(random.randint(1, 3)):
            await tab.evaluate(f"window.scrollBy(0, {random.randint(200,500)})")
            await asyncio.sleep(random.uniform(0.5, 2))

        # JS 直取
        field_js = ", ".join(
            f"'{k}': el.querySelector('{v}')?.textContent?.trim()"
            for k, v in fields.items()
        )
        result = await tab.evaluate(f"""
            Array.from(document.querySelectorAll('{container}'))
            .map(el => ({{ {field_js} }}))
            .filter(item => Object.values(item).some(v => v))
        """)
        return result

    # ═══ AI Agent 层 (低 token, 仅在需要时) ═══

    async def ai_interact(self, task: str,
                          model: str = "gpt-4o-mini",
                          max_steps: int = 15) -> Any:
        """
        AI Agent 接管 — 仅用于脚本无法处理的场景
        ・自动连接到已启动的隐匿浏览器
        ・最低 token 配置
        """
        from browser_use import Agent, BrowserSession
        from langchain_openai import ChatOpenAI

        session = BrowserSession(
            cdp_url=f"http://localhost:{self.cdp_port}",
        )

        agent = Agent(
            task=task,
            llm=ChatOpenAI(model=model),
            browser_session=session,
            # Token 极限优化
            use_vision=False,
            include_attributes=['aria-label', 'placeholder', 'role', 'title'],
            max_input_tokens=8000,
            max_actions_per_step=10,
        )
        return await agent.run(max_steps=max_steps)

    # ═══ HTTP 直请求层 (零浏览器开销) ═══

    async def http_get(self, url: str, cookies: dict = None) -> Any:
        """curl_cffi TLS 伪装 HTTP 请求 — 零浏览器开销"""
        from curl_cffi import requests
        return requests.get(url, impersonate="chrome120", cookies=cookies)

    # ═══ Cookie 管理 ═══

    async def export_cookies(self) -> dict:
        """导出浏览器 Cookie 给 HTTP 层使用"""
        tab = list(self.browser.tabs)[0]
        return await tab.evaluate("""
            () => document.cookie.split(';').reduce((acc, c) => {
                const [k, ...v] = c.trim().split('=');
                acc[k] = v.join('=');
                return acc;
            }, {})
        """)

    # ═══ CF 绕过 ═══

    async def bypass_cloudflare(self, url: str):
        """nodriver 内置 Cloudflare 验证码绕过"""
        tab = await self.browser.get(url)
        try:
            await tab.verify_cf()
        except Exception:
            pass
        await asyncio.sleep(3)
        return tab

    # ═══ 速率控制 ═══

    async def _rate_limit(self):
        self.request_count += 1
        if self.request_count % 30 == 0:
            rest = random.uniform(10, 20)
            print(f"会话休息 {rest:.0f} 分钟...")
            await asyncio.sleep(rest * 60)
        delay = random.uniform(5, 15)
        if random.random() < 0.15:
            delay += random.uniform(15, 45)
        await asyncio.sleep(delay)

    # ═══ 清理 ═══

    async def close(self):
        if self.browser:
            self.browser.stop()


# ═══ 使用示例 ═══

async def main():
    ctrl = StealthBrowserController(headless=False)
    await ctrl.start()

    # 1. 脚本直取 (零 token) — 90% 的场景
    jobs = await ctrl.extract(
        url="https://www.zhipin.com/web/geek/job?query=Python",
        container=".job-card-wrapper",
        fields={
            "title": ".job-name",
            "company": ".company-name",
            "salary": ".salary",
            "location": ".job-area",
        },
    )
    print(f"提取 {len(jobs)} 个职位 (零 token)")

    # 2. AI Agent (低 token) — 仅在需要时
    await ctrl.ai_interact(
        task="点击第一个职位查看详情，记录公司描述和岗位要求",
        model="gpt-4o-mini",
        max_steps=10,
    )

    # 3. HTTP 批量 (零浏览器开销) — API 端点
    cookies = await ctrl.export_cookies()
    for job_id in ["123", "456"]:
        resp = await ctrl.http_get(
            f"https://www.zhipin.com/wapi/zpgeek/job/detail?jobId={job_id}",
            cookies=cookies,
        )

    await ctrl.close()

asyncio.run(main())
```

### 12.11 Docker + noVNC 可视化部署

```dockerfile
# Dockerfile
FROM python:3.12-slim

# 显示 + VNC
RUN apt-get update && apt-get install -y \
    xvfb x11vnc novnc websockify fluxbox \
    wget gnupg2 fonts-noto-cjk libnss3 libxss1 \
    libasound2 libatk-bridge2.0-0 libgtk-3-0 libgbm1

# Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Python 依赖
RUN pip install nodriver scrapling[all] browser-use "camoufox[geoip]" \
    DrissionPage botright

COPY start.sh /start.sh
COPY scraper.py /app/scraper.py
EXPOSE 5900 6080

CMD ["/start.sh"]
```

```bash
# start.sh
#!/bin/bash
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
fluxbox &
x11vnc -display :99 -forever -nopw -shared -rfbport 5900 &
websockify --web /usr/share/novnc 6080 localhost:5900 &
echo "noVNC: http://localhost:6080/vnc.html"
python /app/scraper.py
```

```bash
# 运行 (Mac)
docker build -t stealth-scraper .
docker run -d -p 5900:5900 -p 6080:6080 \
    -v $(pwd)/data:/app/data \
    --name scraper stealth-scraper

# 查看浏览器: 打开 http://localhost:6080/vnc.html
```

---

## 十三、AI Agent Token 优化详细配置

### 13.1 核心问题

browser-use 每一步都要向 LLM 发送：页面 DOM 快照 + 对话历史 + 系统提示。一个 20 步任务可能消耗 **10 万+ token**，成本 $0.15-$0.50/任务。

**各种输入方式的 Token 成本对比**:

| 输入类型 | 每页 Token 数 | GPT-4o 单页成本 |
|---------|-------------|-----------------|
| 原始 HTML | 50,000-200,000 | $0.125-$0.50 |
| 清洗后 HTML | 5,000-20,000 | $0.012-$0.05 |
| 无障碍树 (browser-use 默认) | 2,000-10,000 | $0.005-$0.025 |
| ASCII 线框 (agent-browser 方案) | 200-400 | $0.0005-$0.001 |
| 纯文本提取 | 1,000-5,000 | $0.0025-$0.012 |

### 13.2 最高优先级优化（按影响力排序）

#### 优化 1: 混合架构 — AI 只处理难题（节省 50-85% 成本）

**这是最重要的一条**: 不要让 AI Agent 做所有事。对已知结构的页面用脚本，只有未知/动态页面才用 AI。

```
┌──────────────────────────────────────────────────────────┐
│            混合架构: 脚本 + AI Agent                      │
│                                                          │
│  输入 URL                                                │
│    │                                                     │
│    ├── 页面结构已知？                                     │
│    │   │                                                 │
│    │   ├── 是 → 脚本化 Playwright/nodriver 直接操作       │
│    │   │       ・零 LLM 成本                             │
│    │   │       ・CSS/XPath 选择器提取                     │
│    │   │       ・速度: 毫秒级                            │
│    │   │                                                 │
│    │   └── 否 → Q2: 复杂度如何？                         │
│    │           │                                         │
│    │           ├── 简单决策 → 廉价模型                    │
│    │           │   Gemini Flash / Claude Haiku            │
│    │           │   成本: $0.01-$0.05/任务                 │
│    │           │                                         │
│    │           └── 复杂交互 → 强力模型                    │
│    │               Claude Sonnet / GPT-4o                │
│    │               成本: $0.15-$0.50/任务                │
│    └─────────────────────────────────────────────────────│
│                                                          │
│  实际案例: 10M 页采集                                    │
│  ・纯 AI: $0.06/页 = $60/千页                           │
│  ・混合后: $0.008/页 = $8/千页 (节省 87%)               │
└──────────────────────────────────────────────────────────┘
```

**Boss 直聘混合架构代码**:
```python
async def smart_scrape_boss(url, page):
    """混合架构: 已知结构用脚本, 异常时才启用 AI"""

    # 尝试脚本化提取 (零 LLM 成本)
    try:
        jobs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('.job-card-wrapper'))
                .map(card => ({
                    title: card.querySelector('.job-name')?.textContent?.trim(),
                    company: card.querySelector('.company-name')?.textContent?.trim(),
                    salary: card.querySelector('.salary')?.textContent?.trim(),
                }))
        """)
        if jobs and len(jobs) > 0:
            return jobs  # 成功 → 零成本
    except Exception:
        pass

    # 脚本失败 (页面结构变化/验证码/异常) → AI Agent 接管
    agent = Agent(
        task=f"提取当前页面上的所有职位信息",
        llm=ChatOpenAI(model="gpt-4o-mini"),  # 用廉价模型
        browser_session=session,
        use_vision=False,           # 不用截图, 省 token
        max_actions_per_step=10,    # 批量操作
    )
    return await agent.run(max_steps=5)
```

#### 优化 2: 关闭 Vision 模式（节省 30-50%/步）

```python
agent = Agent(
    task="...",
    llm=llm,
    use_vision=False,   # 关键: 不发送截图, 仅用文本 DOM
    # 截图每步额外消耗 1,000-3,000 image token
    # 对于表单填写/数据提取, 文本 DOM 完全够用
)
```

**何时需要打开 Vision**:
- CAPTCHA 需要图像识别
- Canvas 渲染的 UI
- 需要依据视觉位置判断的场景

#### 优化 3: 精简 DOM 属性（节省 30-50% 文本 token）

```python
agent = Agent(
    task="...",
    llm=llm,
    # 默认发送 10 个属性: alt, aria-label, placeholder, role,
    #   title, type, value, name, href, src
    # 精简为任务所需的最少属性:
    include_attributes=['aria-label', 'placeholder', 'role', 'title'],
    # 200 个元素 × 去掉 6 个属性 ≈ 大幅减少 token
)
```

#### 优化 4: 限制上下文长度（防止历史膨胀）

```python
agent = Agent(
    task="...",
    llm=llm,
    max_input_tokens=10000,  # 超过后自动丢弃最旧消息
    max_error_length=400,    # 限制错误信息长度
    # 没有此限制, 20 步任务的最后几步可能发送 50k+ token
)
```

#### 优化 5: Prompt 缓存（Anthropic 模型专属）

```python
from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(model_name="claude-sonnet-4-5-20250514")

agent = Agent(
    task="...",
    llm=llm,
    use_prompt_caching=True,  # 系统提示缓存 5 分钟
    # 缓存命中时, 系统提示部分成本降低 90%
    # 连续运行多个任务时效果最佳
)
```

### 13.3 模型选择策略

| 模型 | 能力 | 成本 | 推荐场景 |
|------|------|------|---------|
| Claude Sonnet 4 | ★★★★★ | 高 | 复杂多步骤任务 |
| GPT-4o | ★★★★ | 高 | 快速响应场景 |
| **Gemini 2.0 Flash** | ★★★ | **低** | **最佳性价比, 日常任务首选** |
| GPT-4o-mini | ★★★ | 低 | 简单导航/点击 |
| Claude Haiku | ★★ | 极低 | 大批量简单任务 |
| Qwen2.5:32B (本地) | ★★★ | 接近 0 | 本地部署, 无 API 费用 |

**社区共识**: 日常任务用 **Gemini 2.0 Flash**（性价比最高），复杂任务才用 Claude Sonnet。

### 13.4 批量操作优化

```python
agent = Agent(
    task="...",
    llm=llm,
    max_actions_per_step=10,  # 每次 LLM 调用可执行 10 个动作
    # 高值 → 更少 LLM 调用 (省钱) 但出错恢复慢
    # 低值 → 更多 LLM 调用 (贵) 但每步可纠错
    #
    # 建议:
    # 已知稳定页面: max_actions_per_step=15
    # 未知/动态页面: max_actions_per_step=3-5
)
```

### 13.5 Boss 直聘完整优化配置

```python
from browser_use import Agent, BrowserSession
from langchain_openai import ChatOpenAI

# 日常采集: 用廉价模型 + 最大优化
agent = Agent(
    task="在 Boss 直聘搜索 Python 岗位, 提取前 3 页结果",
    llm=ChatOpenAI(model="gpt-4o-mini"),  # 廉价模型

    # Token 优化
    use_vision=False,                      # 不用截图
    include_attributes=['aria-label', 'placeholder', 'role', 'title'],
    max_input_tokens=8000,                 # 限制上下文
    max_error_length=300,

    # 效率优化
    max_actions_per_step=10,               # 批量操作

    # 行为控制
    browser_session=BrowserSession(
        headless=False,                    # 可视化
    ),
)

# 预估成本: ~$0.03-$0.08/任务 (vs 未优化 $0.30-$0.50)
```

### 13.6 成本优化效果总览

```
┌────────────────────────────────────────────────────┐
│         优化前 vs 优化后成本对比                     │
│                                                    │
│  未优化 (GPT-4o + Vision + 全属性):                │
│  ・每步: ~5,000-15,000 tokens                      │
│  ・20 步任务: ~$0.30-$0.50                         │
│  ・1000 页采集: ~$150-$500                         │
│                                                    │
│  全面优化后:                                       │
│  ├── 混合架构 (85% 脚本化):     -85%              │
│  ├── 关闭 Vision:               -40%              │
│  ├── 精简属性:                  -35%              │
│  ├── 廉价模型 (Gemini Flash):   -80%              │
│  ├── Prompt 缓存:               -20%              │
│  └── 批量操作:                  -30%              │
│                                                    │
│  优化后每任务: ~$0.01-$0.05                        │
│  优化后 1000 页: ~$8-$30                           │
│                                                    │
│  综合节省: ~90-95%                                 │
└────────────────────────────────────────────────────┘
```
