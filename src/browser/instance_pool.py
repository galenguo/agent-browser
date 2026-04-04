"""
浏览器实例池

支持两种模式：
1. local: 本地启动 CloakBrowser 进程
2. docker: 启动 Docker 容器中的 CloakBrowser
"""

import os
import asyncio
import logging
from typing import Literal, Optional
from models import (
    BrowserInstance,
    LocalBrowserInstance,
    DockerBrowserInstance,
)


logger = logging.getLogger(__name__)


class PortAllocator:
    """端口分配器"""

    def __init__(self, start: int = 19222, end: int = 19300):
        self.start = start
        self.end = end
        self.allocated = set()

    def allocate(self) -> int:
        """分配一个可用端口"""
        for port in range(self.start, self.end + 1):
            if port not in self.allocated:
                self.allocated.add(port)
                return port
        raise RuntimeError(f"No available ports in range {self.start}-{self.end}")

    def release(self, port: int):
        """释放端口"""
        self.allocated.discard(port)


class BrowserInstancePool:
    """浏览器实例池 - 支持本地和 Docker 两种模式"""

    def __init__(self, mode: Literal["local", "docker"] = "local"):
        self.mode = mode
        self.instances = {}
        self.port_allocator = PortAllocator(start=19222, end=19300)
        self.novnc_port_allocator = PortAllocator(
            start=int(os.getenv('NOVNC_PORT_START', '6080')),
            end=int(os.getenv('NOVNC_PORT_END', '6200')),
        )
        self._docker_client = None  # 延迟初始化，复用
        self._debug_mode = os.getenv('DEBUG_CONTAINERS', 'false').lower() == 'true'
        logger.info(f"🔧 BrowserInstancePool initialized in {mode} mode")

    async def allocate(
        self,
        session_id: str,
        profile_dir: str,
        browser_type: str = "chromium",
    ) -> BrowserInstance:
        """分配浏览器实例"""
        if self.mode == "local":
            return await self._allocate_local(session_id, profile_dir)
        else:
            return await self._allocate_docker(session_id, profile_dir)

    async def _allocate_local(
        self,
        session_id: str,
        profile_dir: str,
    ) -> LocalBrowserInstance:
        """启动本地 CloakBrowser 进程"""
        from browser.stealth_launcher import launch_stealth_browser

        cdp_port = self.port_allocator.allocate()

        logger.info(f"🚀 Launching local browser for session {session_id} on port {cdp_port}")

        # 使用 stealth_launcher 启动浏览器
        pw, browser, cdp_url = await launch_stealth_browser(
            headless=False,
            proxy=None,
            user_data_dir=profile_dir,
            cdp_port=cdp_port,
        )

        instance = LocalBrowserInstance(
            instance_id=f"local_{session_id}",
            cdp_url=cdp_url,
            cdp_port=cdp_port,
            playwright=pw,
            browser=browser,
            session_id=session_id,
        )

        self.instances[session_id] = instance
        logger.info(f"✅ Local browser instance created: {instance.instance_id}")
        return instance

    def _get_docker_client(self):
        """获取或创建 Docker 客户端（复用连接）"""
        if self._docker_client is None:
            import docker
            self._docker_client = docker.from_env()
        return self._docker_client

    async def _allocate_docker(
        self,
        session_id: str,
        profile_dir: str,
    ) -> DockerBrowserInstance:
        """启动 Docker 容器中的 CloakBrowser"""
        cdp_port = self.port_allocator.allocate()
        container_name = f"browser_{session_id}"

        logger.info(f"🐳 Launching Docker browser for session {session_id}")

        client = self._get_docker_client()

        # debug 模式下保留容器用于排查日志，否则自动清理
        auto_remove = not self._debug_mode

        # 检查是否在 Docker 容器内运行（API 容器）
        in_docker = os.path.exists('/.dockerenv')

        if in_docker:
            # 模式 D：API 容器 → 浏览器容器（通过 Docker 网络）
            # 容器内路径 → 宿主机路径转换
            # HOST_PROFILE_PATH 是宿主机上 profile 目录的绝对路径
            host_profile_base = os.getenv('HOST_PROFILE_PATH')
            if not host_profile_base:
                raise RuntimeError(
                    "HOST_PROFILE_PATH must be set in Docker mode "
                    "(host path that maps to PROFILE_STORAGE)"
                )
            # profile_dir 是容器内路径 /data/profiles/{session_id}
            # 提取 session 子目录名，拼接到宿主机路径
            session_subdir = os.path.basename(profile_dir)
            host_profile_dir = os.path.join(host_profile_base, session_subdir)

            container = client.containers.run(
                "agent-browser-browser:latest",
                name=container_name,
                detach=True,
                shm_size='128mb',
                mem_limit='2g',
                environment={
                    'CDP_PORT': '19222',
                    'HEADLESS': 'false',
                    'PROFILE_STORAGE': '/data/profiles',
                },
                ports={
                    '6080/tcp': None,  # noVNC（宿主机动态端口）
                    '5900/tcp': None,  # VNC 直连（宿主机动态端口）
                },
                volumes={
                    host_profile_dir: {
                        'bind': '/data/profiles',
                        'mode': 'rw'
                    }
                },
                network='agent-browser-network',  # 共享网络
                auto_remove=auto_remove,
            )

            # CDP URL 使用 IP 地址（Chrome 拒绝非 IP/localhost 的 Host header）
            import socket
            try:
                container_ip = socket.gethostbyname(container_name)
            except Exception:
                # 容器刚启动时 DNS 可能还没注册，等待后重试
                import asyncio
                await asyncio.sleep(3)
                container_ip = socket.gethostbyname(container_name)
            cdp_url = f"http://{container_ip}:19222"

            # 读取公网访问配置（用于告知用户浏览器节点地址）
            public_host = os.getenv('BROWSER_PUBLIC_HOST', 'www.aiecho.site')
            port_offset = int(os.getenv('BROWSER_PORT_OFFSET', '0'))

            public_cdp_port = None  # Mode D: CDP 不对外暴露（内部网络）
            public_novnc_port = None
            novnc_url = None
            if public_host:
                container.reload()
                ports = container.ports or {}
                novnc_mapping = ports.get('6080/tcp')
                if novnc_mapping:
                    host_port = int(novnc_mapping[0]['HostPort'])
                    public_novnc_port = host_port + port_offset
                    novnc_url = f"http://{public_host}:{public_novnc_port}/vnc.html"

        else:
            # 模式 B：本地 API → Docker 浏览器（通过端口映射）
            novnc_port = self.novnc_port_allocator.allocate()
            container = client.containers.run(
                "agent-browser-browser:latest",
                name=container_name,
                detach=True,
                shm_size='128mb',
                mem_limit='1g',
                ports={
                    '19222/tcp': cdp_port,   # 映射到宿主机动态端口
                    '6080/tcp': novnc_port,  # noVNC（固定端口范围）
                },
                environment={
                    'CDP_PORT': '19222',
                    'HEADLESS': 'false',
                    'PROFILE_STORAGE': '/data/profiles',
                },
                volumes={
                    profile_dir: {
                        'bind': '/data/profiles',
                        'mode': 'rw'
                    }
                },
                auto_remove=auto_remove,
            )

            # CDP URL 使用 localhost
            cdp_url = f"http://localhost:{cdp_port}"

            # 读取公网访问配置（用于告知用户浏览器节点地址）
            public_host = os.getenv('BROWSER_PUBLIC_HOST', 'www.aiecho.site')
            port_offset = int(os.getenv('BROWSER_PORT_OFFSET', '0'))

            public_novnc_port = novnc_port + port_offset
            novnc_url = f"http://{public_host}:{public_novnc_port}/vnc.html" if public_host else None
            public_cdp_port = cdp_port + port_offset if public_host else None

        # 等待容器内浏览器启动
        await self._wait_cdp_ready(cdp_url, timeout=30)

        instance = DockerBrowserInstance(
            instance_id=container_name,
            cdp_url=cdp_url,
            cdp_port=cdp_port,
            container=container,
            session_id=session_id,
            container_name=container_name,
            novnc_host_port=novnc_port if not in_docker else None,
            public_host=public_host,
            public_cdp_port=public_cdp_port,
            public_novnc_port=public_novnc_port,
            novnc_url=novnc_url,
        )

        self.instances[session_id] = instance
        logger.info(f"✅ Docker browser instance created: {instance.instance_id}")
        return instance

    async def _wait_cdp_ready(self, cdp_url: str, timeout: int = 30):
        """等待 CDP 端口就绪"""
        import aiohttp
        from urllib.parse import urlparse

        parsed = urlparse(cdp_url)
        host = parsed.hostname
        port = parsed.port or 19222

        # Chrome DevTools HTTP 端点会拒绝非 IP/localhost 的 Host header
        # 解析容器名到 IP 地址用于健康检查
        check_url = cdp_url
        try:
            import socket
            ip = socket.gethostbyname(host)
            check_url = f"http://{ip}:{port}"
        except Exception:
            pass  # 回退使用原始 URL

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{check_url}/json/version",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"✅ CDP ready at {cdp_url}")
                            return
            except Exception:
                pass
            await asyncio.sleep(1)

        raise TimeoutError(f"CDP not ready at {cdp_url} after {timeout}s")

    async def release(self, session_id: str):
        """释放浏览器实例"""
        instance = self.instances.pop(session_id, None)
        if not instance:
            logger.warning(f"⚠️  Instance not found for session {session_id}")
            return

        logger.info(f"🔒 Releasing browser instance: {instance.instance_id}")

        if isinstance(instance, LocalBrowserInstance):
            # 关闭本地浏览器进程
            try:
                await instance.browser.close()
                await instance.playwright.stop()
                logger.info(f"✅ Local browser closed: {instance.instance_id}")
            except Exception as e:
                logger.warning(f"Failed to close local browser: {e}")

        elif isinstance(instance, DockerBrowserInstance):
            # 停止并删除容器
            try:
                instance.container.stop(timeout=10)
                if self._debug_mode:
                    # debug 模式下手动删除（auto_remove=False）
                    try:
                        instance.container.remove(force=True)
                    except Exception:
                        pass  # 容器可能已被删除
                logger.info(f"✅ Docker container stopped: {instance.container_name}")
            except Exception as e:
                logger.warning(f"Failed to stop Docker container: {e}")
            # 释放 noVNC 端口（Mode B）
            if instance.novnc_host_port:
                self.novnc_port_allocator.release(instance.novnc_host_port)

        # 释放端口
        self.port_allocator.release(instance.cdp_port)
