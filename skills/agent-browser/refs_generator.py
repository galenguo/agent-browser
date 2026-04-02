"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
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
) -> Tuple[List[Dict], List[int], Dict]:
    """生成元素引用 + DOM 索引列表 + 页面信息（单次 JS 评估，无句柄获取）"""
    dom_indices: List[int] = []
    elements: List[Dict] = []

    try:
        result = await page.evaluate(_COMBINED_JS % COMBINED_SELECTOR)
    except Exception:
        return elements, dom_indices, {"href": "", "title": ""}

    page_info = {"href": result["href"], "title": result["title"]}

    for item in result["elements"]:
        try:
            if interactive_only:
                continue

            ref = f"@e{len(dom_indices)}"
            info = {"ref": ref, "text": item["text"], "role": item["role"]}
            elements.append(info)
            dom_indices.append(item["idx"])
        except Exception:
            continue

    return elements, dom_indices, page_info
