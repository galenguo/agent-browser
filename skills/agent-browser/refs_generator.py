"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
import asyncio
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


COMBINED_SELECTOR = "button, a, input, textarea, select"

# JS 批量提取：一次调用获取所有元素属性 + 视口可见性 + role 推导
_BATCH_EXTRACT_JS = """
() => {
    const els = document.querySelectorAll('%s');
    return Array.from(els).map((el, i) => {
        const rect = el.getBoundingClientRect();
        const s = el.style;
        const hidden = s.display === 'none' || s.visibility === 'hidden' || (rect.width === 0 && rect.height === 0);
        const t = el.tagName.toLowerCase();
        const it = el.getAttribute('type') || '';
        const role = (t === 'button' || (t === 'input' && ['submit','button','reset'].includes(it))) ? 'button'
            : t === 'a' ? 'a'
            : (t === 'input' || t === 'textarea') ? 'input'
            : t === 'select' ? 'select'
            : t;
        return {
            role: role,
            text: (el.innerText || '').trim().substring(0, 5),
            hidden: hidden,
        };
    });
}
"""


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[ElementHandle]]:
    """生成元素引用 + 元素句柄（单次 JS 评估批量获取 + 可见性标记 + 并行获取句柄）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []

    # 1. 并行获取元素属性 + 元素句柄
    try:
        raw_attrs, els = await asyncio.gather(
            page.evaluate(_BATCH_EXTRACT_JS % COMBINED_SELECTOR),
            page.query_selector_all(COMBINED_SELECTOR),
        )
    except Exception:
        return elements, handles

    for el, attrs in zip(els, raw_attrs):
        try:
            # Skip hidden/invisible elements
            if attrs.get("hidden"):
                continue

            role = attrs["role"]
            text = attrs["text"]

            if interactive_only:
                continue

            ref = f"@e{len(handles)}"
            info = {"ref": ref, "text": text, "role": role}

            elements.append(info)
            handles.append(el)
        except Exception:
            continue

    return elements, handles
