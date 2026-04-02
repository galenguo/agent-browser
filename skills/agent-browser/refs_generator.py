"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
import asyncio
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "combobox",
    "searchbox", "spinbutton", "switch", "radio",
    "menuitem", "tab", "slider", "treeitem",
}

COMBINED_SELECTOR = "button, a, input, textarea, select"

# JS 批量提取：一次调用获取所有元素属性 + 视口可见性
_BATCH_EXTRACT_JS = """
() => {
    const els = document.querySelectorAll('%s');
    return Array.from(els).map((el, i) => {
        const rect = el.getBoundingClientRect();
        const s = el.style;
        const hidden = s.display === 'none' || s.visibility === 'hidden' || (rect.width === 0 && rect.height === 0);
        return {
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || '').trim().substring(0, 20),
            input_type: el.getAttribute('type') || '',
            placeholder: el.getAttribute('placeholder') || '',
            hidden: hidden,
            index: i
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

            tag = attrs["tag"]
            input_type = attrs.get("input_type", "")
            text = attrs["text"]
            placeholder = attrs["placeholder"]

            if tag == "button" or (tag == "input" and input_type in ("submit", "button", "reset")):
                role = "button"
            elif tag == "a":
                role = "a"
            elif tag in ("input", "textarea"):
                role = "input"
            elif tag == "select":
                role = "select"
            else:
                role = tag

            if interactive_only and role not in INTERACTIVE_ROLES:
                continue

            ref = f"@e{len(handles)}"
            display_text = text or placeholder
            info = {"ref": ref, "text": display_text, "role": role}

            elements.append(info)
            handles.append(el)
        except Exception:
            continue

    return elements, handles
