"""
Fingerprint-IP-Cookie Consistency Manager.

Core principle: The same IP should always use the same fingerprint configuration.
Inconsistency is detected (Akamai associates Canvas/WebGL fingerprints in sensor_data with history).

Managed content:
  - fingerprint_seed: Seed used by CloakBrowser to generate consistent fingerprints
  - proxy: Proxy IP bound to fingerprint
  - timezone/locale: Consistent with IP geographic location
  - user_agent: Consistent with OS/browser version
  - cookies: Persistent cookies (avoid repeated login)
  - Rotation strategy: >300 requests or >24 hours → rotate profile
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


# Default IP -> timezone mapping (replace with GeoIP library in production)
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
    """Complete configuration for a single session."""

    def __init__(
        self,
        profile_id: str,
        proxy_ip: Optional[str] = None,
        country_code: str = "CN",
    ):
        self.profile_id = profile_id
        self.proxy = proxy_ip
        self.country_code = country_code

        # Fingerprint seed (CloakBrowser uses seed to generate C++-level consistent fingerprints)
        self.fingerprint_seed = random.randint(0, 2**32 - 1)

        # Geographic consistency
        self.timezone = _TIMEZONE_MAP.get(country_code, _TIMEZONE_MAP["DEFAULT"])
        self.locale = _LOCALE_MAP.get(country_code, _LOCALE_MAP["DEFAULT"])

        # Generate realistic-distributed fingerprints
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
    Fingerprint-IP-Cookie consistency manager.

    Usage:
        manager = SessionProfileManager(storage_dir="/data/profiles")
        profile = manager.get_or_create("proxy-1", proxy_ip="1.2.3.4")
        # Use profile.timezone, profile.locale, profile.cookies etc.
        manager.record_request(profile.profile_id)
        if manager.should_rotate(profile.profile_id):
            profile = manager.rotate("proxy-1")
    """

    MAX_REQUESTS_PER_PROFILE = 300
    MAX_PROFILE_AGE_SECONDS = 86400  # 24 hours

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
        """Get existing profile or create a new one."""
        if key in self._profiles:
            profile = self._profiles[key]
            if not self.should_rotate(key):
                profile.last_used_at = time.time()
                return profile
            # Needs rotation
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
        """Rotate profile (keep cookie logic but change fingerprint)."""
        old_profile = self._profiles.pop(key, None)
        new_profile = self._create(key, proxy_ip=proxy_ip, country_code=country_code)
        if old_profile:
            logger.info(
                f"Rotated profile {old_profile.profile_id} -> {new_profile.profile_id} "
                f"(requests={old_profile.request_count})"
            )
        return new_profile

    def should_rotate(self, key: str) -> bool:
        """Determine if profile needs rotation."""
        profile = self._profiles.get(key)
        if not profile:
            return True
        if profile.request_count >= self.MAX_REQUESTS_PER_PROFILE:
            return True
        if time.time() - profile.created_at >= self.MAX_PROFILE_AGE_SECONDS:
            return True
        return False

    def record_request(self, key: str) -> None:
        """Record a request (used for rotation decisions)."""
        if key in self._profiles:
            self._profiles[key].request_count += 1
            self._profiles[key].last_used_at = time.time()
            # Persist every 50 requests
            if self._profiles[key].request_count % 50 == 0:
                self._save(key)

    def save_cookies(self, key: str, cookies: dict) -> None:
        """Persist cookies."""
        if key in self._profiles:
            self._profiles[key].cookies = cookies
            self._save(key)

    def _save(self, key: str) -> None:
        """Persist profile to disk."""
        if key not in self._profiles:
            return
        path = self.storage_dir / f"{key}.json"
        try:
            path.write_text(json.dumps(self._profiles[key].to_dict(), ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save profile {key}: {e}")

    def _load_all(self) -> None:
        """Load all profiles from disk."""
        for path in self.storage_dir.glob("*.json"):
            key = path.stem
            try:
                data = json.loads(path.read_text())
                self._profiles[key] = SessionProfile.from_dict(data)
                logger.debug(f"Loaded profile {key}")
            except Exception as e:
                logger.warning(f"Failed to load profile {key}: {e}")
