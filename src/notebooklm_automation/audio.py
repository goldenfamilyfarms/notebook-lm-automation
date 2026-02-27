"""Audio overview utilities for NotebookLM automation.

UI flow (confirmed from screenshots):
  - Studio panel is always visible (three-column layout)
  - Audio Overview card has a pencil/customize button: aria-label="Customize Audio Overview"
  - Clicking it opens a modal with:
      - Format options: Deep Dive, Brief, Critique, Debate (click to select)
      - Length options: Short, Default, Long (click to select)
      - Textarea: "What should the AI hosts focus on in this episode?"
      - Generate button
  - Generation takes several minutes; poll for download button
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from notebooklm_automation.config import AUDIO_GENERATION_TIMEOUT_S, AUDIO_POLL_INTERVAL_S
from notebooklm_automation.models import AudioResult, Notebook

logger = logging.getLogger(__name__)

_UI_SETTLE_MS = 1_500

# Audio Overview customize button in Studio panel
_AUDIO_CUSTOMIZE_BTN = 'button[aria-label="Customize Audio Overview"]'

# Format selection inside the modal — click "Deep Dive"
_DEEP_DIVE_BTN = 'button:has-text("Deep Dive")'

# Length selection inside the modal — click "Long"
_LONG_BTN = 'button:has-text("Long")'

# Focus prompt textarea
_FOCUS_TEXTAREA = "textarea"

# Generate button inside the modal
_GENERATE_BTN = 'button:has-text("Generate")'

# Download button — appears when generation completes
_DOWNLOAD_BTN = (
    'button[aria-label*="Download" i], '
    'a[aria-label*="Download" i]'
)

# Generating indicator — visible while audio is being produced
_GENERATING_INDICATOR = (
    '[aria-label*="Generating" i], '
    'button:has-text("Generating"), '
    '.progress-indicator, '
    '[class*="generating" i]'
)

AUDIO_FOCUS_PROMPT = (
    "cover the primary secondary and tertiary concepts, walk through how they "
    "connect and what they mean in a larger context. opt for a casual tone and "
    "simpler language avoid academic jargon but not at the cost of diluting "
    "definitions or shallow explanations of difficult concepts."
)


async def generate_audio_overview(
    page: Page,
    notebook: Notebook,
    download_dir: Path,
    timeout_s: int = AUDIO_GENERATION_TIMEOUT_S,
    debug_dump_dir: Path | None = None,
) -> AudioResult:
    """Configure and generate Audio Overview for a notebook, then download.

    The page must already be navigated into the target notebook.

    Steps:
        1. Click the pencil (Customize Audio Overview) button.
        2. Select Deep Dive format.
        3. Select Long length.
        4. Fill the focus prompt textarea.
        5. Click Generate.
        6. Poll for the download button.
        7. Download the audio file.

    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
    """
    logger.info("Starting audio overview for notebook: %s", notebook.title)

    try:
        # Step 1: Click the Audio Overview customize/pencil button.
        # force=True bypasses persistent cdk-overlay-backdrop overlays.
        customize_btn = page.locator(_AUDIO_CUSTOMIZE_BTN).first
        await customize_btn.wait_for(state="visible", timeout=10_000)
        await customize_btn.click(force=True)
        logger.debug("Opened Audio Overview customize modal")
        await page.wait_for_timeout(_UI_SETTLE_MS)

        # Step 2: Select Deep Dive format.
        deep_dive = page.locator(_DEEP_DIVE_BTN).first
        try:
            await deep_dive.wait_for(state="visible", timeout=5_000)
            await deep_dive.click(force=True)
            logger.debug("Selected Deep Dive format")
            await page.wait_for_timeout(500)
        except PlaywrightTimeoutError:
            logger.debug("Deep Dive button not found — skipping format selection")

        # Step 3: Select Long length.
        long_opt = page.locator(_LONG_BTN).first
        try:
            await long_opt.wait_for(state="visible", timeout=5_000)
            await long_opt.click(force=True)
            logger.debug("Set length to Long")
            await page.wait_for_timeout(500)
        except PlaywrightTimeoutError:
            logger.debug("Long button not found — skipping length selection")

        # Step 4: Fill the focus prompt textarea.
        textarea = page.locator(_FOCUS_TEXTAREA).first
        try:
            await textarea.wait_for(state="visible", timeout=5_000)
            await textarea.click(force=True)
            await page.keyboard.press("Control+a")
            await textarea.fill(AUDIO_FOCUS_PROMPT)
            logger.debug("Entered focus prompt")
            await page.wait_for_timeout(500)
        except PlaywrightTimeoutError:
            logger.debug("Focus textarea not found — skipping prompt entry")

        # Step 5: Click Generate.
        gen_btn = page.locator(_GENERATE_BTN).first
        await gen_btn.wait_for(state="visible", timeout=5_000)
        await gen_btn.click(force=True)
        logger.info(
            "Audio generation initiated — polling every %ds, timeout %ds",
            AUDIO_POLL_INTERVAL_S,
            timeout_s,
        )

        # Step 6: Poll for the download button.
        elapsed = 0
        download_ready = False
        while elapsed < timeout_s:
            dl_btn = page.locator(_DOWNLOAD_BTN).first
            if await dl_btn.count() and await dl_btn.is_visible():
                download_ready = True
                break
            still_generating = bool(await page.locator(_GENERATING_INDICATOR).count())
            logger.info(
                "Audio overview '%s': %ds / %ds elapsed — %s",
                notebook.title,
                elapsed,
                timeout_s,
                "generating..." if still_generating else "waiting...",
            )
            await asyncio.sleep(AUDIO_POLL_INTERVAL_S)
            elapsed += AUDIO_POLL_INTERVAL_S

        if not download_ready:
            msg = f"Audio overview timed out after {timeout_s}s for '{notebook.title}'"
            logger.warning(msg)
            return AudioResult(notebook_title=notebook.title, file_path=None, success=False, error=msg)

        logger.info("Audio generation complete for: %s", notebook.title)

        # Step 7: Download.
        download_dir.mkdir(parents=True, exist_ok=True)
        dl_btn = page.locator(_DOWNLOAD_BTN).first
        async with page.expect_download(timeout=60_000) as dl_info:
            await dl_btn.click(force=True)

        download = await dl_info.value
        filename = download.suggested_filename or f"{notebook.title}_audio.webm"
        dest = download_dir / filename
        await download.save_as(str(dest))
        logger.info("Audio downloaded to: %s", dest)

        return AudioResult(notebook_title=notebook.title, file_path=dest, success=True)

    except PlaywrightTimeoutError:
        msg = f"Audio overview timed out after {timeout_s}s for '{notebook.title}'"
        logger.warning(msg)
        return AudioResult(notebook_title=notebook.title, file_path=None, success=False, error=msg)

    except Exception as exc:
        msg = f"Audio overview failed for '{notebook.title}': {exc}"
        logger.error(msg, exc_info=True)
        return AudioResult(notebook_title=notebook.title, file_path=None, success=False, error=msg)
