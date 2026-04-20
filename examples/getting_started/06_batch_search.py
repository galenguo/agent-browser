"""Stealth Browser 示例：多站点批量搜索

同时在 Boss直聘 和百度搜索 同一关键词，合并去重后输出。
演示：同一 session 复用、多 adapter 串行执行、结果聚合。

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
  2. 已有对应站点的登录 Cookie
"""
import asyncio
import json
from stealth_browser.adapters.runner import run_adapter
from stealth_browser.main import create_session


# ── 配置：修改这里来搜索不同关键词 ──
SEARCH_QUERY = "Python工程师"
SEARCH_LIMIT = 5


async def search_site(session_id: str, site: str, command: str,
                      args: dict) -> tuple[str, list]:
    """在单个站点执行搜索，返回 (site_name, results) 元组。"""
    label = f"{site}/{command}"
    print(f"\n{'='*50}")
    print(f"正在搜索 [{label}] 关键词: {args.get('query', 'N/A')}")
    print(f"{'='*50}")

    try:
        result = await run_adapter(
            site=site,
            command=command,
            args=args,
            session_id=session_id,
        )

        if isinstance(result, list):
            print(f"  找到 {len(result)} 条结果")
            return label, result
        else:
            print(f"  返回非列表结果: {type(result).__name__}")
            return label, []

    except Exception as e:
        print(f"  搜索失败: {e}")
        return label, []


async def main():
    # 1. 创建会话（所有站点共享同一个浏览器实例）
    session_id = await create_session()
    print(f"Session: {session_id} (共享给所有站点)")

    # 2. 定义搜索任务列表
    tasks = [
        ("boss", "search", {"query": SEARCH_QUERY, "limit": SEARCH_LIMIT}),
        ("baidu", "search", {"query": SEARCH_QUERY, "limit": SEARCH_LIMIT}),
    ]

    # 3. 串行执行每个搜索（避免并发导致 Cookie 冲突）
    all_results: dict[str, list] = {}
    total_items = 0

    for site, command, args in tasks:
        label, items = await search_site(session_id, site, command, args)
        all_results[label] = items
        total_items += len(items)

    # 4. 聚合输出
    print(f"\n{'='*60}")
    print(f"批量搜索完成: {total_items} 条结果来自 {len(all_results)} 个站点")
    print(f"{'='*60}\n")

    for label, items in all_results.items():
        print(f"--- {label} ({len(items)} 条) ---")
        for i, item in enumerate(items[:SEARCH_LIMIT], 1):
            # 通用字段提取（不同 adapter 字段名可能不同）
            title = item.get("title") or item.get("name") or "N/A"
            detail = item.get("salary") or item.get("url") or item.get("link") or ""
            print(f"  {i}. {title}")
            if detail:
                print(f"     {detail}")
        print()

    # 5. 输出原始 JSON（方便管道处理）
    output_file = "batch_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"完整结果已保存到: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
