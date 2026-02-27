"""Notebook discovery — date parsing, filtering, and browser scraping."""

import logging
from datetime import date, datetime, timedelta

from playwright.async_api import Page

from notebooklm_automation.models import Notebook

logger = logging.getLogger(__name__)


def parse_creation_date(date_text: str) -> date | None:
    """Parse NotebookLM's displayed date string into a date object.

    Handles:
        - "Today"
        - "Yesterday"
        - "Jun 28, 2025" (abbreviated month)
        - "June 28, 2025" (full month name)

    Returns None if the string cannot be parsed.
    """
    stripped = date_text.strip()
    if not stripped:
        return None

    lower = stripped.lower()

    if lower == "today":
        return date.today()

    if lower == "yesterday":
        return date.today() - timedelta(days=1)

    # Try "Jun 28, 2025" (abbreviated) then "June 28, 2025" (full)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(stripped, fmt).date()
        except ValueError:
            continue

    logger.warning("Could not parse creation date: %r", date_text)
    return None


def filter_todays_notebooks(
    notebooks: list[Notebook],
    target_date: date | None = None,
) -> list[Notebook]:
    """Return only notebooks whose creation_date equals target_date (default: today)."""
    target = target_date or date.today()
    return [nb for nb in notebooks if nb.creation_date == target]


# ---------------------------------------------------------------------------
# Playwright selectors based on actual NotebookLM DOM structure.
# Notebooks render as mat-card.project-button-card elements.
# ---------------------------------------------------------------------------
_NOTEBOOK_CARD_SELECTOR = "mat-card.project-button-card"
_NOTEBOOK_TITLE_SELECTOR = "span.project-button-title"
_NOTEBOOK_SUBTITLE_SELECTOR = "div.project-button-subtitle"
# The subtitle contains date + source count separated by · (U+00B7)
# e.g. "Feb 26, 2026·1 source"
_SUBTITLE_SEPARATOR = "\u00b7"

# Maximum scroll attempts before giving up on finding new notebooks.
_MAX_SCROLL_ATTEMPTS = 20

# Pause between scrolls to let the DOM settle (ms).
_SCROLL_PAUSE_MS = 800


async def _scroll_to_load_all(page: Page) -> None:
    """Scroll the notebook list container until no new items appear.

    NotebookLM may lazy-load notebooks as the user scrolls.  We repeatedly
    scroll to the bottom of the list and compare the element count to detect
    when all items have been rendered.
    """
    previous_count = 0
    for _ in range(_MAX_SCROLL_ATTEMPTS):
        items = await page.query_selector_all(_NOTEBOOK_CARD_SELECTOR)
        current_count = len(items)
        if current_count == previous_count:
            break
        previous_count = current_count

        # Scroll the last element into view to trigger lazy loading.
        last = items[-1]
        await last.scroll_into_view_if_needed()
        await page.wait_for_timeout(_SCROLL_PAUSE_MS)

    logger.debug("Scrolling complete — %d notebook elements found", previous_count)


async def find_todays_notebooks(
    page: Page,
    target_date: date | None = None,
) -> list[Notebook]:
    """Scrape the notebook list and return only those created on target_date (default: today).

    Steps:
        1. Scroll to ensure all notebooks are loaded.
        2. Query every mat-card.project-button-card element.
        3. Extract title from span.project-button-title inner text.
        4. Extract date from div.project-button-subtitle (split on · U+00B7).
        5. Parse dates via ``parse_creation_date``; skip unparseable entries.
        6. Filter to target_date via ``filter_todays_notebooks``.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
    """
    await _scroll_to_load_all(page)

    cards = await page.query_selector_all(_NOTEBOOK_CARD_SELECTOR)
    if not cards:
        logger.info("No notebook elements found on the page")
        return []

    all_notebooks: list[Notebook] = []

    for idx, card in enumerate(cards):
        # Extract title from the title span.
        title_el = await card.query_selector(_NOTEBOOK_TITLE_SELECTOR)
        title = (await title_el.inner_text()).strip() if title_el else ""

        if not title:
            logger.warning("Skipping card %d — no title found", idx)
            continue

        # Extract date from the subtitle div.
        # Subtitle format: "Feb 26, 2026·1 source"
        subtitle_el = await card.query_selector(_NOTEBOOK_SUBTITLE_SELECTOR)
        subtitle = (await subtitle_el.inner_text()).strip() if subtitle_el else ""

        date_text = subtitle.split(_SUBTITLE_SEPARATOR)[0].strip() if subtitle else ""

        creation_date = parse_creation_date(date_text)
        if creation_date is None:
            logger.warning(
                "Skipping notebook %r — unparseable date from subtitle: %r",
                title,
                subtitle,
            )
            continue

        # Store the 0-based index; reports.py uses page.locator(...).nth(idx) to click.
        locator = f"{_NOTEBOOK_CARD_SELECTOR}||{idx}"

        all_notebooks.append(
            Notebook(
                title=title,
                creation_date=creation_date,
                element_locator=locator,
            )
        )

    logger.info("Discovered %d total notebook(s)", len(all_notebooks))

    todays = filter_todays_notebooks(all_notebooks, target_date)
    label = target_date.isoformat() if target_date else "today"

    if not todays:
        logger.info("No notebooks match %s — nothing to process", label)
    else:
        logger.info(
            "Found %d notebook(s) created on %s: %s",
            len(todays),
            label,
            ", ".join(nb.title for nb in todays),
        )

    return todays
