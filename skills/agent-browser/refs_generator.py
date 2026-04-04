"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测 + data-ab-ref 注入"""
from typing import List, Dict, Tuple
from playwright.async_api import Page


COMBINED_SELECTOR = "button, a, input, textarea, select"

# 注入 data-ab-ref 属性并返回元素信息（防止位置偏移问题）
_COMBINED_JS = """(()=>{const e=document.querySelectorAll('%s'),r=[];let refIndex=0;for(let i=0;i<e.length;i++){const l=e[i];if(!l.offsetParent)continue;const ref='@e'+refIndex;l.setAttribute('data-ab-ref',ref);r.push(ref,(t=>(t==='button'||(t==='input'&&/^(submit|button|reset)$/.test(l.getAttribute('type')||'')))?'button':t==='a'?'a':t==='input'||t==='textarea'?'input':t==='select'?'select':t)(l.tagName.toLowerCase()),(l.innerText||'').trim().slice(0,50));refIndex++}return{href:location.href,title:document.title,elements:r}})()"""


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> Tuple[List[Dict], List[int], Dict]:
    """生成元素引用 + DOM 索引列表 + 页面信息（单次 JS 评估，注入 data-ab-ref 属性）"""
    dom_indices: List[int] = []
    elements: List[Dict] = []

    try:
        result = await page.evaluate(_COMBINED_JS % COMBINED_SELECTOR)
    except Exception:
        return elements, dom_indices, {"href": "", "title": ""}

    page_info = {"href": result["href"], "title": result["title"]}

    flat = result["elements"]
    for i in range(0, len(flat), 3):
        try:
            if interactive_only:
                continue
            ref = flat[i]  # 现在直接使用 JS 返回的 ref（已注入到 DOM）
            elements.append({"ref": ref, "text": flat[i + 2], "role": flat[i + 1]})
            # dom_indices 保留用于向后兼容，但不再用于元素查找
            dom_indices.append(i // 3)
        except Exception:
            continue

    return elements, dom_indices, page_info
