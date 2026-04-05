"""
会话池管理器

多用户隔离核心：
- 每个用户创建独立 Session
- Session 隔离：独立 profile、cookie、指纹
- 资源限制：最大并发数、超时回收
- 负载均衡：分配到不同浏览器实例
- 原子操作：导航、快照、点击、填充、执行 JS 等
"""

import os
import time
import asyncio
import logging
from uuid import uuid4
from typing import Dict, Optional, Literal, List, Any

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from browser_use import Agent, BrowserSession, BrowserProfile
from src.models import (
    UserSession, ResourceExhaustedError, SessionNotFoundError, DockerBrowserInstance,
    NavigateRequest, ClickRequest, FillRequest, EvaluateRequest, ScrollRequest, WaitRequest,
    ElementInfo, SnapshotResponse, LocalBrowserInstance
)
from src.browser.instance_pool import BrowserInstancePool
from src.core.stealth_enhancer import StealthEnhancer

logger = logging.getLogger(__name__)


class SessionPoolManager:
    """会话池管理器 - 多用户隔离核心"""

    def __init__(
        self,
        max_concurrent: int = 10,
        idle_timeout: int = 1800,
        browser_mode: Literal["local", "docker"] = "local",
    ):
        self.sessions: Dict[str, UserSession] = {}
        self.max_concurrent = max_concurrent
        self.idle_timeout = idle_timeout

        # Docker 模式下检测本地 CDP 是否已运行 → 自动降级到 local 模式
        effective_mode = browser_mode
        if browser_mode == "docker":
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', 19222))
                sock.close()
                if result == 0:
                    effective_mode = "local"
                    logger.info("🔧 Local CDP detected on :19222, overriding browser_mode docker → local")
            except Exception:
                pass

        self.browser_pool = BrowserInstancePool(mode=effective_mode)
        self._stealth = StealthEnhancer()

        self._monitor_task = None
        self._health_check_task = None
        self._create_lock = asyncio.Lock()
        # Docker 模式 CDP 连接缓存: session_id → (playwright, browser)
        self._docker_connections: Dict[str, tuple] = {}

        logger.info(
            f"🔧 SessionPoolManager initialized: "
            f"max_concurrent={max_concurrent}, "
            f"idle_timeout={idle_timeout}s, "
            f"browser_mode={browser_mode}"
        )

    def start(self):
        """启动后台任务（必须在事件循环内调用）"""
        self._monitor_task = asyncio.create_task(self._idle_monitor())
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def create_session(
        self,
        user_id: str,
        profile_config: Optional[Dict] = None,
        browser_type: str = "chromium",
    ) -> str:
        """创建新会话"""
        # 在锁内检查配额并预留 session_id，避免并发超额
        async with self._create_lock:
            if len(self.sessions) >= self.max_concurrent:
                raise ResourceExhaustedError(
                    f"Max concurrent sessions reached ({self.max_concurrent})"
                )
            session_id = f"{user_id}_{uuid4().hex[:8]}"
            # 提前占位，防止并发请求绕过配额检查
            self.sessions[session_id] = None  # type: ignore[assignment]

        # 创建独立 Profile 目录
        profile_base = os.getenv('PROFILE_STORAGE', '/data/profiles')
        profile_dir = os.path.join(profile_base, session_id)
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)

        logger.info(f"📝 Creating session {session_id} for user {user_id} (browser={browser_type})")

        # 分配浏览器实例（失败时自动回滚）
        try:
            browser_instance = await self.browser_pool.allocate(
                session_id=session_id,
                profile_dir=profile_dir,
                browser_type=browser_type,
            )
        except Exception:
            logger.error(f"Failed to allocate browser for session {session_id}, cleaning up")
            self.sessions.pop(session_id, None)
            await self.browser_pool.release(session_id)
            raise

        user_session = UserSession(
            session_id=session_id,
            user_id=user_id,
            browser_instance=browser_instance,
            profile_dir=profile_dir,
            created_at=time.time(),
            last_activity=time.time(),
        )

        self.sessions[session_id] = user_session
        logger.info(f"✅ Session created: {session_id}")
        return session_id, self._build_browser_node_info(browser_instance)

    def _build_browser_node_info(self, instance) -> Optional[Dict]:
        """构建浏览器节点公网访问信息（DockerBrowserInstance 返回 VNC 信息）"""
        if not isinstance(instance, DockerBrowserInstance):
            return None
        # 有 novnc_url 就返回（默认有 BROWSER_PUBLIC_HOST 时总会生成）
        info = {
            "instance_id": instance.instance_id,
        }
        if instance.public_host:
            info["public_host"] = instance.public_host
        if instance.public_cdp_port:
            info["public_cdp_port"] = instance.public_cdp_port
        if instance.public_novnc_port:
            info["public_novnc_port"] = instance.public_novnc_port
        if instance.novnc_url:
            info["novnc_url"] = instance.novnc_url
        return info

    async def submit_task(
        self,
        session_id: str,
        task: str,
        llm_config: Dict,
        max_steps: int = 50,
    ) -> str:
        """提交任务到指定会话"""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        session.mark_activity()

        # 创建 LLM
        llm = self._create_llm(llm_config)

        # 每次任务重建 BrowserSession，避免上一个任务清理后状态损坏
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(
                cdp_url=session.browser_instance.cdp_url,
                is_local=True,
                headless=False,
                highlight_elements=True,
            ),
        )

        # 使用 browser-use Agent（CDP 协议）
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            max_actions_per_step=5,
            use_vision=False,
        )

        task_id = f"task_{uuid4().hex[:8]}"

        # 记录任务
        session.tasks[task_id] = {
            "status": "running",
            "task": task,
            "llm_config": llm_config,
            "result": None,
            "error": None,
            "created_at": time.time(),
            "current_step": 0,
            "last_step_at": None,
        }

        # 异步执行任务（传入 browser_session 以便 finally 关闭）
        asyncio.create_task(self._run_agent(session_id, task_id, agent, browser_session, max_steps))

        logger.info(f"📋 Task {task_id} submitted to session {session_id}")
        return task_id

    async def _run_agent(
        self,
        session_id: str,
        task_id: str,
        agent: Agent,
        browser_session: BrowserSession,
        max_steps: int,
    ):
        """运行 Agent 任务（串行锁保证同一 session 不并发，CDP 连接失败自动重试）"""
        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found when running task {task_id}")
            return

        # 从 task 记录中获取原始任务描述和 LLM 配置
        task_info = session.tasks.get(task_id, {})
        task_description = task_info.get("task", "")
        llm_config = task_info.get("llm_config", {})
        cdp_url = session.browser_instance.cdp_url

        async with session.task_lock:
            MAX_CDP_RETRIES = 3
            last_error = None
            current_agent = agent
            current_bs = browser_session

            try:
                for attempt in range(MAX_CDP_RETRIES):
                    try:
                        # Docker 容器刚启动时 CDP 端点可能不稳定，给短暂等待
                        if attempt == 0 and isinstance(session.browser_instance, DockerBrowserInstance):
                            await asyncio.sleep(2)

                        logger.info(f"🤖 Running agent for task {task_id} (max_steps={max_steps}, attempt={attempt+1})")

                        result = await current_agent.run(max_steps=max_steps)

                        # 提取最终结果文本
                        final_text = str(result)
                        if hasattr(result, "all_results"):
                            for r in reversed(result.all_results):
                                if r.extracted_content and r.is_done:
                                    final_text = r.extracted_content
                                    break

                        session.tasks[task_id]["status"] = "completed"
                        session.tasks[task_id]["result"] = final_text
                        session.mark_activity()

                        logger.info(f"✅ Task {task_id} completed")
                        return  # Success

                    except Exception as e:
                        last_error = e
                        error_str = str(e).lower()
                        error_type = type(e).__name__.lower()

                        # 检查是否为 CDP 连接错误（可重试）
                        # 同时检查错误消息和异常类型名（httpx.ReadError 的 str(e) 可能为空）
                        cdp_keywords = [
                            "read error", "econnreset", "cdp", "websocket",
                            "connect_over_cdp", "readerror", "connection",
                            "browserstartevent", "timed out", "timeout",
                        ]
                        is_cdp_error = (
                            any(kw in error_str for kw in cdp_keywords) or
                            any(kw in error_type for kw in ["readerror", "timeout", "connection"])
                        )

                        # 关闭失败的 browser session
                        try:
                            await current_bs.close()
                        except Exception:
                            pass

                        if not is_cdp_error or attempt >= MAX_CDP_RETRIES - 1:
                            # 非 CDP 错误或重试次数耗尽
                            logger.error(f"❌ Task {task_id} failed: {e}")
                            session.tasks[task_id]["status"] = "failed"
                            session.tasks[task_id]["error"] = str(e)
                            return

                        # CDP 连接错误，等待后重试
                        wait_time = 5 * (attempt + 1)
                        logger.warning(
                            f"⚠️ [{task_id}] CDP connection error (attempt {attempt+1}/{MAX_CDP_RETRIES}): {e}. "
                            f"Retrying in {wait_time}s..."
                        )
                        await asyncio.sleep(wait_time)

                        # 重新创建 BrowserSession 和 Agent
                        new_bs = BrowserSession(
                            browser_profile=BrowserProfile(
                                cdp_url=cdp_url,
                                is_local=True,
                                headless=False,
                                highlight_elements=True,
                            ),
                        )
                        new_agent = Agent(
                            task=task_description,
                            llm=self._create_llm(llm_config),
                            browser_session=new_bs,
                            max_actions_per_step=5,
                            use_vision=False,
                        )
                        current_agent = new_agent
                        current_bs = new_bs

            finally:
                # 关闭最后一次的 BrowserSession
                try:
                    await current_bs.close()
                except Exception:
                    pass

    def _create_llm(self, llm_config: Dict):
        """创建 LLM 实例（使用 browser-use 的 ChatOpenAI 包装器）"""
        from browser_use.llm import ChatOpenAI

        return ChatOpenAI(
            model=llm_config.get("model", "glm-5-turbo"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            temperature=0.1,
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
        )

    async def get_task_status(self, session_id: str, task_id: str) -> Dict:
        """获取任务状态"""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        task_info = session.tasks.get(task_id)
        if not task_info:
            return {"status": "not_found"}

        result = dict(task_info)
        result["browser_node"] = self._build_browser_node_info(session.browser_instance)
        return result

    async def get_session_status(self, session_id: str) -> Dict:
        """获取会话状态"""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "idle_time": time.time() - session.last_activity,
            "tasks": {
                task_id: {
                    "status": task_info["status"],
                    "task": task_info["task"],
                    "created_at": task_info["created_at"],
                }
                for task_id, task_info in session.tasks.items()
            },
            "browser_node": self._build_browser_node_info(session.browser_instance),
        }

    async def close_session(self, session_id: str):
        """关闭会话"""
        session = self.sessions.pop(session_id, None)
        if not session:
            logger.warning(f"⚠️  Session not found: {session_id}")
            return

        logger.info(f"🔒 Closing session {session_id}")

        # 关闭 Docker CDP 连接
        conn = self._docker_connections.pop(session_id, None)
        if conn:
            pw, browser = conn
            try:
                await browser.close()
            except Exception:
                pass
            try:
                await pw.stop()
            except Exception:
                pass

        # 释放浏览器实例
        await self.browser_pool.release(session_id)

        logger.info(f"✅ Session closed: {session_id}")

    async def _idle_monitor(self):
        """空闲监控：超时自动关闭会话（跳过有活跃任务的会话）"""
        while True:
            await asyncio.sleep(60)  # 每分钟检查一次

            idle_sessions = []
            for session_id, session in list(self.sessions.items()):
                if session.is_idle(self.idle_timeout):
                    # 检查是否有任务正在运行（task_lock 被持有）
                    if session.task_lock.locked():
                        logger.debug(
                            f"⏰ Session {session_id} idle for {self.idle_timeout}s, "
                            f"but has active task running, skipping..."
                        )
                        continue
                    idle_sessions.append(session_id)

            for session_id in idle_sessions:
                logger.info(
                    f"⏰ Session {session_id} idle for {self.idle_timeout}s, closing..."
                )
                await self.close_session(session_id)

    async def _health_check_loop(self):
        """运行时健康检查：检测 Docker 容器崩溃并自动恢复"""
        from models import DockerBrowserInstance

        while True:
            await asyncio.sleep(30)  # 每 30 秒检查一次

            for session_id, session in list(self.sessions.items()):
                instance = session.browser_instance

                if not isinstance(instance, DockerBrowserInstance):
                    continue

                try:
                    instance.container.reload()
                    status = instance.container.status
                except Exception as e:
                    logger.warning(f"Cannot inspect container for {session_id}: {e}")
                    status = "unknown"

                if status not in ("running",):
                    logger.error(
                        f"🔴 Container for session {session_id} is {status}, "
                        f"recovering..."
                    )
                    # 清理死会话，释放资源
                    try:
                        await self.close_session(session_id)
                    except Exception as e:
                        logger.warning(f"Failed to close dead session {session_id}: {e}")

                    # TODO Phase 2: 自动重建会话（需要记住原始 user_id 和 profile_config）

    async def shutdown(self):
        """关闭所有会话"""
        logger.info("🛑 Shutting down SessionPoolManager...")

        # 取消后台任务
        for task in (self._monitor_task, self._health_check_task):
            if task:
                task.cancel()

        # 关闭所有会话
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id)

        logger.info("✅ SessionPoolManager shutdown complete")

    # ============ 原子操作方法 ============

    async def _get_page(self, session_id: str) -> Page:
        """获取会话的 Playwright Page 对象（支持 Local 和 Docker 实例）"""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        instance = session.browser_instance

        if isinstance(instance, DockerBrowserInstance):
            return await self._get_docker_page(session_id, instance)

        # LocalBrowserInstance: 直接使用已有的 Playwright 对象
        browser = instance.browser
        if not browser:
            raise SessionNotFoundError(f"Browser not connected for session {session_id}")

        # 兼容 Browser 和 BrowserContext（persistent context 返回 BrowserContext）
        # 注意: patchright 和 playwright 的类型不同，不能跨 isinstance 检查
        if hasattr(browser, 'pages') and not hasattr(browser, 'contexts'):
            # persistent context / BrowserContext: 直接使用 pages
            pages = browser.pages
            if pages:
                return pages[0]
            else:
                return await browser.new_page()
        else:
            # 普通 Browser: 通过 contexts 获取
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
            else:
                context = await browser.new_context()
            pages = context.pages
            if pages:
                return pages[0]
            else:
                return await context.new_page()

    async def _get_docker_page(self, session_id: str, instance: DockerBrowserInstance) -> Page:
        """通过 CDP 连接获取 Docker 容器中的 Page（带重试）"""
        # 复用已有的 CDP 连接
        if session_id in self._docker_connections:
            pw, browser = self._docker_connections[session_id]
            try:
                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
            except Exception:
                # 连接断开，清理后重连
                old_pw, old_browser = self._docker_connections.pop(session_id, (None, None))
                if old_browser:
                    try:
                        await old_browser.close()
                    except Exception:
                        pass
                if old_pw:
                    try:
                        await old_pw.stop()
                    except Exception:
                        pass

        # 建立新的 CDP 连接（带重试，Docker 容器可能需要额外时间）
        last_error = None
        for attempt in range(3):
            try:
                pw = await async_playwright().start()
                browser = await pw.chromium.connect_over_cdp(instance.cdp_url)
                self._docker_connections[session_id] = (pw, browser)

                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
                context = contexts[0] if contexts else await browser.new_context()
                return await context.new_page()
            except Exception as e:
                last_error = e
                logger.warning(f"CDP connect attempt {attempt+1}/3 failed: {e}")
                # 清理失败的连接
                if session_id in self._docker_connections:
                    _, failed_browser = self._docker_connections.pop(session_id, (None, None))
                    try:
                        if failed_browser:
                            await failed_browser.close()
                    except Exception:
                        pass
                    try:
                        await pw.stop()
                    except Exception:
                        pass
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))  # 3s, 6s backoff

        raise ConnectionError(f"Failed to connect to Docker CDP at {instance.cdp_url} after 3 attempts: {last_error}")

    async def navigate(self, session_id: str, request: NavigateRequest) -> Dict:
        """页面导航"""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("navigate")

        try:
            await page.goto(
                request.url,
                wait_until=request.wait_until,
                timeout=request.timeout
            )
        except Exception as e:
            error_str = str(e).lower()
            # CDP 连接断开时标记会话为异常，让 health_check 清理
            if any(kw in error_str for kw in ["disconnected", "connection", "read error", "econnreset"]):
                logger.error(f"CDP connection lost during navigate for session {session_id}: {e}")
                # Docker 实例：主动清理避免僵尸容器
                session = self.sessions.get(session_id)
                if session and isinstance(session.browser_instance, DockerBrowserInstance):
                    logger.warning(f"Auto-cleaning dead Docker session {session_id}")
                    asyncio.create_task(self.close_session(session_id))
            raise

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {
            "status": "ok",
            "url": page.url,
            "title": await page.title()
        }

    async def snapshot(self, session_id: str, interactive_only: bool = True) -> SnapshotResponse:
        """获取 DOM 快照"""
        page = await self._get_page(session_id)

        # 注入 data-ab-ref 属性并返回元素列表，确保 ref 与 DOM 绑定（防止位置偏移问题）
        elements_script = """
        () => {
            const selectors = 'button, a, input, textarea, select, [role="button"], [onclick]';
            const allElements = [];
            let refIndex = 0;

            document.querySelectorAll(selectors).forEach(el => {
                if (el.offsetParent === null && el.getClientRects().length === 0) return;

                const ref = '@e' + refIndex;
                el.setAttribute('data-ab-ref', ref);
                refIndex++;

                const rect = el.getBoundingClientRect();
                allElements.push({
                    ref: ref,
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || el.value || el.placeholder || '').substring(0, 100).trim(),
                    role: el.getAttribute('role') || el.tagName.toLowerCase(),
                    type: el.type || null,
                    placeholder: el.placeholder || null,
                    href: el.href || null,
                    is_visible: rect.width > 0 && rect.height > 0,
                    is_enabled: !el.disabled,
                    bounding_box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                });
            });

            return {
                url: window.location.href,
                title: document.title,
                elements: allElements
            };
        }
        """

        result = await page.evaluate(elements_script)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return SnapshotResponse(
            url=result["url"],
            title=result["title"],
            elements=[ElementInfo(**el) for el in result["elements"]]
        )

    async def click(self, session_id: str, request: ClickRequest) -> Dict:
        """点击元素"""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("click")
        await self._stealth.random_mouse_move(page)

        # 验证 ref 格式
        if not request.ref.startswith("@e"):
            raise ValueError(f"Invalid ref format: {request.ref}")

        # 通过 data-ab-ref 属性查找元素（稳定，不受 DOM 位置变化影响）
        element = await page.query_selector(f'[data-ab-ref="{request.ref}"]')
        if not element:
            raise ValueError(f"Element {request.ref} not found. DOM may have changed since snapshot.")

        # 执行点击
        await element.click(
            button=request.button,
            click_count=request.click_count,
            delay=request.delay
        )

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "ref": request.ref}

    async def fill(self, session_id: str, request: FillRequest) -> Dict:
        """填充输入框"""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("input")

        # 验证 ref 格式
        if not request.ref.startswith("@e"):
            raise ValueError(f"Invalid ref format: {request.ref}")

        # 通过 data-ab-ref 属性查找元素（稳定，不受 DOM 位置变化影响）
        element = await page.query_selector(f'[data-ab-ref="{request.ref}"]')
        if not element:
            raise ValueError(f"Element {request.ref} not found. DOM may have changed since snapshot.")

        # 清空并填充
        if request.clear_first:
            await element.fill("")
        await element.fill(request.text)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "ref": request.ref, "text": request.text}

    async def evaluate(self, session_id: str, request: EvaluateRequest) -> Dict:
        """执行 JavaScript"""
        page = await self._get_page(session_id)

        result = await page.evaluate(request.expression)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "result": result}

    async def scroll(self, session_id: str, request: ScrollRequest) -> Dict:
        """滚动页面"""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("scroll")

        delta_y = request.amount if request.direction == "down" else -request.amount

        await page.mouse.wheel(0, delta_y)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "direction": request.direction, "amount": request.amount}

    async def wait_for_selector(self, session_id: str, request: WaitRequest) -> Dict:
        """等待选择器"""
        page = await self._get_page(session_id)

        await page.wait_for_selector(
            request.selector,
            timeout=request.timeout,
            state=request.state
        )

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "selector": request.selector}

    async def get_title(self, session_id: str) -> str:
        """获取页面标题"""
        page = await self._get_page(session_id)
        return await page.title()

    async def get_url(self, session_id: str) -> str:
        """获取页面 URL"""
        page = await self._get_page(session_id)
        return page.url

    async def go_back(self, session_id: str, wait_until: str = "domcontentloaded", timeout: int = 10000) -> Dict:
        """后退到上一页"""
        page = await self._get_page(session_id)
        await page.go_back(wait_until=wait_until, timeout=timeout)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "url": page.url}

    async def mouse_move(self, session_id: str, x: float, y: float) -> Dict:
        """移动鼠标"""
        page = await self._get_page(session_id)
        await page.mouse.move(x, y)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "x": x, "y": y}

    async def keyboard_press(self, session_id: str, key: str) -> Dict:
        """按键"""
        page = await self._get_page(session_id)
        await page.keyboard.press(key)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "key": key}
