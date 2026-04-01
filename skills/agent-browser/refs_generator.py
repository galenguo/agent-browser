"""元素引用生成器 — 使用批量 JS 评估"""
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "combobox",
    "searchbox", "spinbutton", "switch", "radio",
    "menuitem", "tab", "slider", "treeitem",
}

COMBINED_SELECTOR = "button, a, input, textarea, select"

# JS 批量提取脚本：一次调用获取所有元素属性
_BATCH_EXTRACT_JS = """
() => {
    const els = document.querySelectorAll('%s');
    return Array.from(els).map((el, i) => ({
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || '').trim().substring(0, 80),
        role_attr: el.getAttribute('role') || '',
        input_type: el.getAttribute('type') || '',
        placeholder: el.getAttribute('placeholder') || '',
        index: i
    }));
}
"""


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[ElementHandle]]:
    """生成元素引用 + 元素句柄（单次 JS 评估批量获取）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []

    # 1. 单次 JS 评估获取所有元素属性（无 DOM roundtrip 开销）
    try:
        raw_attrs = await page.evaluate(_BATCH_EXTRACT_JS % COMBINED_SELECTOR)
    except Exception:
        return elements, handles

    # 2. 获取元素句柄（仍需 query_selector_all 用于 click/fill）
    try:
        els = await page.query_selector_all(COMBINED_SELECTOR)
    except Exception:
        return elements, handles

    for el, attrs in zip(els, raw_attrs):
        try:
            tag = attrs["tag"]
            role_attr = attrs["role_attr"]
            input_type = attrs["input_type"]
            text = attrs["text"]
            placeholder = attrs["placeholder"]

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
            info = {"ref": ref, "text": text or placeholder, "role": role, "tag": tag}
            if input_type:
                info["type"] = input_type

            elements.append(info)
            handles.append(el)
        except Exception:
            continue

    return elements, handles
