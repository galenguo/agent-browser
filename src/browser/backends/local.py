"""本地 CDP 后端 — 包装现有 BrowserController + BrowserDaemon"""
import sys
from pathlib import Path

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 确保项目根路径在 sys.path 中（src/browser/backends/ 需要访问 skills/ 和 src/）
_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from . import BrowserBackend, BrowserPageHandle
from skills.agent_browser.config import SkillConfig
from skills.agent_browser.refs_generator import generate_refs, COMBINED_SELECTOR

logger = logging.getLogger(__name__)


class PlaywrightPageHandle(BrowserPageHandle):
    """
    Playwright Page 的薄包装，实现 BrowserPageHandle 接口。
    95% 委托给 Playwright Page 对象。
    """

    def __init__(self, page: Page):
        self._page = page
        self._listeners: Dict[str, list] = {}

    @property
    def raw_page(self) -> Page:
        """暴露原始 Playwright Page（用于需要 Playwright 特定功能的场景）"""
        return self._page

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        await self._page.go_back(wait_until=wait_until, timeout=timeout)

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        await self._page.mouse.wheel(delta_x, delta_y)

    async def mouse_move(self, x: float, y: float) -> None:
        await self._page.mouse.move(x, y)

    async def keyboard_press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def title(self) -> str:
        return await self._page.title()

    async def url(self) -> str:
        return self._page.url

    async def on(self, event: str, handler: Callable) -> None:
        self._page.on(event, handler)
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)

    def remove_listener(self, event: str, handler: Callable) -> None:
        self._page.remove_listener(event, handler)
        if event in self._listeners:
            self._listeners[event] = [h for h in self._listeners[event] if h != handler]

    async def close(self) -> None:
        try:
            await self._page.close()
        except Exception:
            pass


@dataclass
class LocalSession:
    """本地会话数据"""
    page_handle: PlaywrightPageHandle
    browser_context: Any  # BrowserContext
    dom_indices: List[int]
    snapshot_cache: Optional[Dict] = None


