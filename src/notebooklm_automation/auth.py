"""Browser launch and Google authentication for NotebookLM."""

import logging
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from notebooklm_automation.config import NOTEBOOKLM_URL, PAGE_LOAD_TIMEOUT_S

logger = logging.getLogger(__name__)


async def launch_browser(user_data_dir: Path) -> tuple[BrowserContext, Page]:
    """Launch Chromium with a persistent user-data directory.

    Uses ``launch_persistent_context`` so cookies / sessions survive across
    runs.  Returns the browser context and its first page.
    """
    user_data_dir.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )

    page = context.pages[0] if context.pages else await context.new_page()
    logger.info("Browser launched with profile at %s", user_data_dir)
    return context, page


def _is_on_notebooklm(page: Page) -> bool:
    """Return True if the current page URL is on notebooklm.google.com."""
    return "notebooklm.google.com" in page.url


async def ensure_authenticated(
    page: Page,
    timeout_s: int = PAGE_LOAD_TIMEOUT_S,
) -> bool:
    """Navigate to NotebookLM and confirm the app loads.

    If a Google login wall is detected the user is prompted to complete
    authentication manually in the browser window.  Returns ``True`` when
    the app is visible, ``False`` on timeout.
    """
    timeout_ms = timeout_s * 1000

    try:
        logger.info("Navigating to %s", NOTEBOOKLM_URL)
        await page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        logger.error("Failed to load %s within %ds", NOTEBOOKLM_URL, timeout_s)
        return False

    # If we're already on NotebookLM and the page has settled, we're good.
    if _is_on_notebooklm(page):
        # Give the app a moment to render before proceeding.
        await page.wait_for_timeout(3_000)
        logger.info("Active session detected — on NotebookLM")
        return True

    # We're on a login/redirect page — prompt for manual login.
    logger.warning("Not on NotebookLM — manual login required")
    input(
        "\n>>> Please log in to your Google account in the browser window, "
        "then press ENTER here to continue... "
    )

    # Wait for the URL to land on notebooklm.google.com.
    try:
        await page.wait_for_url("**/notebooklm.google.com/**", timeout=timeout_ms)
    except Exception:
        # URL check failed — do a final URL inspection.
        if not _is_on_notebooklm(page):
            logger.error("Did not reach NotebookLM within %ds after login", timeout_s)
            return False

    # Give the app time to fully render after redirect.
    await page.wait_for_timeout(5_000)
    logger.info("Authentication successful — NotebookLM loaded")
    return True
