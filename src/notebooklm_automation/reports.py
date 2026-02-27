"""Report generation utilities for NotebookLM automation.

UI flow (confirmed from screenshots):
  - Studio panel is always visible (three-column layout)
  - "Reports" card in Studio panel — click it to open "Create report" modal
  - Modal shows standard formats (Briefing Doc, Study Guide, Blog Post, Create Your Own)
    plus AI-suggested formats below (takes ~1 min to load)
  - Click the pencil icon on a format to open the description modal
  - Description modal has a textarea pre-filled with a description — append our prompt
  - Click Generate
  - Wait for a new note/artifact to appear in the notebook
"""

import logging
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from notebooklm_automation.config import REPORT_GENERATION_TIMEOUT_S, STANDARD_REPORT_FORMATS
from notebooklm_automation.models import Notebook, ReportResult

logger = logging.getLogger(__name__)

STANDARD_FORMATS: list[str] = STANDARD_REPORT_FORMATS

_UI_SETTLE_MS = 1_500

# ---------------------------------------------------------------------------
# Studio panel — ensure it's visible
# ---------------------------------------------------------------------------
_STUDIO_ANCHOR = "Audio Overview"
_STUDIO_TAB = '.mdc-tab__text-label:text("Studio")'  # legacy fallback

# ---------------------------------------------------------------------------
# Reports card in Studio panel — click to open "Create report" modal
# The card contains text "Reports" and is a button or clickable element
# ---------------------------------------------------------------------------
_REPORTS_CARD = (
    'button:has-text("Reports"), '
    '[role="button"]:has-text("Reports")'
)

# ---------------------------------------------------------------------------
# Inside "Create report" modal:
#   - Standard format buttons: "Briefing Doc", "Study Guide", "Blog Post", "Create Your Own"
#   - AI-suggested formats appear below after ~1 min load
#   - Each format has a pencil/edit icon button to open the description modal
# ---------------------------------------------------------------------------

# Pencil/edit button next to a specific format name inside the modal
# The edit button is a mat-icon-button adjacent to the format card
_FORMAT_EDIT_BTN = 'button[aria-label="Edit {name}"], button[mattooltip="Edit {name}"]'

# Fallback: pencil icon button inside a container that has the format name text
_FORMAT_CARD_EDIT = '[class*="format"]:has-text("{name}") button, div:has-text("{name}") button[mat-icon-button]'

# ---------------------------------------------------------------------------
# Inside the description modal (second modal after clicking pencil):
#   - Textarea pre-filled with AI description — we append our prompt
#   - Generate button
# ---------------------------------------------------------------------------
_DESCRIPTION_TEXTAREA = "textarea"

# Generate button inside the description modal — scoped to mat-dialog to avoid
# matching other Generate buttons on the page
_GENERATE_BTN = (
    'mat-dialog-container button:has-text("Generate"), '
    'mat-dialog-content button:has-text("Generate"), '
    '[role="dialog"] button:has-text("Generate"), '
    'button:has-text("Generate")'
)
# Completed artifact/note — count before and wait for count+1
_ARTIFACT_DONE = "button.artifact-button-content"

# ---------------------------------------------------------------------------
# Prompt appended to the existing description in the textarea
# ---------------------------------------------------------------------------
REPORT_APPEND_PROMPT = (
    " cover the primary secondary and tertiary concepts, walk through how they "
    "connect and what they mean in a larger context. opt for a casual tone and "
    "simpler language avoid academic jargon but not at the cost of diluting "
    "definitions or shallow explanations of difficult concepts."
)