class LocalCDPBackend(BrowserBackend):
    """
    本地 CDP 后端 — 唯一的浏览器操作核心实现。

    - 使用 Playwright connect_over_cdp 连接本地 CloakBrowser
    - daemon_enabled 时使用 BrowserDaemon 持久连接
    - 集成 StealthEnhancer（隐匿增强）
    - 支持 LLM 模式（原子操作）和 Agent 模式（browser-use Agent）
    """

    def __init__(self, config: SkillConfig):
        self._config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._sessions: Dict[str, LocalSession] = {}
        self._stealth = None
        self._daemon = None
        self._browser_process = None  # 自动启动的浏览器子进程

        # Daemon 持久化（可选）
        if config.daemon_enabled:
            try:
                from ..daemon import BrowserDaemon
                self._daemon = BrowserDaemon.get(config)
                logger.info("BrowserDaemon enabled")
            except Exception as e:
                logger.debug(f"BrowserDaemon not available: {e}")

        # 延迟初始化 StealthEnhancer
        if config.stealth_enabled:
            try:
                from ..stealth import StealthEnhancer
                self._stealth = StealthEnhancer()
            except ImportError:
                logger.debug("StealthEnhancer not available")

    async def _is_cdp_reachable(self) -> bool:
        """检查 CDP 端点是否可达"""
        import aiohttp
        cdp_url = self._config.cdp_url
        # 转换为 HTTP URL 用于健康检查
        if cdp_url.startswith("ws://"):
            health_url = "http://" + cdp_url[5:] + "/json/version"
        else:
            health_url = cdp_url.replace("http://", "http://") + "/json/version"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @staticmethod
    async def ensure_cloakbrowser_installed() -> bool:
        """
        检查 CloakBrowser 是否已安装，未安装则自动下载。

        Returns True 如果已安装或安装成功。
        """
        try:
            import cloakbrowser  # noqa: F401
            logger.debug(f"CloakBrowser found: {getattr(cloakbrowser, '__version__', 'unknown')}")
            return True
        except ImportError:
            pass

        logger.info("CloakBrowser not installed, attempting auto-install...")
        import subprocess
        import sys

        try:
            result = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install",
                "cloakbrowser==0.3.18",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate(timeout=120)

            if result.returncode != 0:
                logger.error(f"pip install cloakbrowser failed (rc={result.returncode}):")
                if stderr:
                    logger.error(stderr.decode().strip()[-500:])
                return False

            logger.info("✅ CloakBrowser installed successfully")
            return True

        except Exception as e:
            logger.error(f"Auto-install CloakBrowser failed: {e}")
            return False

    async def _launch_browser(self) -> None:
        """自动启动 CloakBrowser 子进程"""
        import sys
        import subprocess

        logger.info("🚀 Auto-starting CloakBrowser...")

        # 启动 CloakBrowser 子进程
        try:
            self._browser_process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "cloakbrowser.launch",
                "--port", "19222",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info(f"CloakBrowser process started (PID: {self._browser_process.pid})")
        except Exception as e:
            logger.error(f"Failed to launch CloakBrowser: {e}")
            raise

        # 等待 CDP 端点可用（最多 30 秒）
        for attempt in range(30):
            await asyncio.sleep(1)
            if await self._is_cdp_reachable():
                logger.info("✅ CloakBrowser CDP endpoint ready")
                return

        # 超时，清理子进程
        if self._browser_process:
            self._browser_process.kill()
            await self._browser_process.wait()
            self._browser_process = None
        raise TimeoutError("CloakBrowser failed to start within 30 seconds")

    async def connect(self) -> None:
        """连接到 CDP 端点（带重试 + 自动启动浏览器）"""
        # Daemon 路径：使用 BrowserDaemon 持久连接
        if self._daemon:
            await self._daemon.ensure_connected()
            self._browser = self._daemon.browser
            return

        # 非 Daemon 路径：直接连接
        if self._browser:
            try:
                _ = self._browser.contexts  # 存活性检查
                return
            except Exception:
                self._browser = None

        # 自动启动浏览器（如果 CDP 不可达）
        if not await self._is_cdp_reachable():
            # 先确保 CloakBrowser 已安装（Phase 1.5: auto-download）
            if not await self.ensure_cloakbrowser_installed():
                raise RuntimeError(
                    "CloakBrowser not installed and auto-install failed. "
                    "Run: pip install cloakbrowser==0.3.18"
                )
            await self._launch_browser()

        if not self._playwright:
            self._playwright = await async_playwright().start()

        cdp_url = self._config.cdp_url
        # Playwright connect_over_cdp 需要 HTTP URL
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]

        retries = 3
        for attempt in range(retries):
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                logger.info(f"Connected to CDP: {cdp_url}")
                return
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))
                else:
                    raise

    async def disconnect(self) -> None:
        """断开浏览器连接（清理子进程）"""
        # 先关闭所有 session
        for sid in list(self._sessions.keys()):
            await self.delete_session(sid)

        if self._daemon:
            await self._daemon.disconnect()
            self._browser = None
            return

        # 清理浏览器子进程（如果是自动启动的）
        if self._browser_process:
            try:
                logger.info(f"Terminating auto-started browser process (PID: {self._browser_process.pid})")
                self._browser_process.terminate()
                await asyncio.wait_for(self._browser_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Browser process did not terminate gracefully, killing...")
                self._browser_process.kill()
                await self._browser_process.wait()
            except Exception as e:
                logger.debug(f"Error terminating browser process: {e}")
            finally:
                self._browser_process = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def is_connected(self) -> bool:
        if self._daemon:
            return self._daemon.is_connected
        if not self._browser:
            return False
        try:
            _ = self._browser.contexts
            return True
        except Exception:
            return False

    async def create_session(self, session_id: str) -> PlaywrightPageHandle:
        """创建浏览器会话"""
        await self.connect()

        # Daemon 路径：使用 daemon 的 context 管理
        if self._daemon:
            context, page = await self._daemon.create_context(session_id)
            if self._stealth:
                from ..stealth import StealthEnhancer
                await StealthEnhancer.inject_timing_noise(page)
            page_handle = PlaywrightPageHandle(page)
            self._sessions[session_id] = LocalSession(
                page_handle=page_handle,
                browser_context=context,
                dom_indices=[],
            )
            logger.info(f"Session created (daemon): {session_id}")
            return page_handle

        # 非 Daemon 路径
        context = await self._browser.new_context()
        page = await context.new_page()

        # 注入隐匿增强
        if self._stealth:
            from ..stealth import StealthEnhancer
            await StealthEnhancer.inject_timing_noise(page)

        page_handle = PlaywrightPageHandle(page)
        self._sessions[session_id] = LocalSession(
            page_handle=page_handle,
            browser_context=context,
            dom_indices=[],
        )

        logger.info(f"Session created: {session_id}")
        return page_handle

    async def delete_session(self, session_id: str) -> None:
        """删除浏览器会话"""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        # Daemon 路径：通过 daemon 管理 context 生命周期
        if self._daemon:
            await self._daemon.destroy_context(session_id)
            logger.info(f"Session deleted (daemon): {session_id}")
            return

        # 非 Daemon 路径
        try:
            await session.page_handle.close()
        except Exception:
            pass
        try:
            await session.browser_context.close()
        except Exception:
            pass
        logger.info(f"Session deleted: {session_id}")

    async def get_page(self, session_id: str) -> PlaywrightPageHandle:
        """获取会话的页面句柄"""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id].page_handle

    # ── 快照/refs 专用方法（保持与现有 controller.py 兼容）──

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照（兼容现有接口）"""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # 使用缓存
        if session.snapshot_cache and not interactive_only:
            result = session.snapshot_cache
            session.snapshot_cache = None
            return result

        page = session.page_handle.raw_page
        elements, dom_indices, page_info = await generate_refs(page, interactive_only)
        session.dom_indices = dom_indices

        return {
            "url": page_info["href"],
            "title": page_info["title"],
            "elements": elements,
        }

    async def cache_snapshot_after_open(self, session_id: str) -> None:
        """open_page 后预计算快照缓存"""
        session = self._sessions.get(session_id)
        if not session:
            return

        try:
            page = session.page_handle.raw_page
            elements, dom_indices, page_info = await generate_refs(page, False)
            session.dom_indices = dom_indices
            session.snapshot_cache = {
                "url": page_info["href"],
                "title": page_info["title"],
                "elements": elements,
            }
        except Exception:
            session.snapshot_cache = None

    def get_dom_indices(self, session_id: str) -> List[int]:
        """获取会话的 DOM 索引"""
        session = self._sessions.get(session_id)
        return session.dom_indices if session else []

    async def stealth_delay(self, action_type: str = "general") -> None:
        """隐匿延迟"""
        if self._stealth:
            await self._stealth.pre_action(action_type)

    async def stealth_mouse_move(self, session_id: str) -> None:
        """隐匿鼠标移动"""
        if self._stealth:
            session = self._sessions.get(session_id)
            if session:
                await self._stealth.random_mouse_move(session.page_handle.raw_page)

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: Optional[Dict] = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> Dict:
        """
        Agent 模式任务执行（本地 CDP）。

        使用 browser-use Agent 通过现有 CDP URL 自主完成任务。
        每块最多 max_steps 步，最多执行 2 块。
        total_timeout: 整体超时秒数（默认 300s / 5 分钟），防止无限阻塞。
        """
        if intelligence != "agent":
            return {
                "status": "ready",
                "mode": "llm",
                "session_id": session_id,
                "tools": ["snapshot", "click", "fill", "scroll", "go_back", "hover", "press_key"],
            }

        try:
            from browser_use import Agent
            from browser_use.browser.profile import BrowserProfile
            from browser_use.browser.session import BrowserSession as BUSession
        except ImportError:
            return {
                "status": "failed",
                "error": "browser-use not installed. Run: pip install browser-use==0.12.2",
            }

        if session_id not in self._sessions:
            return {"status": "failed", "error": f"Session {session_id} not found"}

        # LLM 实例
        llm = self._create_llm(llm_config)

        # browser-use 通过 CDP URL 创建自己的连接（需要独立 BrowserSession）
        cdp_url = self._config.cdp_url
        browser_profile = BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.0,
        )

        all_results = []
        last_result_text = ""
        stuck_count = 0
        total_steps = 0
        MAX_CHUNKS = 2

        try:
            browser_session = BUSession(browser_profile=browser_profile)

            async def _run_chunks():
                """内部：分块执行 agent 任务（可被 total_timeout 超时控制）"""
                nonlocal browser_session

                # 注入隐匿动作（覆盖 browser-use 默认 navigate/input/click）
                controller = None
                if self._stealth:
                    try:
                        from browser_use.tools.service import Tools
                        from src.core.stealth_actions import register_stealth_actions

                        controller = Tools(browser_session)
                        register_stealth_actions(controller, self._stealth)
                        logger.info("Stealth actions registered for agent mode")
                    except Exception as e:
                        logger.warning(f"Failed to register stealth actions: {e} (using default actions)")

                for chunk_num in range(1, MAX_CHUNKS + 1):
                    if chunk_num == 1:
                        current_task = f"{task}\n完成后输出 TASK_COMPLETE: <结果摘要>"
                    else:
                        current_task = (
                            f"任务：{task}\n"
                            f"已完成：{last_result_text}\n"
                            f"请继续。完成后输出 TASK_COMPLETE: <结果摘要>"
                        )

                    agent_kwargs = dict(
                        task=current_task,
                        llm=llm,
                        browser_session=browser_session,
                        max_actions_per_step=5,
                        use_vision=False,
                    )
                    if controller:
                        agent_kwargs["controller"] = controller

                    agent = Agent(**agent_kwargs)

                    try:
                        result = await agent.run(max_steps=max_steps)
                        total_steps += max_steps
                    except Exception as e:
                        logger.error(f"Agent chunk {chunk_num} failed: {e}")
                        return {"status": "failed", "error": str(e), "steps": total_steps}

                    result_text = str(result) if result else ""
                    all_results.append(result_text)

                    if "TASK_COMPLETE" in result_text:
                        final = result_text.split("TASK_COMPLETE:")[-1].strip()
                        return {"status": "completed", "result": final, "steps": total_steps, "chunks": chunk_num}

                    if not result_text or result_text == last_result_text:
                        stuck_count += 1
                    else:
                        stuck_count = 0

                    if stuck_count >= 2:
                        return {
                            "status": "stuck",
                            "result": result_text or last_result_text,
                            "steps": total_steps,
                            "chunks": chunk_num,
                        }

                    last_result_text = result_text

                return {
                    "status": "completed" if all_results else "failed",
                    "result": last_result_text,
                    "steps": total_steps,
                    "chunks": MAX_CHUNKS,
                }

            # 超时控制
            if total_timeout > 0:
                try:
                    return await asyncio.wait_for(_run_chunks(), timeout=total_timeout)
                except asyncio.TimeoutError:
                    return {
                        "status": "timeout",
                        "error": f"Task exceeded {total_timeout}s limit",
                        "steps": total_steps,
                    }
            else:
                return await _run_chunks()
        finally:
            try:
                await browser_session.close()
            except Exception:
                pass

    def _create_llm(self, llm_config: Optional[Dict] = None):
        """创建 browser-use 兼容的 LLM 实例"""
        import os
        if not llm_config:
            provider = os.getenv("AGENT_BROWSER_LLM_PROVIDER", "openai")
            llm_config = {"provider": provider}

        provider = llm_config.get("provider", "openai")
        model_name = llm_config.get("model", "gpt-4o" if provider == "openai" else "claude-3-5-sonnet-20241022")
        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        temperature = llm_config.get("temperature", 0.1)
        max_tokens = llm_config.get("max_tokens", 4096)

        if provider == "anthropic":
            from browser_use.llm.anthropic.chat import ChatAnthropic
            return ChatAnthropic(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=temperature, max_tokens=max_tokens,
            )
        else:
            from browser_use.llm.openai.chat import ChatOpenAI
            return ChatOpenAI(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=temperature, max_completion_tokens=max_tokens,
            )
