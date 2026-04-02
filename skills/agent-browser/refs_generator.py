"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
import asyncio
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


COMBINED_SELECTOR = "button, a, input, textarea, select"

# 合并的 JS：一次 evaluate 同时返回元素属性 + 页面信息（减少一次 CDP 往返）
_COMBINED_JS = """
() => {
    const els = document.querySelectorAll('%s');
    const items = [];
    for (let i = 0; i < els.length; i++) {
        const el = els[i];
        const rect = el.getBoundingClientRect();
        const s = el.style;
        const hidden = s.display === 'none' || s.visibility === 'hidden' || (rect.width === 0 && rect.height === 0);
        if (hidden) continue;
        const t = el.tagName.toLowerCase();
        const it = el.getAttribute('type') || '';
        const role = (t === 'button' || (t === 'input' && ['submit','button','reset'].includes(it))) ? 'button'
            : t === 'a' ? 'a'
            : (t === 'input' || t === 'textarea') ? 'input'
            : t === 'select' ? 'select'
            : t;
        items.push({
            idx: i,
            role: role,
            text: (el.innerText || '').trim().substring(0, 3),
        });
    }
    return {
        href: location.href,
        title: document.title,
        elements: items
    };
}
"""


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[ElementHandle], Dict]:
    """生成元素引用 + 元素句柄 + 页面信息（单次 JS 评估）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []

    try:
        result = await page.evaluate(_COMBINED_JS % COMBINED_SELECTOR)
    except Exception:
        return elements, handles, {"href": "", "title": ""}

    page_info = {"href": result["href"], "title": result["title"]}

    # 批量获取句柄
    all_handles = await page.query_selector_all(COMBINED_SELECTOR)

    for item in result["elements"]:
        try:
            idx = item["idx"]
            if idx >= len(all_handles):
                continue

            if interactive_only:
                continue

            ref = f"@e{len(handles)}"
            info = {"ref": ref, "text": item["text"], "role": item["role"]}
            elements.append(info)
            handles.append(all_handles[idx])
        except Exception:
            continue

    return elements, handles, page_info
