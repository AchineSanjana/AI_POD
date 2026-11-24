"""tests/test_s3_browser.py

Pytest wrapper for Playwright + Chromium browser verification (Step S3: Dashboard & Wizard).
Skipped when Playwright or the Chromium browser is not installed.
"""

import pytest

from scripts.verify_s3_browser import run_with_servers

try:
    import playwright
    from playwright.sync_api import sync_playwright

    # Verify chromium can be located / launched
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(channel="msedge", headless=True)
        browser.close()
    PLAYWRIGHT_CHROMIUM_AVAILABLE = True
except Exception:
    PLAYWRIGHT_CHROMIUM_AVAILABLE = False


@pytest.mark.skipif(
    not PLAYWRIGHT_CHROMIUM_AVAILABLE,
    reason="Playwright or Chromium browser not installed / available",
)
def test_s3_dashboard_browser_verification():
    """Run full Playwright browser verification for S3 across viewports 390x844 and 1280x900."""
    success = run_with_servers(
        base_url="http://127.0.0.1:8000",
        headless=True,
    )
    assert success is True

