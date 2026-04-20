"""Detection module tests — intervention detection logic."""

from stealth_browser.detection import detect_intervention


class TestURLPatterns:
    """URL path pattern detection."""

    def test_login_path(self):
        result = detect_intervention("https://example.com/login", "Home")
        assert result is not None
        assert result["type"] == "login"

    def test_signin_path(self):
        result = detect_intervention("https://example.com/signin", "Home")
        assert result is not None
        assert result["type"] == "login"

    def test_auth_path(self):
        result = detect_intervention("https://example.com/auth", "Home")
        assert result is not None
        assert result["type"] == "login"

    def test_sso_path(self):
        result = detect_intervention("https://example.com/sso/callback", "Home")
        assert result is not None
        assert result["type"] == "login"

    def test_captcha_path(self):
        result = detect_intervention("https://example.com/captcha", "Home")
        assert result is not None
        assert result["type"] == "captcha"

    def test_verify_path(self):
        result = detect_intervention("https://example.com/verify", "Verify")
        assert result is not None
        assert result["type"] == "captcha"

    def test_challenge_path(self):
        result = detect_intervention("https://example.com/challenge", "Challenge")
        assert result is not None
        assert result["type"] == "captcha"

    def test_blocked_path(self):
        result = detect_intervention("https://example.com/blocked", "Home")
        assert result is not None
        assert result["type"] == "access_denied"

    def test_forbidden_path(self):
        result = detect_intervention("https://example.com/forbidden", "Home")
        assert result is not None
        assert result["type"] == "access_denied"

    def test_normal_path_no_intervention(self):
        result = detect_intervention("https://example.com/dashboard", "Dashboard")
        assert result is None

    def test_normal_path_products(self):
        result = detect_intervention("https://example.com/products/123", "Product Detail")
        assert result is None


class TestTitlePatterns:
    """Title pattern detection."""

    def test_chinese_login(self):
        result = detect_intervention("https://example.com/page", "请登录")
        assert result is not None
        assert result["type"] == "login"

    def test_chinese_captcha(self):
        result = detect_intervention("https://example.com/page", "人机验证")
        assert result is not None
        assert result["type"] == "captcha"

    def test_chinese_anti_bot(self):
        result = detect_intervention("https://example.com/page", "操作过于频繁")
        assert result is not None
        assert result["type"] == "anti_bot"

    def test_chinese_access_denied(self):
        result = detect_intervention("https://example.com/page", "安全限制")
        assert result is not None
        assert result["type"] == "access_denied"

    def test_english_login(self):
        result = detect_intervention("https://example.com/page", "Sign In to Continue")
        assert result is not None
        assert result["type"] == "login"

    def test_english_anti_bot(self):
        result = detect_intervention("https://example.com/page", "Just a moment...")
        assert result is not None
        assert result["type"] == "anti_bot"

    def test_english_cloudflare(self):
        result = detect_intervention("https://example.com/page", "Checking your browser")
        assert result is not None
        assert result["type"] == "anti_bot"

    def test_case_insensitive(self):
        result = detect_intervention("https://example.com/page", "ACCESS DENIED")
        assert result is not None
        assert result["type"] == "access_denied"


class TestRedirectDetection:
    """Redirect from requested URL detection."""

    def test_redirect_to_login(self):
        result = detect_intervention(
            "https://example.com/login",
            "Login",
            requested_url="https://example.com/dashboard",
        )
        assert result is not None
        assert result["type"] == "login"
        assert any("redirect" in p for p in result["patterns_matched"])

    def test_no_redirect_same_path(self):
        result = detect_intervention(
            "https://example.com/dashboard",
            "Dashboard",
            requested_url="https://example.com/dashboard",
        )
        assert result is None


class TestTypePriority:
    """anti_bot > captcha > login > access_denied."""

    def test_anti_bot_over_login(self):
        # Title "操作过于频繁" (anti_bot) + URL "/login" (login) -> anti_bot wins
        result = detect_intervention("https://example.com/login", "操作过于频繁")
        assert result is not None
        assert result["type"] == "anti_bot"

    def test_captcha_over_login(self):
        # Title "人机验证" (captcha) + URL "/login" (login) -> captcha wins
        result = detect_intervention("https://example.com/login", "人机验证")
        assert result is not None
        assert result["type"] == "captcha"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_title(self):
        result = detect_intervention("https://example.com/login", "")
        assert result is not None
        assert result["type"] == "login"

    def test_none_url_handled_gracefully(self):
        # urlparse("") should not crash
        result = detect_intervention("", "Login Page")
        assert result is not None

    def test_normal_page_returns_none(self):
        result = detect_intervention("https://example.com/products", "Product List")
        assert result is None

    def test_partial_match_in_title(self):
        # "login" appears in "Login to your account"
        result = detect_intervention("https://example.com/page", "Login to your account")
        assert result is not None
        assert result["type"] == "login"

    def test_patterns_matched_populated(self):
        result = detect_intervention("https://example.com/login", "请登录")
        assert result is not None
        assert len(result["patterns_matched"]) >= 2  # URL + title

    def test_reason_field_populated(self):
        result = detect_intervention("https://example.com/login", "Home")
        assert result is not None
        assert "reason" in result
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0
