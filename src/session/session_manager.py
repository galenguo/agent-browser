"""
指纹-IP-Cookie 一致性管理。

核心原则：同一个 IP 应始终使用相同的指纹配置。
不一致会被检测到（Akamai 会关联 sensor_data 中的 Canvas/WebGL 指纹与历史记录）。

管理内容：
  - fingerprint_seed：CloakBrowser 用于生成一致指纹的种子
  - proxy：与指纹绑定的代理 IP
  - timezone/locale：与 IP 地理位置一致
  - user_agent：与 OS/浏览器版本一致
  - cookies：持久化 Cookie（避免反复登录）
  - 轮换策略：>300 请求 或 >24 小时 → 轮换 profile
"""
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from browserforge.fingerprints import FingerprintGenerator
    _HAS_BROWSERFORGE = True
except ImportError:
    _HAS_BROWSERFORGE = False
    logger.warning("browserforge not installed, fingerprint generation disabled")


# 默认 IP → 时区映射（生产环境用 GeoIP 库替换）
_TIMEZONE_MAP = {
    "CN": "Asia/Shanghai",
    "US": "America/New_York",
    "JP": "Asia/Tokyo",
    "SG": "Asia/Singapore",
    "DEFAULT": "Asia/Shanghai",
}

_LOCALE_MAP = {
    "CN": "zh-CN",
    "US": "en-US",
    "JP": "ja-JP",
    "SG": "zh-CN",
    "DEFAULT": "zh-CN",
}


class SessionProfile:
    """单个会话的完整配置"""

    def __init__(
        self,
        profile_id: str,
        proxy_ip: Optional[str] = None,
        country_code: str = "CN",
    ):
        self.profile_id = profile_id
        self.proxy = proxy_ip
        self.country_code = country_code

        # 指纹种子（CloakBrowser 使用 seed 生成一致的 C++ 级指纹）
        self.fingerprint_seed = random.randint(0, 2**32 - 1)

        # 地理一致性
        self.timezone = _TIMEZONE_MAP.get(country_code, _TIMEZONE_MAP["DEFAULT"])
        self.locale = _LOCALE_MAP.get(country_code, _LOCALE_MAP["DEFAULT"])

        # 生成真实分布的指纹
        if _HAS_BROWSERFORGE:
            gen = FingerprintGenerator(browser="chrome")
            fp = gen.generate(os="windows")
            self.user_agent = fp.navigator.userAgent
            self.screen_width = fp.screen.width
            self.screen_height = fp.screen.height
        else:
            self.user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            self.screen_width = 1920
            self.screen_height = 1080

        self.cookies: dict = {}
        self.created_at = time.time()
        self.request_count = 0
        self.last_used_at = time.time()

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "proxy": self.proxy,
            "country_code": self.country_code,
            "fingerprint_seed": self.fingerprint_seed,
            "timezone": self.timezone,
            "locale": self.locale,
            "user_agent": self.user_agent,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "cookies": self.cookies,
            "created_at": self.created_at,
            "request_count": self.request_count,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionProfile":
        p = cls.__new__(cls)
        for k, v in data.items():
            setattr(p, k, v)
        return p


class SessionProfileManager:
    """
    指纹-IP-Cookie 一致性管理器。

    Usage:
        manager = SessionProfileManager(storage_dir="/data/profiles")
        profile = manager.get_or_create("proxy-1", proxy_ip="1.2.3.4")
        # 使用 profile.timezone, profile.locale, profile.cookies 等
        manager.record_request(profile.profile_id)
        if manager.should_rotate(profile.profile_id):
            profile = manager.rotate("proxy-1")
    """

    MAX_REQUESTS_PER_PROFILE = 300
    MAX_PROFILE_AGE_SECONDS = 86400  # 24 小时

    def __init__(self, storage_dir: str = os.getenv("PROFILE_STORAGE", "/data/profiles")):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, SessionProfile] = {}
        self._load_all()

    def get_or_create(
        self,
        key: str,
        proxy_ip: Optional[str] = None,
        country_code: str = "CN",
    ) -> SessionProfile:
        """获取已有 profile 或创建新的"""
        if key in self._profiles:
            profile = self._profiles[key]
            if not self.should_rotate(key):
                profile.last_used_at = time.time()
                return profile
            # 需要轮换
            logger.info(f"Profile {key} needs rotation")
            return self.rotate(key, proxy_ip=proxy_ip, country_code=country_code)

        return self._create(key, proxy_ip=proxy_ip, country_code=country_code)

    def _create(
        self,
        key: str,
        proxy_ip: Optional[str] = None,
        country_code: str = "CN",
    ) -> SessionProfile:
        profile_id = f"{key}_{int(time.time())}_{random.randint(1000, 9999)}"
        profile = SessionProfile(
            profile_id=profile_id,
            proxy_ip=proxy_ip,
            country_code=country_code,
        )
        self._profiles[key] = profile
        self._save(key)
        logger.info(f"Created profile {profile_id} for key={key}, tz={profile.timezone}")
        return profile

    def rotate(
        self,
        key: str,
        proxy_ip: Optional[str] = None,
        country_code: str = "CN",
    ) -> SessionProfile:
        """轮换 profile（保留 cookies 逻辑，但换新指纹）"""
        old_profile = self._profiles.pop(key, None)
        new_profile = self._create(key, proxy_ip=proxy_ip, country_code=country_code)
        if old_profile:
            logger.info(
                f"Rotated profile {old_profile.profile_id} → {new_profile.profile_id} "
                f"(requests={old_profile.request_count})"
            )
        return new_profile

    def should_rotate(self, key: str) -> bool:
        """判断是否需要轮换"""
        profile = self._profiles.get(key)
        if not profile:
            return True
        if profile.request_count >= self.MAX_REQUESTS_PER_PROFILE:
            return True
        if time.time() - profile.created_at >= self.MAX_PROFILE_AGE_SECONDS:
            return True
        return False

    def record_request(self, key: str) -> None:
        """记录一次请求（用于轮换判断）"""
        if key in self._profiles:
            self._profiles[key].request_count += 1
            self._profiles[key].last_used_at = time.time()
            # 每 50 次请求持久化一次
            if self._profiles[key].request_count % 50 == 0:
                self._save(key)

    def save_cookies(self, key: str, cookies: dict) -> None:
        """持久化 Cookie"""
        if key in self._profiles:
            self._profiles[key].cookies = cookies
            self._save(key)

    def _save(self, key: str) -> None:
        """持久化 profile 到磁盘"""
        if key not in self._profiles:
            return
        path = self.storage_dir / f"{key}.json"
        try:
            path.write_text(json.dumps(self._profiles[key].to_dict(), ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save profile {key}: {e}")

    def _load_all(self) -> None:
        """从磁盘加载所有 profile"""
        for path in self.storage_dir.glob("*.json"):
            key = path.stem
            try:
                data = json.loads(path.read_text())
                self._profiles[key] = SessionProfile.from_dict(data)
                logger.debug(f"Loaded profile {key}")
            except Exception as e:
                logger.warning(f"Failed to load profile {key}: {e}")
