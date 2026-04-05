"""
测试 ProfileManager 核心功能（单元测试）
"""
import sys
import os
import tempfile
import shutil

from agent_browser.session.profile_manager import ProfileManager


def test_profile_manager():
    """测试 ProfileManager 基本功能"""
    print("=" * 60)
    print("测试 ProfileManager 核心功能")
    print("=" * 60)

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    print(f"\n临时目录: {temp_dir}")

    try:
        # 创建 ProfileManager
        manager = ProfileManager(storage_dir=temp_dir, profile_ttl=60)
        print("✅ ProfileManager 创建成功")

        # 测试1：创建新 profile
        print("\n--- 测试1：创建新 profile ---")
        api_key_1 = "sk-test-key-001"
        profile_1 = manager.get_or_create_profile(api_key_1)
        print(f"Profile ID: {profile_1.profile_id}")
        print(f"Profile Dir: {profile_1.profile_dir}")
        print(f"Session Count: {profile_1.session_count}")
        assert os.path.exists(profile_1.profile_dir), "Profile 目录应该存在"
        print("✅ 新 profile 创建成功")

        # 测试2：复用已有 profile
        print("\n--- 测试2：复用已有 profile ---")
        profile_1_again = manager.get_or_create_profile(api_key_1)
        assert profile_1_again.profile_id == profile_1.profile_id, "Profile ID 应该相同"
        print(f"Profile ID: {profile_1_again.profile_id} (相同)")
        print("✅ Profile 复用成功")

        # 测试3：不同 API key 创建不同 profile
        print("\n--- 测试3：不同 API key 创建不同 profile ---")
        api_key_2 = "sk-test-key-002"
        profile_2 = manager.get_or_create_profile(api_key_2)
        assert profile_2.profile_id != profile_1.profile_id, "不同 API key 应该有不同 profile"
        print(f"Profile 1 ID: {profile_1.profile_id}")
        print(f"Profile 2 ID: {profile_2.profile_id}")
        print("✅ 不同 profile 创建成功")

        # 测试4：Session 计数
        print("\n--- 测试4：Session 计数 ---")
        manager.increment_session_count(profile_1.profile_id)
        assert profile_1.session_count == 1, "Session 计数应该为 1"
        print(f"Session Count: {profile_1.session_count}")
        manager.decrement_session_count(profile_1.profile_id)
        assert profile_1.session_count == 0, "Session 计数应该为 0"
        print(f"Session Count: {profile_1.session_count}")
        print("✅ Session 计数功能正常")

        # 测试5：Profile 统计
        print("\n--- 测试5：Profile 统计 ---")
        stats = manager.get_profile_stats()
        print(f"总 Profile 数: {stats['total_profiles']}")
        print(f"活跃 Profile 数: {stats['active_profiles']}")
        print(f"总磁盘使用: {stats['total_disk_usage_mb']:.2f} MB")
        assert stats['total_profiles'] == 2, "应该有 2 个 profile"
        print("✅ Profile 统计功能正常")

        # 测试6：删除 profile
        print("\n--- 测试6：删除 profile ---")
        success = manager.delete_profile(profile_2.profile_id)
        assert success, "删除应该成功"
        assert not os.path.exists(profile_2.profile_dir), "Profile 目录应该被删除"
        stats = manager.get_profile_stats()
        assert stats['total_profiles'] == 1, "应该只剩 1 个 profile"
        print(f"剩余 Profile 数: {stats['total_profiles']}")
        print("✅ Profile 删除功能正常")

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\n临时目录已清理: {temp_dir}")


if __name__ == "__main__":
    test_profile_manager()