async def _ensure_studio_panel(page: Page, debug_dump_dir: Path | None = None) -> None:
    """Ensure the Studio panel is visible.

    New UI: Studio is always open as the right column. If collapsed, a toggle
    button labelled 'Studio' appears top-right.
    """
    audio_overview = page.get_by_text("Audio Overview").first

    try:
        await audio_overview.wait_for(state="visible", timeout=8_000)
        logger.debug("Studio panel is active and visible.")
    except PlaywrightTimeoutError:
        logger.debug("Studio panel not visible — attempting toggle button")
        studio_toggle = page.get_by_role("button", name="Studio").first
        try:
            await studio_toggle.wait_for(state="visible", timeout=5_000)
            await studio_toggle.click(force=True)
            await audio_overview.wait_for(state="visible", timeout=10_000)
            logger.debug("Clicked Studio toggle — panel now visible")
        except PlaywrightTimeoutError:
            # Legacy mdc-tab fallback
            legacy_tab = page.locator(_STUDIO_TAB)
            try:
                await legacy_tab.wait_for(state="visible", timeout=5_000)
                tab_container = page.locator('.mdc-tab:has(.mdc-tab__text-label:text("Studio"))')
                selected = await tab_container.get_attribute("aria-selected")
                if selected != "true":
                    await legacy_tab.click()
                    await page.wait_for_selector(
                        '#mat-tab-group-0-content-2:not([inert])', timeout=10_000
                    )
                    await page.wait_for_timeout(_UI_SETTLE_MS)
                logger.debug("Studio activated via legacy tab selector")
            except PlaywrightTimeoutError:
                logger.warning("Could not find Studio panel via any known selector.")

    await page.wait_for_timeout(_UI_SETTLE_MS)

    if debug_dump_dir is not None:
        try:
            dump_path = Path(debug_dump_dir) / "studio_panel_reports.html"
            if not dump_path.exists():
                html = await page.content()
                dump_path.write_text(html, encoding="utf-8")
                logger.info("DEBUG: Studio panel HTML dumped to %s", dump_path)
        except Exception as exc:
            logger.warning("DEBUG: Could not dump Studio panel HTML: %s", exc)


async def create_single_report(
    page: Page,
    format_name: str,
    timeout_s: int = REPORT_GENERATION_TIMEOUT_S,
    debug_dump_dir: Path | None = None,
) -> ReportResult:
    """Generate a single report via the 'Create report' modal flow.

    Steps:
        1. Click the Reports card in Studio to open "Create report" modal.
        2. Wait for the modal to open.
        3. Wait for AI-suggested formats to load (up to 90s).
        4. Click the pencil/edit button next to format_name.
        5. In the description modal, append REPORT_APPEND_PROMPT to existing text.
        6. Click Generate.
        7. Wait for a new artifact to appear.

    Requirements: 3.4, 3.5, 4.1, 4.5
    """
    timeout_ms = timeout_s * 1_000
    logger.info("Creating report: %s", format_name)

    try:
        # Step 1: Click the Reports card to open the modal.
        reports_card = page.locator(_REPORTS_CARD).first
        await reports_card.wait_for(state="visible", timeout=10_000)
        await reports_card.click(force=True)
        logger.debug("Clicked Reports card — waiting for modal")
        await page.wait_for_timeout(_UI_SETTLE_MS)

        # Step 2: Wait for "Create report" modal to appear.
        modal_header = page.get_by_text("Create report").first
        await modal_header.wait_for(state="visible", timeout=10_000)
        logger.debug("Create report modal is open")

        # Step 3: Wait for AI-suggested formats to load (they take ~60s).
        # We look for the format_name text to appear inside the modal.
        format_text = page.get_by_text(format_name, exact=True).first
        try:
            await format_text.wait_for(state="visible", timeout=90_000)
            logger.debug("Format '%s' is visible in modal", format_name)
        except PlaywrightTimeoutError:
            logger.warning("Format '%s' did not appear in modal — skipping", format_name)
            # Close modal and return failure
            close_btn = page.locator('button[aria-label="Close"], button:has-text("×")').first
            if await close_btn.count():
                await close_btn.click(force=True)
            return ReportResult(
                notebook_title="",
                report_type=format_name,
                success=False,
                error=f"Format '{format_name}' not found in Create report modal",
            )

        # Step 4: Click the pencil/edit button next to this format.
        # The edit button is inside the same card as the format name.
        # Try aria-label first, then fall back to finding a button near the text.
        edit_btn = page.locator(_FORMAT_EDIT_BTN.format(name=format_name)).first
        if not await edit_btn.count():
            # Fallback: button inside the container that has the format name
            edit_btn = (
                page.locator(f'div:has(> *:has-text("{format_name}")) button')
                .or_(page.locator(f'[class*="card"]:has-text("{format_name}") button'))
                .first
            )

        await edit_btn.wait_for(state="visible", timeout=8_000)
        await edit_btn.click(force=True)
        logger.debug("Clicked edit/pencil for format: %s", format_name)
        await page.wait_for_timeout(_UI_SETTLE_MS)

        # Step 5: In the description modal, append our prompt to existing text.
        textarea = page.locator(_DESCRIPTION_TEXTAREA).first
        await textarea.wait_for(state="visible", timeout=15_000)
        # Move to end of existing text and append
        await textarea.click(force=True)
        await page.keyboard.press("Control+End")
        await page.keyboard.type(REPORT_APPEND_PROMPT)
        logger.debug("Appended prompt to description for: %s", format_name)
        await page.wait_for_timeout(500)

        # Step 6: Count existing artifacts, then click Generate.
        # Dump dialog HTML for selector debugging before attempting the click.
        before_count = await page.locator(_ARTIFACT_DONE).count()

        if debug_dump_dir is not None:
            try:
                dump_path = Path(debug_dump_dir) / f"report_dialog_{format_name.replace(' ', '_')}.html"
                html = await page.content()
                dump_path.write_text(html, encoding="utf-8")
                logger.info("DEBUG: Report dialog HTML dumped to %s", dump_path)
            except Exception as exc:
                logger.warning("DEBUG: Could not dump dialog HTML: %s", exc)

        gen_btn = page.get_by_role("button", name="Generate").first
        try:
            await gen_btn.wait_for(state="visible", timeout=10_000)
        except PlaywrightTimeoutError:
            # Fallback to broader text selector
            gen_btn = page.locator(_GENERATE_BTN).first
            await gen_btn.wait_for(state="visible", timeout=5_000)
        await gen_btn.click(force=True)
        logger.info("Generation initiated for: %s — waiting up to %ds", format_name, timeout_s)

        # Step 7: Wait for generation to complete.
        # Signal: the dialog closes (report is queued/generating) OR a new artifact appears.
        # We wait for the dialog to disappear first — that means generation was accepted.
        try:
            await page.locator('mat-dialog-container').wait_for(state="hidden", timeout=30_000)
            logger.debug("Dialog closed — report generation accepted for: %s", format_name)
        except PlaywrightTimeoutError:
            logger.debug("Dialog did not close — checking for artifact anyway")

        # Then wait for the new artifact to appear in the notebook.
        await page.locator(_ARTIFACT_DONE).nth(before_count).wait_for(
            state="visible", timeout=timeout_ms
        )
        logger.info("Report generated successfully: %s", format_name)
        return ReportResult(notebook_title="", report_type=format_name, success=True)

    except PlaywrightTimeoutError:
        msg = f"Report generation timed out after {timeout_s}s: {format_name}"
        logger.error(msg)
        return ReportResult(notebook_title="", report_type=format_name, success=False, error=msg)
    except Exception as exc:
        msg = f"Failed to create report '{format_name}': {exc}"
        logger.error(msg, exc_info=True)
        return ReportResult(notebook_title="", report_type=format_name, success=False, error=msg)


