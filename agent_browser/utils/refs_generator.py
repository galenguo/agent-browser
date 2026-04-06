"""Element reference generator -- uses batch JS evaluation + visibility detection + data-ab-ref injection."""

from playwright.async_api import Page

COMBINED_SELECTOR = "button, a, input, textarea, select"

# Inject data-ab-ref attribute and return element info (prevents position offset issues)
_COMBINED_JS = """(()=>{const e=document.querySelectorAll('%s'),r=[];let refIndex=0;for(let i=0;i<e.length;i++){const l=e[i];if(!l.offsetParent)continue;const ref='@e'+refIndex;l.setAttribute('data-ab-ref',ref);r.push(ref,(t=>(t==='button'||(t==='input'&&/^(submit|button|reset)$/.test(l.getAttribute('type')||'')))?'button':t==='a'?'a':t==='input'||t==='textarea'?'input':t==='select'?'select':t)(l.tagName.toLowerCase()),(l.innerText||'').trim().slice(0,50));refIndex++}return{href:location.href,title:document.title,elements:r}})()"""


async def generate_refs(
    page: Page,
    interactive_only: bool = False,
) -> tuple[list[dict], list[int], dict]:
    """Generate element references + DOM index list + page info (single JS evaluation, injects data-ab-ref attributes)."""
    dom_indices: list[int] = []
    elements: list[dict] = []

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
            ref = flat[i]  # Now use the ref returned by JS directly (already injected into DOM)
            elements.append({"ref": ref, "text": flat[i + 2], "role": flat[i + 1]})
            # dom_indices kept for backward compatibility, but no longer used for element lookup
            dom_indices.append(i // 3)
        except Exception:
            continue

    return elements, dom_indices, page_info
