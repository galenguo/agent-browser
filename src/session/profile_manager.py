"""
Profile 管理器 - 基于 API Key 的持久化 Profile

核心功能：
1. 基于 API Key 创建持久化 Profile
2. Profile 自动复用（同一个 API key）
3. 定期清理过期 Profile（30天不活跃）
4. Profile 统计和监控
"""
import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """用户持久化 Profile"""
    profile_id: str          # user_a1b2c3
    api_key_hash: str        # SHA256 hash
    profile_dir: str         # /data/profiles/user_a1b2c3/
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    session_count: int = 0   # 当前使用此 profile 的 session 数
    total_sessions: int = 0  # 历史总 session 数


class ProfileManager:
    """持久化 Profile 管理器"""

    def __init__(
        self,
        storage_dir: str = "/data/profiles",
        profile_ttl: int = 30 * 24 * 3600  # 30天
    ):
        self.storage_dir = storage_dir
        self.profile_ttl = profile_ttl
        self.profiles: Dict[str, UserProfile] = {}

        # 确保存储目录存在
        os.makedirs(storage_dir, mode=0o700, exist_ok=True)

        # 加载已有的 profiles
        self._load_existing_profiles()

    def _compute_profile_id(self, api_key: str) -> str:
        """计算 API key 的 profile ID"""
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return f"user_{api_key_hash[:12]}"

    def _load_existing_profiles(self):
        """加载已有的 profile 元数据"""
        try:
            for item in os.listdir(self.storage_dir):
                profile_dir = os.path.join(self.storage_dir, item)
                if not os.path.isdir(profile_dir):
                    continue

                metadata_file = os.path.join(profile_dir, ".metadata.json")
                if os.path.exists(metadata_file):
                    with open(metadata_file, 'r') as f:
                        data = json.load(f)
                        profile = UserProfile(**data)
                        self.profiles[profile.profile_id] = profile
                        logger.info(f"Loaded profile: {profile.profile_id}")
        except Exception as e:
            logger.error(f"Failed to load existing profiles: {e}")

    def _save_metadata(self, profile: UserProfile):
        """保存 profile 元数据"""
        try:
            metadata_file = os.path.join(profile.profile_dir, ".metadata.json")
            with open(metadata_file, 'w') as f:
                json.dump(asdict(profile), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save profile metadata: {e}")

    def get_or_create_profile(self, api_key: str) -> UserProfile:
        """获取或创建持久化 profile"""
        profile_id = self._compute_profile_id(api_key)

        # 检查是否已存在
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.last_activity = time.time()
            self._save_metadata(profile)
            logger.info(f"Reusing existing profile: {profile_id}")
            return profile

        # 创建新 profile
        profile_dir = os.path.join(self.storage_dir, profile_id)
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)

        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        profile = UserProfile(
            profile_id=profile_id,
            api_key_hash=api_key_hash,
            profile_dir=profile_dir
        )

        self.profiles[profile_id] = profile
        self._save_metadata(profile)
        logger.info(f"Created new profile: {profile_id}")
        return profile

    def increment_session_count(self, profile_id: str):
        """增加 session 计数"""
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.session_count += 1
            profile.total_sessions += 1
            profile.last_activity = time.time()
            self._save_metadata(profile)

    def decrement_session_count(self, profile_id: str):
        """减少 session 计数"""
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.session_count = max(0, profile.session_count - 1)
            profile.last_activity = time.time()
            self._save_metadata(profile)

    def cleanup_expired_profiles(self) -> List[str]:
        """清理过期的 profile"""
        cleaned = []
        now = time.time()

        for profile_id, profile in list(self.profiles.items()):
            # 只清理没有活跃 session 的 profile
            if profile.session_count == 0:
                idle_time = now - profile.last_activity
                if idle_time > self.profile_ttl:
                    try:
                        # 删除 profile 目录
                        shutil.rmtree(profile.profile_dir, ignore_errors=True)
                        del self.profiles[profile_id]
                        cleaned.append(profile_id)
                        logger.info(f"Cleaned up expired profile: {profile_id} (idle for {idle_time/86400:.1f} days)")
                    except Exception as e:
                        logger.error(f"Failed to cleanup profile {profile_id}: {e}")

        return cleaned

    def get_profile_stats(self) -> Dict:
        """获取 profile 统计信息"""
        total_disk_usage = 0
        profile_list = []

        for profile_id, profile in self.profiles.items():
            # 计算磁盘使用
            disk_usage = 0
            try:
                for root, dirs, files in os.walk(profile.profile_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        if os.path.exists(fp):
                            disk_usage += os.path.getsize(fp)
            except Exception as e:
                logger.warning(f"Failed to calculate disk usage for {profile_id}: {e}")

            total_disk_usage += disk_usage

            profile_list.append({
                "profile_id": profile_id,
                "created_at": profile.created_at,
                "last_activity": profile.last_activity,
                "session_count": profile.session_count,
                "total_sessions": profile.total_sessions,
                "disk_usage_mb": disk_usage / (1024 * 1024),
                "idle_days": (time.time() - profile.last_activity) / 86400
            })

        return {
            "total_profiles": len(self.profiles),
            "active_profiles": sum(1 for p in self.profiles.values() if p.session_count > 0),
            "total_disk_usage_mb": total_disk_usage / (1024 * 1024),
            "profiles": sorted(profile_list, key=lambda x: x["last_activity"], reverse=True)
        }

    def delete_profile(self, profile_id: str) -> bool:
        """手工删除指定 profile"""
        if profile_id not in self.profiles:
            return False

        profile = self.profiles[profile_id]

        # 检查是否有活跃 session
        if profile.session_count > 0:
            logger.warning(f"Cannot delete profile {profile_id}: has {profile.session_count} active sessions")
            return False

        try:
            shutil.rmtree(profile.profile_dir, ignore_errors=True)
            del self.profiles[profile_id]
            logger.info(f"Manually deleted profile: {profile_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete profile {profile_id}: {e}")
            return False
