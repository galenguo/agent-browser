"""Intervention detection -- identifies login, CAPTCHA, and anti-bot states.

Pure function module with no external dependencies.  Used by pool_manager
(server-side) to automatically flag pages that require human intervention,
and by the CLI layer for defence-in-depth checks.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── URL path patterns ────────────────────────────────────────────────────
# (regex, intervention_type)  — matched against the parsed URL path.

_URL_PATTERNS: list[tuple[str, str]] = [
    # Login / authentication
    (r"/login", "login"),
    (r"/signin", "login"),
    (r"/sign-in", "login"),
    (r"/auth/?$", "login"),
    (r"/authenticate", "login"),
    (r"/sso", "login"),
    (r"/oauth", "login"),
    # CAPTCHA / verification
    (r"/captcha", "captcha"),
    (r"/verify", "captcha"),
    (r"/challenge", "captcha"),
    # Access denied / blocked
    (r"/blocked", "access_denied"),
    (r"/denied", "access_denied"),
    (r"/forbidden", "access_denied"),
]

# ── Title patterns ───────────────────────────────────────────────────────
# (substring, intervention_type)  — case-insensitive match against page title.

_TITLE_PATTERNS: list[tuple[str, str]] = [
    # Chinese
    ("安全限制", "access_denied"),
    ("验证", "captcha"),
    ("登录", "login"),
    ("请登录", "login"),
    ("人机验证", "captcha"),
    ("滑动验证", "captcha"),
    ("操作过于频繁", "anti_bot"),
    ("访问受限", "access_denied"),
    # English
    ("access denied", "access_denied"),
    ("sign in", "login"),
    ("log in", "login"),
    ("login", "login"),
    ("captcha", "captcha"),
    ("forbidden", "access_denied"),
    ("just a moment", "anti_bot"),
    ("checking your browser", "anti_bot"),
    ("attention required", "anti_bot"),
    ("please wait", "anti_bot"),
    ("ray id", "anti_bot"),
    ("unusual traffic", "anti_bot"),
    ("are you a robot", "anti_bot"),
]

# ── Type priority (lower = more severe) ──────────────────────────────────

_TYPE_PRIORITY: dict[str, int] = {
    "anti_bot": 0,
    "captcha": 1,
    "login": 2,
    "access_denied": 3,
}

_REASON_MAP: dict[str, str] = {
    "login": "Login page detected -- user authentication required",
    "captcha": "CAPTCHA or verification page detected -- human interaction required",
    "anti_bot": "Anti-bot challenge detected -- browser may be blocked",
    "access_denied": "Access denied or blocked page detected",
}


def detect_intervention(
    url: str,
    title: str,
    requested_url: str = "",
) -> dict | None:
    """Detect if the current page requires human intervention.

    Args:
        url: The actual page URL after navigation.
        title: The page title.
        requested_url: The URL that was originally requested (for redirect detection).

    Returns:
        ``None`` if the page looks normal, or a dict with keys:

        - **type**: ``"login"`` | ``"captcha"`` | ``"anti_bot"`` | ``"access_denied"``
        - **reason**: Human-readable one-line explanation.
        - **patterns_matched**: List of pattern identifiers that triggered.
    """
    matched: list[str] = []
    types_found: set[str] = set()

    # ── Layer 1: URL path patterns ───────────────────────────────────────
    parsed = urlparse(url.lower())
    path = parsed.path.rstrip("/") or "/"

    for pattern, itype in _URL_PATTERNS:
        if re.search(pattern, path):
            matched.append(f"url:{pattern}")
            types_found.add(itype)

    # ── Redirect detection ───────────────────────────────────────────────
    if requested_url:
        req_parsed = urlparse(requested_url.lower())
        if parsed.netloc == req_parsed.netloc and parsed.path != req_parsed.path:
            for pattern, itype in _URL_PATTERNS:
                if re.search(pattern, path) and f"redirect:{pattern}" not in matched:
                    matched.append(f"redirect:{req_parsed.path}->{parsed.path}")
                    types_found.add(itype)

    # ── Layer 2: Title patterns ──────────────────────────────────────────
    title_lower = (title or "").lower()
    for pattern, itype in _TITLE_PATTERNS:
        if pattern.lower() in title_lower:
            matched.append(f"title:{pattern}")
            types_found.add(itype)

    if not matched:
        return None

    # Pick highest-priority type
    best_type = min(types_found, key=lambda t: _TYPE_PRIORITY.get(t, 99))

    return {
        "type": best_type,
        "reason": _REASON_MAP.get(best_type, "Human intervention required"),
        "patterns_matched": matched,
    }
