"""Export reports and audio transcripts to Google Docs.

Handles the export-to-Google-Docs action for generated reports and audio
overview transcripts inside NotebookLM.

Requirements: 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from notebooklm_automation.models import ExportResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Playwright selectors for the Export UI
# ---------------------------------------------------------------------------

# The share / export menu button on a report or audio transcript panel.
# NotebookLM typically uses a "more options" (three-dot) or share icon.
_SHARE_BUTTON_SELECTOR = (
    'button[aria-label*="Share" i], '
    'button[aria-label*="Export" i], '
    'button[aria-label*="More" i], '
    'button[aria-label*="more_vert" i], '
    'button:has(mat-icon:text("more_vert")), '
    'button:has(mat-icon:text("share"))'
)

# Menu item inside the share/export dropdown that triggers Google Docs export.
_EXPORT_TO_DOCS_SELECTOR = (
    'button:has-text("Google Docs"), '
    '[role="menuitem"]:has-text("Google Docs"), '
    'button:has-text("Export to Google Docs"), '
    '[role="menuitem"]:has-text("Export to Google Docs"), '
    'a:has-text("Google Docs")'
)

# Confirmation element that appears after a successful export — typically a
# toast notification, snackbar, or dialog with a link to the created doc.
_EXPORT_CONFIRMATION_SELECTOR = (
    '[role="alert"], '
    '.cdk-overlay-container [role="status"], '
    'snack-bar-container, '
    'div:has-text("Exported to Google Docs"), '
    'div:has-text("exported"), '
    'a[href*="docs.google.com"]'
)

# Timeout for the export confirmation to appear (ms).
_EXPORT_CONFIRMATION_TIMEOUT_MS = 60_000

# Pause between UI interactions to let the DOM settle (ms).
_UI_SETTLE_MS = 1_000


async def export_to_docs(page: Page, item_name: str) -> ExportResult:
    """Trigger the export-to-Google-Docs action for a report or audio transcript.

    Steps:
        1. Locate and click the share/export button for the current item.
        2. Click the "Export to Google Docs" menu option.
        3. Wait for the export confirmation toast/dialog.
        4. Return an ``ExportResult`` indicating success or failure.

    On failure the error is logged and an ``ExportResult`` with
    ``success=False`` is returned so the caller can continue with remaining
    exports (req 7.4).

    Requirements: 7.1, 7.2, 7.3, 7.4
    """
    logger.info("Exporting to Google Docs: %s", item_name)

    try:
        # 1. Click the share / export menu button.
        share_btn = page.locator(_SHARE_BUTTON_SELECTOR).first
        await share_btn.click(timeout=10_000)
        logger.debug("Opened share/export menu for: %s", item_name)
        await page.wait_for_timeout(_UI_SETTLE_MS)

        # 2. Click "Export to Google Docs" in the dropdown.
        export_option = page.locator(_EXPORT_TO_DOCS_SELECTOR).first
        await export_option.click(timeout=10_000)
        logger.debug("Clicked 'Export to Google Docs' for: %s", item_name)

        # 3. Wait for the export confirmation (req 7.3).
        await page.wait_for_selector(
            _EXPORT_CONFIRMATION_SELECTOR,
            state="visible",
            timeout=_EXPORT_CONFIRMATION_TIMEOUT_MS,
        )
        logger.info("Export confirmed for: %s", item_name)

        return ExportResult(item_name=item_name, success=True)

    except PlaywrightTimeoutError:
        msg = f"Export timed out for '{item_name}'"
        logger.error(msg)
        return ExportResult(item_name=item_name, success=False, error=msg)

    except Exception as exc:
        msg = f"Export failed for '{item_name}': {exc}"
        logger.error(msg, exc_info=True)
        return ExportResult(item_name=item_name, success=False, error=msg)
