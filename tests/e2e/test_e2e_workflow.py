"""
E2E Workflow Test -- Full agent_browser API lifecycle.

Validates the complete user workflow:
  1. create_session -> get a browser session
  2. open_page -> navigate to a URL
  3. snapshot -> inspect page elements
  4. evaluate -> extract data via JS
  5. scroll -> page interaction
  6. delete_session -> clean up

Prerequisites:
  - CloakBrowser running on 127.0.0.1:19222 (or any CDP-compatible browser)
  - Tests are auto-skipped if no browser is detected (@pytest.mark.requires_browser)
"""
import pytest

from agent_browser import AgentBrowser, SkillConfig


@pytest.mark.requires_browser
class TestE2EWorkflow:
    """Full lifecycle E2E test through the public API."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, cdp_url):
        """Complete workflow: create -> navigate -> snapshot -> extract -> delete."""
        cfg = SkillConfig(cdp_url=cdp_url)
        ab = AgentBrowser(cfg)

        # Step 1: Create session
        session_id = await ab.create_session()
        assert session_id, "Session ID should be non-empty"
        print(f"[E2E] Session created: {session_id}")

        try:
            # Step 2: Navigate to example.com
            await ab.open_page("https://example.com", session_id=session_id)
            print("[E2E] Navigated to example.com")

            # Step 3: Snapshot page elements
            snap = await ab.snapshot(session_id=session_id)
            assert snap is not None, "Snapshot should return data"
            assert isinstance(snap, dict), "Snapshot should be a dict"
            print(f"[E2E] Snapshot: {len(snap)} elements")

            # Step 4: Extract data via JS
            title = await ab.evaluate(
                "document.title", session_id=session_id
            )
            assert title, "Page title should be non-empty"
            assert isinstance(title, str), "Title should be a string"
            print(f"[E2E] Page title: {title}")

            url = await ab.evaluate(
                "window.location.href", session_id=session_id
            )
            assert url, "URL should be non-empty"
            assert "example" in url.lower(), f"URL should contain 'example', got {url}"
            print(f"[E2E] URL: {url}")

            # Step 5: Scroll interaction
            await ab.scroll(300, session_id=session_id)
            print("[E2E] Scrolled successfully")

        finally:
            # Step 6: Clean up
            await ab.delete_session(session_id)
            print(f"[E2E] Session deleted: {session_id}")

    @pytest.mark.asyncio
    async def test_evaluate_structured_data(self, cdp_url):
        """Extract structured data (links, headings) from a real page."""
        cfg = SkillConfig(cdp_url=cdp_url)
        ab = AgentBrowser(cfg)

        session_id = await ab.create_session()
        try:
            await ab.open_page("https://example.com", session_id=session_id)

            # Extract all links as structured data
            links = await ab.evaluate(
                """() => {
                    const links = [];
                    document.querySelectorAll('a').forEach(a => links.push({
                        text: a.textContent.trim(),
                        href: a.href
                    }));
                    return links;
                }""",
                session_id=session_id,
            )
            assert isinstance(links, list), "Links should be a list"
            assert len(links) > 0, "example.com should have at least one link"
            assert all("href" in link for link in links), "Each link should have href"
            print(f"[E2E] Found {len(links)} links: {[l['text'] for l in links]}")

            # Extract heading
            h1 = await ab.evaluate(
                """() => {
                    const el = document.querySelector('h1');
                    return el ? el.textContent.trim() : null;
                }""",
                session_id=session_id,
            )
            assert h1, "example.com should have an h1"
            print(f"[E2E] H1: {h1}")
        finally:
            await ab.delete_session(session_id)

    @pytest.mark.asyncio
    async def test_context_manager(self, cdp_url):
        """Test AgentBrowser as an async context manager."""
        cfg = SkillConfig(cdp_url=cdp_url)

        async with AgentBrowser(cfg) as ab:
            session_id = await ab.create_session()
            try:
                await ab.open_page("https://example.com", session_id=session_id)
                title = await ab.evaluate("document.title", session_id=session_id)
                assert title
                print(f"[E2E] Context manager title: {title}")
            finally:
                await ab.delete_session(session_id)


@pytest.mark.requires_browser
class TestE2EPipelineWorkflow:
    """Pipeline engine E2E test with inline steps."""

    @pytest.mark.asyncio
    async def test_execute_navigate_and_evaluate(self, cdp_url):
        """Execute a minimal pipeline: navigate + evaluate."""
        from agent_browser.pipeline.executor import execute_pipeline

        steps = [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "evaluate", "expression": "document.title"},
        ]

        cfg = SkillConfig(cdp_url=cdp_url)
        ab = AgentBrowser(cfg)
        session_id = await ab.create_session()

        try:
            result = await execute_pipeline(
                steps=steps,
                session_id=session_id,
                config=cfg,
            )
            assert result is not None, "Pipeline should return a result"
            print(f"[E2E Pipeline] Result: {result}")
        finally:
            await ab.delete_session(session_id)
