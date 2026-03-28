"""
工业级 CDP 隐匿组合：
  ① CloakBrowser（C++ 编译级指纹，via pip install cloakbrowser）
  ② patchright（驱动级修补 —— 移除 __playwright__binding__ / navigator.webdriver）
  ③ REBROWSER_PATCHES_RUNTIME_FIX_MODE=addBinding（CDP Runtime.Enable 泄漏修复）
  ④ 非标准端口 19222 绑定 127.0.0.1（连接隐匿）
  ⑤ 禁止频繁 attach/detach（持久单会话）

集成方式：
  - CloakBrowser Python API (cloakbrowser.ensure_binary()) 定位二进制路径
  - patchright 通过 executable_path 启动 CloakBrowser
  - REBROWSER_PATCHES_RUNTIME_FIX_MODE 环境变量激活 Runtime.Enable 修复
  - 两者在不同层工作，互不干扰
"""
import asyncio
import os
import logging
from typing import Optional, Tuple

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

from patchright.async_api import async_playwright, Playwright, Browser

logger = logging.getLogger(__name__)

CDP_PORT = int(os.getenv("CDP_PORT", "19222"))


def get_cloakbrowser_path() -> str:
    """获取 CloakBrowser 二进制路径，自动下载（如未安装）"""
    # 优先使用环境变量（Docker / 手动指定场景）
    env_path = os.getenv("CLOAKBROWSER_PATH", "")
    if env_path and os.path.exists(env_path):
        logger.info(f"Using CloakBrowser from CLOAKBROWSER_PATH: {env_path}")
        return env_path

    # 使用 cloakbrowser Python 包自动定位/下载
    try:
        import cloakbrowser
        path = cloakbrowser.ensure_binary()
        logger.info(f"CloakBrowser binary: {path}")
        return path
    except ImportError:
        raise RuntimeError(
            "CloakBrowser not found. Install with: pip install cloakbrowser\n"
            "Or set CLOAKBROWSER_PATH env var to the binary path."
        )


def _build_launch_args(
    cdp_port: int = None,
    proxy: Optional[str] = None,
    extra_args: Optional[list] = None
) -> list:
    if cdp_port is None:
        cdp_port = CDP_PORT

    args = [
        # ── 连接隐匿 ──
        f"--remote-debugging-port={cdp_port}",
        f"--remote-debugging-address={os.getenv('CDP_BIND_ADDRESS', '127.0.0.1')}",
        "--remote-allow-origins=*",

        # ── 环境适配 ──
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--window-position=0,0",
        "--start-maximized",
        "--disable-infobars",          # 隐藏信息栏（包括命令行标记警告）
        "--no-default-browser-check",  # 不弹出默认浏览器提示

        # ── WebRTC 泄漏防护 ──
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--enforce-webrtc-ip-permission-check",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",

        # ── 自动化信号抑制 ──
        "--disable-ipc-flooding-protection",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-hang-monitor",
        "--disable-client-side-phishing-detection",
        "--disable-domain-reliability",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-breakpad",
        "--metrics-recording-only",
        "--no-pings",
        "--font-render-hinting=medium",
        "--disable-features="
        "TranslateUI,"
        "ImprovedCookieControls,"
        "LazyFrameLoading,"
        "GlobalMediaControls,"
        "DestroyProfileOnBrowserClose,"
        "MediaRouter,"
        "DialMediaRouteProvider,"
        "AcceptCHFrame,"
        "AutoExpandDetailsElement,"
        "CertificateTransparencyComponentUpdater,"
        "AvoidUnnecessaryBeforeUnloadCheckSync,"
        "Translate,"
        "HttpsUpgrades,"
        "PaintHolding",
    ]
    if proxy:
        args.append(f"--proxy-server={proxy}")
    if extra_args:
        args.extend(extra_args)
    return args


