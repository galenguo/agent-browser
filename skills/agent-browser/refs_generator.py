"""元素引用生成器 — 使用批量 JS 评估 + 可见性检测"""
from typing import List, Dict, Tuple
from playwright.async_api import Page, ElementHandle


COMBINED_SELECTOR = "button, a, input, textarea, select"

# 合并的 JS：一次 evaluate 同时返回元素属性 + 页面信息（减少一次 CDP 往返）
_COMBINED_JS = """(()=>{const e=document.querySelectorAll('%s'),r=[];for(let i=0;i<e.length;i++){const l=e[i],c=l.getBoundingClientRect(),d=l.style;if(d.display==='none'||d.visibility==='hidden'||(c.width===0&&c.height===0))continue;r.push(i,(t=>(t==='button'||(t==='input'&&/^(submit|button|reset)$/.test(l.getAttribute('type')||'')))?'button':t==='a'?'a':t==='input'||t==='textarea'?'input':t==='select'?'select':t)(l.tagName.toLowerCase()),(l.innerText||'').trim().substring(0,3))}return{href:location.href,title:document.title,elements:r}})()"""


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

    flat = result["elements"]
    for i in range(0, len(flat), 3):
        try:
            if interactive_only:
                continue
            ref = f"@e{len(dom_indices)}"
            elements.append({"ref": ref, "text": flat[i + 2], "role": flat[i + 1]})
            dom_indices.append(flat[i])
        except Exception:
            continue

    return elements, dom_indices, page_info
