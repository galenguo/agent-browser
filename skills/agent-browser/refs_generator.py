"""元素引用生成器"""
from typing import List, Dict
from playwright.async_api import Page


async def generate_refs(page: Page, interactive_only: bool = False) -> List[Dict]:
    """生成元素引用"""
    snapshot = await page.accessibility.snapshot()
    elements = []

    def traverse(node, depth=0):
        if depth > 10 or not node:
            return

        role = node.get("role", "")
        if interactive_only and role not in ["button", "link", "textbox", "checkbox", "combobox"]:
            if "children" in node:
                for child in node["children"]:
                    traverse(child, depth + 1)
            return

        if role:
            elements.append({
                "type": role,
                "text": node.get("name", ""),
                "role": role
            })

        if "children" in node:
            for child in node["children"]:
                traverse(child, depth + 1)

    if snapshot:
        traverse(snapshot)

    return elements[:50]
