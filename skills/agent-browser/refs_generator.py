"""元素引用生成器 — 使用 query_selector_all"""
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "combobox",
    "searchbox", "spinbutton", "switch", "radio",
    "menuitem", "tab", "slider", "treeitem",
}

SELECTORS = ["button", "a", "input", "textarea", "select", "[role]"]


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[ElementHandle]]:
    """生成元素引用 + 元素句柄（同索引对应）"""
    handles: List[ElementHandle] = []
    elements: List[Dict] = []
    seen: set = set()

    for sel in SELECTORS:
        try:
            els = await page.query_selector_all(sel)
        except Exception:
            continue
        for el in els:
            try:
                text = (await el.text_content() or "").strip()[:80]

                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                role_attr = await el.get_attribute("role") or ""
                input_type = await el.get_attribute("type") or ""
                placeholder = await el.get_attribute("placeholder") or ""

                # 确定 role — 保持与旧 controller 一致（用 tag 名而非语义 role）
                if role_attr and role_attr not in INTERACTIVE_ROLES:
                    role = role_attr  # 保留自定义 role
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

                # 去重
                key = f"{role}:{text or placeholder}"
                if key in seen:
                    continue
                seen.add(key)

                ref = f"@e{len(handles)}"
                info = {"ref": ref, "text": text or placeholder, "role": role, "tag": tag}
                if input_type:
                    info["type"] = input_type

                elements.append(info)
                handles.append(el)
            except Exception:
                continue

    return elements, handles
