"""
UnifiedSessionManager - 统一会话管理

支持 API 模式和 CLI 模式，支持本地和远程浏览器。
远程浏览器通过 Gateway 分配，cdp_url 指向 Gateway WebSocket 代理。
"""
import time
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional
from uuid import uuid4

from browser_use.browser import BrowserSession, BrowserProfile

from src.browser.instance_pool import BrowserInstancePool
from src.core.browser_controller import BrowserController
from src.models import BrowserInstance, ResourceExhaustedError, SessionNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str
    browser_instance: BrowserInstance
    browser_session: BrowserSession
    controller: BrowserController
    mode: Literal["api", "cli"]
    browser_mode: Literal["local", "remote"]
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    # 远程模式专用（Gateway 分配的 instance_id）
    gateway_instance_id: Optional[str] = None


class UnifiedSessionManager:
    """
    统一会话管理器，API 和 CLI 模式共享。

    本地模式：通过 BrowserInstancePool 启动 CloakBrowser。
    远程模式：通过 Gateway 分配浏览器，cdp_url 指向 Gateway CDP 代理。
    """

    def __init__(
        self,
        mode: Literal["api", "cli"] = "api",
        max_concurrent: int = 10,
        idle_timeout: int = 1800,
        browser_mode: Literal["local", "remote"] = "local",
    ):
        self.mode = mode
        self.max_concurrent = max_concurrent
        self.idle_timeout = idle_timeout
        self.default_browser_mode = browser_mode
        self.sessions: Dict[str, SessionContext] = {}
        self._local_pool = BrowserInstancePool(mode="local")
        self._monitor_task = None

    async def start(self):
        """启动监控任务"""
        import asyncio
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止并清理所有会话"""
        if self._monitor_task:
            self._monitor_task.cancel()
        for session_id in list(self.sessions):
            await self.destroy_session(session_id)

    # ──────────────────────────────────────────
    # 会话生命周期
    # ──────────────────────────────────────────

    async def create_session(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        browser_mode: Optional[Literal["local", "remote"]] = None,
        cdp_url: Optional[str] = None,
        skip_warmup: bool = False,
    ) -> SessionContext:
        """
        创建会话。

        Args:
            session_id: 自定义 session_id，默认自动生成
            user_id: 用户标识（API 模式用于多用户隔离）
            browser_mode: local / remote，默认使用初始化时的配置
            cdp_url: 直接指定 cdp_url（远程模式下由 Gateway 提供）
            skip_warmup: 跳过预热浏览（测试环境使用，生产环境默认 False）
        """
        if len(self.sessions) >= self.max_concurrent:
            raise ResourceExhaustedError(f"Max concurrent sessions ({self.max_concurrent}) reached")

        session_id = session_id or uuid4().hex[:12]
        bmode = browser_mode or self.default_browser_mode

        # 环境变量可全局跳过预热（CI/测试环境）
        _skip = skip_warmup or os.getenv("SKIP_WARMUP", "").lower() in ("1", "true", "yes")

        if bmode == "remote":
            ctx = await self._create_remote_session(session_id, cdp_url, user_id)
        else:
            ctx = await self._create_local_session(session_id, user_id, skip_warmup=_skip)

        self.sessions[session_id] = ctx
        logger.info(f"Session created: {session_id} (mode={bmode})")
        return ctx

    async def _create_local_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        skip_warmup: bool = False,
    ) -> SessionContext:
        """创建本地浏览器会话"""
        import os
        profile_base = os.getenv('PROFILE_STORAGE', '/data/profiles')
        profile_dir = os.path.join(profile_base, session_id)
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)

        instance = await self._local_pool.allocate(
            session_id=session_id,
            profile_dir=profile_dir,
        )
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(cdp_url=instance.cdp_url, is_local=True)
        )
        await browser_session.start()

        # 预热浏览：在 Akamai/同盾行为模型中建立"正常用户"基线（+2% → 90%+ 隐匿度）
        if not skip_warmup:
            try:
                from browser.human_behavior import HumanBehaviorSimulator
                page = await browser_session.get_current_page()
                simulator = HumanBehaviorSimulator()
                logger.info(f"[{session_id}] Starting warmup browsing to establish behavioral baseline...")
                await simulator.warmup_browsing(page)
                logger.info(f"[{session_id}] Warmup browsing completed")
            except Exception as e:
                logger.warning(f"[{session_id}] Warmup browsing failed (non-fatal): {e}")

        controller = BrowserController(browser_session, session_id)
        return SessionContext(
            session_id=session_id,
            browser_instance=instance,
            browser_session=browser_session,
            controller=controller,
            mode=self.mode,
            browser_mode="local",
            user_id=user_id,
        )

    async def _create_remote_session(
        self, session_id: str, cdp_url: Optional[str], user_id: Optional[str] = None
    ) -> SessionContext:
        """
        创建远程浏览器会话。

        cdp_url 格式: ws://gateway:8001/cdp?apikey=xxx&instance=yyy
        如果未提供 cdp_url，则通过 Gateway /allocate 自动分配。
        """
        gateway_instance_id = None

        if not cdp_url:
            cdp_url, gateway_instance_id = await self._allocate_from_gateway()

        browser_session = BrowserSession(
            browser_profile=BrowserProfile(cdp_url=cdp_url, is_local=False)
        )
        await browser_session.start()

        # 构造虚拟 BrowserInstance
        from models import BrowserInstance
        instance = BrowserInstance(
            instance_id=gateway_instance_id or session_id,
            cdp_url=cdp_url,
            cdp_port=0,
            session_id=session_id,
        )
        controller = BrowserController(browser_session, session_id)
        return SessionContext(
            session_id=session_id,
            browser_instance=instance,
            browser_session=browser_session,
            controller=controller,
            mode=self.mode,
            browser_mode="remote",
            user_id=user_id,
            gateway_instance_id=gateway_instance_id,
        )

    async def _allocate_from_gateway(self) -> tuple[str, str]:
        """
        通过 Gateway /allocate 分配远程浏览器。
        返回 (cdp_url, instance_id)
        """
        import httpx
        gateway_url = os.environ["BROWSER_GATEWAY_URL"]
        api_key = os.environ["BROWSER_GATEWAY_KEY"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{gateway_url}/allocate",
                headers={"X-API-Key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        return data["cdp_url"], data["instance_id"]

    async def get_session(self, session_id: str) -> SessionContext:
        """获取会话，更新最后使用时间"""
        ctx = self.sessions.get(session_id)
        if not ctx:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        ctx.last_used = time.time()
        return ctx

    def get_session_status(self, session_id: str) -> dict:
        """获取会话状态摘要"""
        ctx = self.sessions.get(session_id)
        if not ctx:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return {
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
            "mode": ctx.mode,
            "browser_mode": ctx.browser_mode,
            "created_at": ctx.created_at,
            "last_used": ctx.last_used,
            "idle_time": time.time() - ctx.last_used,
        }

    async def destroy_session(self, session_id: str):
        """销毁会话，释放资源"""
        ctx = self.sessions.pop(session_id, None)
        if not ctx:
            return

        try:
            await ctx.browser_session.kill()
        except Exception:
            pass

        if ctx.browser_mode == "local":
            try:
                await self._local_pool.release(ctx.session_id)
            except Exception:
                pass
        elif ctx.browser_mode == "remote" and ctx.gateway_instance_id:
            await self._release_from_gateway(ctx.gateway_instance_id)

        logger.info(f"Session destroyed: {session_id}")

    async def _release_from_gateway(self, instance_id: str):
        """通过 Gateway /release 释放远程浏览器"""
        try:
            import httpx
            gateway_url = os.environ.get("BROWSER_GATEWAY_URL", "")
            api_key = os.environ.get("BROWSER_GATEWAY_KEY", "")
            if not gateway_url:
                return
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{gateway_url}/release",
                    headers={"X-API-Key": api_key},
                    json={"instance_id": instance_id},
                    timeout=10,
                )
        except Exception as e:
            logger.warning(f"Failed to release gateway instance {instance_id}: {e}")

    def list_sessions(self) -> list[dict]:
        """列出所有会话信息"""
        return [
            {
                "session_id": ctx.session_id,
                "mode": ctx.mode,
                "browser_mode": ctx.browser_mode,
                "cdp_url": ctx.browser_instance.cdp_url,
                "created_at": ctx.created_at,
                "last_used": ctx.last_used,
            }
            for ctx in self.sessions.values()
        ]

    # ──────────────────────────────────────────
    # 监控（空闲超时回收）
    # ──────────────────────────────────────────

    async def _monitor_loop(self):
        import asyncio
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [
                sid for sid, ctx in self.sessions.items()
                if now - ctx.last_used > self.idle_timeout
            ]
            for sid in expired:
                logger.info(f"Session idle timeout, destroying: {sid}")
                await self.destroy_session(sid)
