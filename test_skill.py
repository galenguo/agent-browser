"""测试 skill 功能"""
import sys
import asyncio
sys.path.insert(0, 'skills')

# 导入 skill（使用 importlib 处理连字符）
import importlib
agent_browser = importlib.import_module('agent-browser')

async def test_skill():
    """测试 skill 基本功能"""
    print("Testing skill functions...")

    # 测试创建会话（使用本地浏览器，不连接远程CDP）
    # 注意：skill 默认需要 CDP，这里我们测试导入是否成功
    print("✅ Skill module imported successfully")
    print(f"✅ Available functions: {dir(agent_browser)}")

    # 验证函数存在
    assert hasattr(agent_browser, 'create_session')
    assert hasattr(agent_browser, 'open_page')
    assert hasattr(agent_browser, 'snapshot')
    assert hasattr(agent_browser, 'click')
    assert hasattr(agent_browser, 'fill')
    assert hasattr(agent_browser, 'delete_session')

    print("\n✅ All skill function signatures verified!")

if __name__ == "__main__":
    asyncio.run(test_skill())