async def generate_all_reports(
    page: Page,
    notebook: Notebook,
    timeout_s: int = REPORT_GENERATION_TIMEOUT_S,
    debug_dump_dir: Path | None = None,
) -> list[ReportResult]:
    """Generate all standard reports for a notebook.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.5
    """
    logger.info("Generating all reports for notebook: %s", notebook.title)
    results: list[ReportResult] = []

    try:
        # Navigate into the notebook.
        if notebook.element_locator.startswith("http"):
            clean_url = notebook.element_locator.split("?")[0]
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=30_000)
        else:
            selector, _, idx_str = notebook.element_locator.partition("||")
            idx = int(idx_str) if idx_str else 0
            await page.locator(selector).nth(idx).click(timeout=10_000)
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        logger.debug("Opened notebook: %s", notebook.title)
        await page.wait_for_timeout(_UI_SETTLE_MS * 2)

        # Ensure Studio panel is visible.
        await _ensure_studio_panel(page, debug_dump_dir=debug_dump_dir)
        logger.debug("Studio panel active for: %s", notebook.title)

        # Generate each format.
        for fmt in STANDARD_FORMATS:
            result = await create_single_report(page, fmt, timeout_s, debug_dump_dir)
            result.notebook_title = notebook.title
            results.append(result)

            if result.success:
                logger.info("✓ %s — %s", notebook.title, fmt)
            else:
                logger.warning("✗ %s — %s: %s", notebook.title, fmt, result.error)

            await page.wait_for_timeout(_UI_SETTLE_MS)

    except Exception as exc:
        msg = f"Failed to generate reports for notebook '{notebook.title}': {exc}"
        logger.error(msg, exc_info=True)
        results.append(ReportResult(
            notebook_title=notebook.title,
            report_type="(setup)",
            success=False,
            error=msg,
        ))

    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    logger.info(
        "Report generation complete for '%s': %d succeeded, %d failed",
        notebook.title, succeeded, failed,
    )
    return results
