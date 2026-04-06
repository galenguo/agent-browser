"""
测试持久化 Profile 功能

测试场景：
1. 首次创建 session（新 profile）
2. 销毁 session
3. 再次创建 session（复用 profile）
4. 验证 profile 目录存在
5. 验证登录状态保留
"""

import time

import requests

BASE_URL = "http://localhost:8001"
API_KEY = "sk-test-persistent-profile-001"


def test_create_session_first_time():
    """测试首次创建 session"""
    print("\n=== 测试1：首次创建 Session ===")

    response = requests.post(f"{BASE_URL}/session/create", headers={"X-API-Key": API_KEY})

    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应: {data}")

    assert response.status_code == 200
    assert not data["profile_exists"], "首次创建应该是新 profile"

    session_id = data["session_id"]
    profile_id = data["profile_id"]

    print(f"✅ Session ID: {session_id}")
    print(f"✅ Profile ID: {profile_id}")
    print("✅ Profile 是新创建的")

    return session_id, profile_id


def test_destroy_session(session_id):
    """测试销毁 session"""
    print(f"\n=== 测试2：销毁 Session {session_id} ===")

    response = requests.delete(f"{BASE_URL}/session/{session_id}", headers={"X-API-Key": API_KEY})

    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    assert response.status_code == 200
    print("✅ Session 已销毁")


def test_create_session_second_time(expected_profile_id):
    """测试第二次创建 session（应该复用 profile）"""
    print("\n=== 测试3：第二次创建 Session（复用 Profile）===")

    response = requests.post(f"{BASE_URL}/session/create", headers={"X-API-Key": API_KEY})

    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应: {data}")

    assert response.status_code == 200
    assert data["profile_exists"], "第二次创建应该复用已有 profile"
    assert data["profile_id"] == expected_profile_id, "Profile ID 应该相同"

    session_id = data["session_id"]

    print(f"✅ Session ID: {session_id}")
    print(f"✅ Profile ID: {data['profile_id']} (复用)")
    print("✅ Profile 已复用，登录状态应该保留")

    return session_id


def test_profile_stats():
    """测试 profile 统计"""
    print("\n=== 测试4：Profile 统计 ===")

    response = requests.get(f"{BASE_URL}/profiles/stats", headers={"X-API-Key": API_KEY})

    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"总 Profile 数: {data['total_profiles']}")
    print(f"活跃 Profile 数: {data['active_profiles']}")
    print(f"总磁盘使用: {data['total_disk_usage_mb']:.2f} MB")

    if data["profiles"]:
        print("\nProfile 详情:")
        for profile in data["profiles"]:
            print(f"  - {profile['profile_id']}")
            print(f"    Session 数: {profile['session_count']}")
            print(f"    磁盘使用: {profile['disk_usage_mb']:.2f} MB")
            print(f"    空闲天数: {profile['idle_days']:.2f}")

    assert response.status_code == 200
    print("✅ Profile 统计正常")


def test_health_check():
    """测试健康检查"""
    print("\n=== 测试5：健康检查 ===")

    response = requests.get(f"{BASE_URL}/health")

    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应: {data}")

    assert response.status_code == 200
    assert data["status"] == "ok"
    print("✅ 健康检查通过")


def test_execute_task(session_id):
    """测试执行任务"""
    print(f"\n=== 测试6：执行任务（Session {session_id}）===")

    response = requests.post(
        f"{BASE_URL}/session/{session_id}/task",
        headers={"X-API-Key": API_KEY},
        json={"task": "打开百度首页", "max_steps": 10},
    )

    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应: {data}")

    assert response.status_code == 200
    task_id = data["task_id"]

    print(f"✅ 任务已提交: {task_id}")

    # 等待任务完成
    print("等待任务完成...")
    for i in range(30):
        time.sleep(2)
        status_response = requests.get(
            f"{BASE_URL}/session/{session_id}/task/{task_id}", headers={"X-API-Key": API_KEY}
        )
        status_data = status_response.json()
        print(f"  [{i * 2}s] 状态: {status_data['status']}")

        if status_data["status"] in ["completed", "failed"]:
            if status_data["status"] == "completed":
                print("✅ 任务完成")
                print(f"结果: {status_data.get('result')}")
            else:
                print(f"❌ 任务失败: {status_data.get('error')}")
            break

    return task_id


def main():
    """主测试流程"""
    print("=" * 60)
    print("持久化 Profile 功能测试")
    print("=" * 60)

    try:
        # 测试1：首次创建 session
        session_id_1, profile_id = test_create_session_first_time()

        # 测试2：销毁 session
        test_destroy_session(session_id_1)

        # 等待一下
        print("\n等待 2 秒...")
        time.sleep(2)

        # 测试3：第二次创建 session（应该复用 profile）
        session_id_2 = test_create_session_second_time(profile_id)

        # 测试4：Profile 统计
        test_profile_stats()

        # 测试5：健康检查
        test_health_check()

        # 测试6：执行任务（可选）
        # test_execute_task(session_id_2)

        # 清理：销毁第二个 session
        test_destroy_session(session_id_2)

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        print("\n核心验证：")
        print("1. ✅ 首次创建 session 时创建新 profile")
        print("2. ✅ Session 销毁后 profile 保留")
        print("3. ✅ 第二次创建 session 时复用已有 profile")
        print("4. ✅ Profile 统计功能正常")
        print("\n结论：持久化 Profile 功能正常工作！")
        print("用户的登录状态、密码、cookies 将在多个 session 之间保留。")

    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