async def launch_stealth_browser(
    headless: bool = False,
    proxy: Optional[str] = None,
    extra_args: Optional[list] = None,
    user_data_dir: Optional[str] = None,
    cdp_port: Optional[int] = None,
) -> Tuple[Playwright, Browser, str]:
    """
    启动 CloakBrowser（C++ 指纹）via patchright（驱动级修补）。

    支持持久化 Profile（可选）：
    - 方式1：设置环境变量 PROFILE_STORAGE 指定 Profile 目录
    - 方式2：直接传递 user_data_dir 参数（优先级更高）
    - 登录状态、密码、cookies 将保留在该目录中
    - 重启容器后仍然有效

    Args:
        headless: 是否无头模式
        proxy: 代理服务器地址
        extra_args: 额外的启动参数
        user_data_dir: 用户数据目录（优先级高于 PROFILE_STORAGE）
        cdp_port: CDP 端口（默认 19222）

    Returns:
        (playwright, browser, cdp_url)
        cdp_url 用于 browser-use BrowserSession(cdp_url=...)
    """
    binary_path = get_cloakbrowser_path()

    # 获取 CloakBrowser 推荐的 stealth 启动参数
    try:
        import cloakbrowser as cb
        stealth_args = cb.get_default_stealth_args()
    except Exception:
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
        ]

    # 持久化 Profile 支持（可选）
    # 优先级：user_data_dir 参数 > PROFILE_STORAGE 环境变量
    profile_dir = user_data_dir or os.getenv('PROFILE_STORAGE')
    if profile_dir:
        # 创建 Profile 目录
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)
        logger.info(f"✅ Using persistent profile: {profile_dir}")

        # 隐藏书签栏 + 不弹出恢复页面提示
        import json as _json
        default_dir = os.path.join(profile_dir, "Default")
        os.makedirs(default_dir, exist_ok=True)
        prefs_path = os.path.join(default_dir, "Preferences")
        prefs = {}
        if os.path.exists(prefs_path):
            try:
                with open(prefs_path) as f:
                    prefs = _json.load(f)
            except Exception:
                pass
        prefs.setdefault("bookmark_bar", {})["show_on_all_tabs"] = False
        prefs.setdefault("profile", {})["exit_type"] = "Normal"
        prefs.setdefault("profile", {})["exited_cleanly"] = True
        with open(prefs_path, "w") as f:
            _json.dump(prefs, f)
    else:
        logger.info("ℹ️  Using temporary profile (set PROFILE_STORAGE or user_data_dir to enable persistence)")

    # 使用指定的 CDP 端口（如果提供）
    if cdp_port is None:
        cdp_port = CDP_PORT

    extra = _build_launch_args(cdp_port=cdp_port, proxy=proxy, extra_args=extra_args)
    all_args = stealth_args + extra

    pw = await async_playwright().start()

    logger.info(f"Launching CloakBrowser: headless={headless}, port={cdp_port}")

    if profile_dir:
        # patchright 要求使用 launch_persistent_context 来指定 user_data_dir
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            executable_path=binary_path,
            headless=headless,
            args=all_args,
            ignore_default_args=[
                "--enable-automation",
                "--enable-blink-features=AutomationControlled",
            ],
            no_viewport=True,  # 让浏览器窗口自适应屏幕大小（配合 --start-maximized）
        )
        # persistent context 的 browser 就是 context 自身
        browser = context
    else:
        browser = await pw.chromium.launch(
            executable_path=binary_path,
            headless=headless,
            args=all_args,
            ignore_default_args=[
                "--enable-automation",
                "--enable-blink-features=AutomationControlled",
            ],
        )

    cdp_url = f"http://127.0.0.1:{cdp_port}"
    logger.info(f"CloakBrowser running, CDP at {cdp_url}")
    return pw, browser, cdp_url


async def close_browser(pw: Playwright, browser: Browser) -> None:
    """安全关闭（单次，避免多次 detach）"""
    try:
        await browser.close()
    except Exception as e:
        logger.warning(f"Browser close: {e}")
    try:
        await pw.stop()
    except Exception as e:
        logger.warning(f"Playwright stop: {e}")


async def launch_cloakbrowser_cdp(
    cdp_port: int,
    profile_dir: Optional[str] = None,
    headless: bool = False,
    proxy: Optional[str] = None
):
    """
    启动 CloakBrowser 进程并返回进程对象（用于 Session Pool）

    Args:
        cdp_port: CDP 调试端口
        profile_dir: 用户数据目录（用于隔离不同用户的 cookie/session）
        headless: 是否无头模式
        proxy: 代理服务器地址

    Returns:
        subprocess.Popen 进程对象
    """
    import subprocess

    binary_path = get_cloakbrowser_path()

    # 获取 CloakBrowser 推荐的 stealth 启动参数
    try:
        import cloakbrowser as cb
        stealth_args = cb.get_default_stealth_args()
    except Exception:
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
        ]

    # 构建启动参数
    extra = _build_launch_args(cdp_port=cdp_port, proxy=proxy)
    all_args = [binary_path] + stealth_args + extra

    # 添加 profile 目录
    if profile_dir:
        all_args.append(f"--user-data-dir={profile_dir}")

    # 添加无头模式
    if headless:
        all_args.append("--headless=new")

    logger.info(f"Launching CloakBrowser process on port {cdp_port}")

    # 启动进程
    process = subprocess.Popen(
        all_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    # 等待浏览器启动
    await asyncio.sleep(2)

    return process
