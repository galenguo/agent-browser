"""
会话池管理器

多用户隔离核心：
- 每个用户创建独立 Session
- Session 隔离：独立 profile、cookie、指纹
- 资源限制：最大并发数、超时回收
- 负载均衡：分配到不同浏览器实例
"""

import os
import time
import asyncio
import logging
from uuid import uuid4
from typing import Dict, Optional, Literal

from browser_use import Agent, BrowserSession, BrowserProfile
from models import UserSession, ResourceExhaustedError, SessionNotFoundError, DockerBrowserInstance
from browser.instance_pool import BrowserInstancePool

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
        self.browser_pool = BrowserInstancePool(mode=browser_mode)

        self._monitor_task = None
        self._health_check_task = None

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
        if len(self.sessions) >= self.max_concurrent:
            raise ResourceExhaustedError(
                f"Max concurrent sessions reached ({self.max_concurrent})"
            )

        session_id = f"{user_id}_{uuid4().hex[:8]}"

        # 创建独立 Profile 目录
        profile_base = os.getenv('PROFILE_STORAGE', '/data/profiles')
        profile_dir = os.path.join(profile_base, session_id)
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)

        logger.info(f"📝 Creating session {session_id} for user {user_id} (browser={browser_type})")

        # 分配浏览器实例
        browser_instance = await self.browser_pool.allocate(
            session_id=session_id,
            profile_dir=profile_dir,
            browser_type=browser_type,
        )

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
        """构建浏览器节点公网访问信息（仅 DockerBrowserInstance 且配置了 BROWSER_PUBLIC_HOST 时返回）"""
        if not isinstance(instance, DockerBrowserInstance):
            return None
        if not instance.public_host:
            return None
        return {
            "instance_id": instance.instance_id,
            "public_host": instance.public_host,
            "public_cdp_port": instance.public_cdp_port,
            "public_novnc_port": instance.public_novnc_port,
            "novnc_url": instance.novnc_url,
        }

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
        """运行 Agent 任务（串行锁保证同一 session 不并发）"""
        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found when running task {task_id}")
            return

        async with session.task_lock:
            try:
                logger.info(f"🤖 Running agent for task {task_id} (max_steps={max_steps})")

                async def on_step_start(agent_instance):
                    step_num = agent_instance.state.n_steps + 1
                    try:
                        url = agent_instance.browser_session.current_page.url
                    except Exception:
                        url = "unknown"
                    logger.info(f"🔄 [{task_id}] Step {step_num} starting | url={url}")

                async def on_step_end(agent_instance):
                    step_num = agent_instance.state.n_steps
                    last_step_at = session.tasks[task_id].get("last_step_at") or session.tasks[task_id]["created_at"]
                    elapsed = time.time() - last_step_at
                    action_summary = "unknown"
                    try:
                        history = agent_instance.state.history.history
                        if history:
                            last_result = history[-1]
                            if last_result.model_output:
                                actions = last_result.model_output.action
                                action_summary = str(actions[0])[:80] if actions else "none"
                    except Exception:
                        pass
                    logger.info(f"✅ [{task_id}] Step {step_num} done | action={action_summary} | elapsed={elapsed:.1f}s")
                    session.tasks[task_id]["current_step"] = step_num
                    session.tasks[task_id]["last_step_at"] = time.time()
                    session.mark_activity()

                result = await agent.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end)

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

            except Exception as e:
                logger.error(f"❌ Task {task_id} failed: {e}")
                session.tasks[task_id]["status"] = "failed"
                session.tasks[task_id]["error"] = str(e)

            finally:
                # 关闭本次任务的 BrowserSession，释放 CDP 连接状态
                try:
                    await browser_session.close()
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

        # 释放浏览器实例
        await self.browser_pool.release(session_id)

        logger.info(f"✅ Session closed: {session_id}")

    async def _idle_monitor(self):
        """空闲监控：超时自动关闭会话"""
        while True:
            await asyncio.sleep(60)  # 每分钟检查一次

            idle_sessions = []
            for session_id, session in list(self.sessions.items()):
                if session.is_idle(self.idle_timeout):
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
