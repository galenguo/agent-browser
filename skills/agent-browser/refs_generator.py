"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
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
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    const els = document.querySelectorAll('%s');
    return Array.from(els).map((el, i) => {
        const rect = el.getBoundingClientRect();
        const inViewport = rect.top < vh && rect.bottom > 0 && rect.left < vw && rect.right > 0;
        const style = window.getComputedStyle(el);
        const hidden = style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || (rect.width === 0 && rect.height === 0);
        return {
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || '').trim().substring(0, 60),
            role_attr: el.getAttribute('role') || '',
            input_type: el.getAttribute('type') || '',
            placeholder: el.getAttribute('placeholder') || '',
            aria_label: el.getAttribute('aria-label') || '',
            href: (el.tagName === 'A' ? (el.href || '') : ''),
            in_viewport: inViewport,
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
    """生成元素引用 + 元素句柄（单次 JS 评估批量获取 + 可见性标记）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []

    # 1. 单次 JS 评估获取所有元素属性（含可见性检测）
    try:
        raw_attrs = await page.evaluate(_BATCH_EXTRACT_JS % COMBINED_SELECTOR)
    except Exception:
        return elements, handles

    # 2. 获取元素句柄（用于 click/fill）
    try:
        els = await page.query_selector_all(COMBINED_SELECTOR)
    except Exception:
        return elements, handles

    for el, attrs in zip(els, raw_attrs):
        try:
            # Skip hidden/invisible elements
            if attrs.get("hidden"):
                continue

            tag = attrs["tag"]
            role_attr = attrs["role_attr"]
            input_type = attrs["input_type"]
            text = attrs["text"]
            placeholder = attrs["placeholder"]
            in_viewport = attrs["in_viewport"]

            if role_attr and role_attr not in INTERACTIVE_ROLES:
                role = role_attr
            elif tag == "button" or (tag == "input" and input_type in ("submit", "button", "reset")):
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
            display_text = text or placeholder or attrs.get("aria_label", "")
            info = {"ref": ref, "text": display_text, "role": role, "tag": tag, "in_viewport": in_viewport}
            if input_type:
                info["type"] = input_type
            if attrs.get("href"):
                info["href"] = attrs["href"]

            elements.append(info)
            handles.append(el)
        except Exception:
            continue

    return elements, handles
