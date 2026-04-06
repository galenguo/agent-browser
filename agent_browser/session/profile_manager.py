"""
Profile Manager — Persistent profiles based on API Key.

Core features:
1. Create persistent profile based on API Key
2. Auto-reuse profile (same API key)
3. Periodic cleanup of expired profiles (30 days inactive)
4. Profile statistics and monitoring
"""
import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """User persistent profile."""
    profile_id: str          # user_a1b2c3
    api_key_hash: str        # SHA256 hash
    profile_dir: str         # /data/profiles/user_a1b2c3/
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    session_count: int = 0   # Current sessions using this profile
    total_sessions: int = 0  # Historical total session count


class ProfileManager:
    """Persistent profile manager."""

    def __init__(
        self,
        storage_dir: str = "/data/profiles",
        profile_ttl: int = 30 * 24 * 3600  # 30 days
    ):
        self.storage_dir = storage_dir
        self.profile_ttl = profile_ttl
        self.profiles: dict[str, UserProfile] = {}

        # Ensure storage directory exists
        os.makedirs(storage_dir, mode=0o700, exist_ok=True)

        # Load existing profiles
        self._load_existing_profiles()

    def _compute_profile_id(self, api_key: str) -> str:
        """Compute profile ID from API key."""
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return f"user_{api_key_hash[:12]}"

    def _load_existing_profiles(self):
        """Load existing profile metadata."""
        try:
            for item in os.listdir(self.storage_dir):
                profile_dir = os.path.join(self.storage_dir, item)
                if not os.path.isdir(profile_dir):
                    continue

                metadata_file = os.path.join(profile_dir, ".metadata.json")
                if os.path.exists(metadata_file):
                    with open(metadata_file) as f:
                        data = json.load(f)
                        profile = UserProfile(**data)
                        self.profiles[profile.profile_id] = profile
                        logger.info(f"Loaded profile: {profile.profile_id}")
        except Exception as e:
            logger.error(f"Failed to load existing profiles: {e}")

    def _save_metadata(self, profile: UserProfile):
        """Save profile metadata."""
        try:
            metadata_file = os.path.join(profile.profile_dir, ".metadata.json")
            with open(metadata_file, 'w') as f:
                json.dump(asdict(profile), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save profile metadata: {e}")

    def get_or_create_profile(self, api_key: str) -> UserProfile:
        """Get or create a persistent profile."""
        profile_id = self._compute_profile_id(api_key)

        # Check if already exists
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.last_activity = time.time()
            self._save_metadata(profile)
            logger.info(f"Reusing existing profile: {profile_id}")
            return profile

        # Create new profile
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
        """Increment session count."""
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.session_count += 1
            profile.total_sessions += 1
            profile.last_activity = time.time()
            self._save_metadata(profile)

    def decrement_session_count(self, profile_id: str):
        """Decrement session count."""
        if profile_id in self.profiles:
            profile = self.profiles[profile_id]
            profile.session_count = max(0, profile.session_count - 1)
            profile.last_activity = time.time()
            self._save_metadata(profile)

    def cleanup_expired_profiles(self) -> list[str]:
        """Clean up expired profiles."""
        cleaned = []
        now = time.time()

        for profile_id, profile in list(self.profiles.items()):
            # Only clean profiles with no active sessions
            if profile.session_count == 0:
                idle_time = now - profile.last_activity
                if idle_time > self.profile_ttl:
                    try:
                        # Delete profile directory
                        shutil.rmtree(profile.profile_dir, ignore_errors=True)
                        del self.profiles[profile_id]
                        cleaned.append(profile_id)
                        logger.info(f"Cleaned up expired profile: {profile_id} (idle for {idle_time/86400:.1f} days)")
                    except Exception as e:
                        logger.error(f"Failed to cleanup profile {profile_id}: {e}")

        return cleaned

    def get_profile_stats(self) -> dict:
        """Get profile statistics."""
        total_disk_usage = 0
        profile_list = []

        for profile_id, profile in self.profiles.items():
            # Calculate disk usage
            disk_usage = 0
            try:
                for root, _dirs, files in os.walk(profile.profile_dir):
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
        """Manually delete a specific profile."""
        if profile_id not in self.profiles:
            return False

        profile = self.profiles[profile_id]

        # Check for active sessions
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
