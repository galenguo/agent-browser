"""Industrial-grade CDP stealth composition:

  1) CloakBrowser (C++ compiled-level fingerprinting, via pip install cloakbrowser)
  2) patchright (driver-level patches -- removes __playwright__binding__ / navigator.webdriver)
  3) REBROWSER_PATCHES_RUNTIME_FIX_MODE=addBinding (CDP Runtime.Enable leak fix)
  4) Non-standard port 19222 bound to 127.0.0.1 (connection obfuscation)
  5) Prohibit frequent attach/detach (persistent single session)

Integration approach:
  - CloakBrowser Python API (cloakbrowser.ensure_binary()) locates the binary path
  - patchright launches CloakBrowser via executable_path
  - REBROWSER_PATCHES_RUNTIME_FIX_MODE env var activates Runtime.Enable fix
  - The two work at different layers and do not interfere with each other
"""
import asyncio
import logging
import os

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

# Conditional CloakBrowser import
try:
    from cloakbrowser import launch_browser
    _HAS_CLOAK = True
except ImportError:
    _HAS_CLOAK = False

# Conditional patchright import (fallback to playwright)
try:
    from patchright.async_api import Browser, Playwright, async_playwright
    _HAS_PATCHRIGHT = True
except ImportError:
    from playwright.async_api import Browser, Playwright, async_playwright
    _HAS_PATCHRIGHT = False

logger = logging.getLogger(__name__)

CDP_PORT = int(os.getenv("CDP_PORT", "19222"))


def get_cloakbrowser_path() -> str:
    """Get CloakBrowser binary path; auto-downloads if not installed.

    Priority: environment variable (for Docker / manual override) > auto-detection.
    """
    # Prefer environment variable (Docker / manual specification scenarios)
    env_path = os.getenv("CLOAKBROWSER_PATH", "")
    if env_path and os.path.exists(env_path):
        logger.info(f"Using CloakBrowser from CLOAKBROWSER_PATH: {env_path}")
        return env_path

    # Use cloakbrowser Python package to auto-locate / download
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
    proxy: str | None = None,
    extra_args: list | None = None
) -> list:
    if cdp_port is None:
        cdp_port = CDP_PORT

    args = [
        # -- Connection obfuscation --
        f"--remote-debugging-port={cdp_port}",
        f"--remote-debugging-address={os.getenv('CDP_BIND_ADDRESS', '127.0.0.1')}",
        "--remote-allow-origins=*",

        # -- Environment adaptation --
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--window-position=0,0",
        "--start-maximized",
        "--disable-infobars",          # Hide info bar (including command-line flag warning)
        "--no-default-browser-check",  # Do not show default browser prompt

        # -- WebRTC leak protection --
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--enforce-webrtc-ip-permission-check",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",

        # -- Automation signal suppression --
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
    proxy: str | None = None,
    extra_args: list | None = None,
    user_data_dir: str | None = None,
    cdp_port: int | None = None,
) -> tuple[Playwright, Browser, str]:
    """Launch CloakBrowser (C++ fingerprint) via patchright (driver-level patches).

    Supports persistent Profile (optional):
    - Method 1: Set PROFILE_STORAGE env var to specify profile directory
    - Method 2: Pass user_data_dir parameter directly (higher priority)
    - Login state, passwords, cookies are persisted in that directory
    - Survives container restarts

    Args:
        headless: Whether to run in headless mode
        proxy: Proxy server address
        extra_args: Additional launch arguments
        user_data_dir: User data directory (takes priority over PROFILE_STORAGE)
        cdp_port: CDP port (default 19222)

    Returns:
        (playwright, browser, cdp_url)
        cdp_url is used for browser-use BrowserSession(cdp_url=...)
    """
    binary_path = get_cloakbrowser_path()

    # Get CloakBrowser's recommended stealth launch arguments
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

    # Persistent Profile support (optional)
    # Priority: user_data_dir parameter > PROFILE_STORAGE env var
    profile_dir = user_data_dir or os.getenv('PROFILE_STORAGE')
    if profile_dir:
        # Create profile directory
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)
        logger.info(f"Using persistent profile: {profile_dir}")

        # Hide bookmark bar + suppress restore page prompt
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
        logger.info("Using temporary profile (set PROFILE_STORAGE or user_data_dir to enable persistence)")

    # Use specified CDP port (if provided)
    if cdp_port is None:
        cdp_port = CDP_PORT

    extra = _build_launch_args(cdp_port=cdp_port, proxy=proxy, extra_args=extra_args)
    all_args = stealth_args + extra

    pw = await async_playwright().start()

    logger.info(f"Launching CloakBrowser: headless={headless}, port={cdp_port}")

    if profile_dir:
        # patchright requires launch_persistent_context for user_data_dir
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            executable_path=binary_path,
            headless=headless,
            args=all_args,
            ignore_default_args=[
                "--enable-automation",
                "--enable-blink-features=AutomationControlled",
            ],
            no_viewport=True,  # Let browser window adapt to screen size (with --start-maximized)
        )
        # For persistent context, the browser IS the context itself
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
    """Safe close (single attempt, avoid multiple detaches)."""
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
    profile_dir: str | None = None,
    headless: bool = False,
    proxy: str | None = None
):
    """Launch CloakBrowser process and return the process object (for Session Pool).

    Args:
        cdp_port: CDP debug port
        profile_dir: User data directory (for isolating different users' cookies/sessions)
        headless: Whether to use headless mode
        proxy: Proxy server address

    Returns:
        subprocess.Popen process object
    """
    import subprocess

    binary_path = get_cloakbrowser_path()

    # Get CloakBrowser's recommended stealth launch arguments
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

    # Build launch arguments
    extra = _build_launch_args(cdp_port=cdp_port, proxy=proxy)
    all_args = [binary_path] + stealth_args + extra

    # Add profile directory
    if profile_dir:
        all_args.append(f"--user-data-dir={profile_dir}")

    # Add headless mode
    if headless:
        all_args.append("--headless=new")

    logger.info(f"Launching CloakBrowser process on port {cdp_port}")

    # Launch process
    process = subprocess.Popen(
        all_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    # Wait for browser startup
    await asyncio.sleep(2)

    return process
