"""元素引用生成器 — 使用 query_selector_all"""
import asyncio
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "combobox",
    "searchbox", "spinbutton", "switch", "radio",
    "menuitem", "tab", "slider", "treeitem",
}

SELECTORS = ["button", "a", "input", "textarea", "select"]


async def _get_el_attrs(el: ElementHandle) -> Tuple[str, str, str, str, str]:
    """并行获取元素属性"""
    text, tag, role_attr, input_type, placeholder = await asyncio.gather(
        el.text_content(),
        el.evaluate("e => e.tagName.toLowerCase()"),
        el.get_attribute("role"),
        el.get_attribute("type"),
        el.get_attribute("placeholder"),
    )
    return (
        (text or "").strip()[:80],
        tag or "",
        role_attr or "",
        input_type or "",
        placeholder or "",
    )


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[ElementHandle]]:
    """生成元素引用 + 元素句柄（同索引对应）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []

    # 并行查询所有选择器
    try:
        all_els = await asyncio.gather(
            *[page.query_selector_all(sel) for sel in SELECTORS],
            return_exceptions=True
        )
    except Exception:
        return elements, handles

    for els in all_els:
        if isinstance(els, Exception):
            continue
        # 并行获取所有元素属性
        attrs_list = await asyncio.gather(*[_get_el_attrs(el) for el in els])
        for el, (text, tag, role_attr, input_type, placeholder) in zip(els, attrs_list):
            try:
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
