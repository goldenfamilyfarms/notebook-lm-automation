"""PDF discovery and grouping utilities for NotebookLM automation."""

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from playwright.async_api import Page

from notebooklm_automation.config import NOTEBOOKLM_URL
from notebooklm_automation.models import Notebook

logger = logging.getLogger(__name__)

# Tokens to ignore when inferring topics (too generic to be meaningful)
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for",
        "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "this", "that", "it", "its", "as", "up", "out", "if", "so",
        "pdf", "doc", "document", "file", "report", "paper", "draft",
        "final", "v1", "v2", "v3", "copy", "new", "old", "rev",
    }
)

# Minimum token length to be considered meaningful
_MIN_TOKEN_LEN = 3


@dataclass
class PDFGroup:
    topic: str
    pdf_paths: list[Path] = field(default_factory=list)


class NotebookCreationError(Exception):
    pass


def find_recent_pdfs(downloads_dir: Path, max_age_hours: int = 24) -> list[Path]:
    """Scan downloads_dir for PDF files whose mtime is within max_age_hours.

    Returns list of matching file paths. Logs a warning and returns an empty
    list if downloads_dir does not exist.
    """
    if not downloads_dir.exists():
        logger.warning("Downloads directory does not exist: %s", downloads_dir)
        return []

    cutoff = time.time() - max_age_hours * 3600
    results: list[Path] = []

    for entry in downloads_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".pdf":
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError as exc:
            logger.warning("Could not stat %s: %s", entry, exc)
            continue
        if mtime >= cutoff:
            results.append(entry)

    return results


def _tokenize(stem: str) -> list[str]:
    """Split a filename stem into meaningful lowercase tokens."""
    # Split on non-alphanumeric characters and digit/letter boundaries
    raw = re.split(r"[_\-\s]+", stem)
    tokens: list[str] = []
    for part in raw:
        # Further split on digit/letter transitions (e.g. "report2024" → ["report", "2024"])
        sub = re.split(r"(?<=\D)(?=\d)|(?<=\d)(?=\D)", part)
        for tok in sub:
            tok = tok.lower()
            if len(tok) >= _MIN_TOKEN_LEN and tok not in _STOP_WORDS and not tok.isdigit():
                tokens.append(tok)
    return tokens


def group_pdfs_by_topic(pdf_paths: list[Path]) -> list[PDFGroup]:
    """Group PDF files by inferred domain/topic using filename heuristics.

    Each group gets an inferred topic string used as the notebook title.
    PDFs that don't cluster with others form single-item groups.
    Every input PDF appears in exactly one group.
    """
    if not pdf_paths:
        return []

    if len(pdf_paths) == 1:
        path = pdf_paths[0]
        return [PDFGroup(topic=_topic_from_stem(path.stem), pdf_paths=[path])]

    # Build token sets per file
    token_sets: list[tuple[Path, set[str]]] = [
        (p, set(_tokenize(p.stem))) for p in pdf_paths
    ]

    # Build adjacency: two files are "related" if they share at least one meaningful token
    adjacency: dict[int, set[int]] = defaultdict(set)
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            shared = token_sets[i][1] & token_sets[j][1]
            if shared:
                adjacency[i].add(j)
                adjacency[j].add(i)

    # Connected-components clustering via BFS
    visited: set[int] = set()
    clusters: list[list[int]] = []

    for start in range(len(token_sets)):
        if start in visited:
            continue
        component: list[int] = []
        queue = [start]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            queue.extend(adjacency[node] - visited)
        clusters.append(component)

    # Build PDFGroup for each cluster
    groups: list[PDFGroup] = []
    for cluster in clusters:
        paths_in_cluster = [token_sets[i][0] for i in cluster]
        # Infer topic from common tokens across all files in the cluster
        common_tokens = _common_tokens([token_sets[i][1] for i in cluster])
        if common_tokens:
            topic = " ".join(sorted(common_tokens)).title()
        elif len(paths_in_cluster) == 1:
            topic = _topic_from_stem(paths_in_cluster[0].stem)
        else:
            # Fallback: use tokens from the first file
            topic = _topic_from_stem(paths_in_cluster[0].stem)
        groups.append(PDFGroup(topic=topic, pdf_paths=paths_in_cluster))

    return groups


def _common_tokens(token_sets: list[set[str]]) -> set[str]:
    """Return tokens that appear in ALL of the given token sets."""
    if not token_sets:
        return set()
    result = token_sets[0].copy()
    for ts in token_sets[1:]:
        result &= ts
    return result


def _topic_from_stem(stem: str) -> str:
    """Derive a human-readable topic string from a filename stem."""
    tokens = _tokenize(stem)
    if tokens:
        return " ".join(tokens).title()
    # Last resort: just title-case the raw stem with separators replaced
    return re.sub(r"[_\-]+", " ", stem).strip().title()


async def create_notebook_from_group(page: "Page", group: PDFGroup) -> Notebook:
    """Create a new NotebookLM notebook titled after group.topic.

    Uploads all PDFs in group.pdf_paths as sources. Logs and skips individual
    upload failures (Requirement 9.7). Returns a Notebook instance for
    downstream processing. Raises NotebookCreationError on notebook creation
    failure (Requirement 9.8).
    """
    logger.info("Creating notebook for topic: %s (%d PDFs)", group.topic, len(group.pdf_paths))

    try:
        # Navigate to NotebookLM home
        await page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3_000)  # NotebookLM keeps WS open — networkidle never fires
    except Exception as exc:
        raise NotebookCreationError(f"Failed to navigate to NotebookLM: {exc}") from exc

    # Click "New notebook" button — NotebookLM immediately creates an untitled
    # notebook and navigates into it. There is no title dialog at creation time.
    try:
        new_notebook_btn = (
            page.get_by_role("button", name="New notebook")
            .or_(page.get_by_role("button", name="Create new notebook"))
            .or_(page.locator("[aria-label*='New notebook' i]"))
            .or_(page.locator("[aria-label*='Create new notebook' i]"))
            .or_(page.locator("text=New notebook"))
        )
        await new_notebook_btn.first.click(timeout=15_000)
        # Wait for navigation into the new notebook — use domcontentloaded + fixed wait
        await page.wait_for_load_state("domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)
    except Exception as exc:
        raise NotebookCreationError(f"Could not click 'New notebook' button: {exc}") from exc

    # Capture notebook URL before doing anything else
    notebook_url = page.url
    element_locator = notebook_url if notebook_url != NOTEBOOKLM_URL else f"text={group.topic}"

    # Set the notebook title — NotebookLM renders the title as an <input class="title-input">
    # inside the <editable-project-title> component (confirmed via DOM inspection).
    # The cdk-overlay-backdrop persists indefinitely after notebook creation and
    # intercepts pointer events — force=True bypasses the overlay entirely.
    try:
        title_input = page.locator("input.title-input").first
        await title_input.wait_for(state="visible", timeout=10_000)
        await title_input.click(force=True)
        await page.keyboard.press("Control+a")
        await title_input.fill(group.topic)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1_000)
        logger.debug("Renamed notebook to: %s", group.topic)
    except Exception as exc:
        # Title rename failed — not fatal, notebook was still created.
        # Log a warning and continue with the default "Untitled" name.
        logger.warning("Could not rename notebook to '%s': %s — continuing with default title", group.topic, exc)

    # Upload each PDF as a source
    for pdf_path in group.pdf_paths:
        try:
            await _upload_pdf_source(page, pdf_path)
            logger.info("Uploaded PDF source: %s", pdf_path.name)
        except Exception as exc:
            # Requirement 9.7: log and continue with remaining PDFs
            logger.error("Failed to upload PDF '%s': %s", pdf_path.name, exc)

    return Notebook(
        title=group.topic,
        creation_date=date.today(),
        element_locator=element_locator,
    )


async def _upload_pdf_source(page: "Page", pdf_path: Path) -> None:
    """Upload a single PDF file as a source in the currently open notebook.

    NotebookLM flow:
      1. Click "Add source" (or the source dialog may already be open)
      2. Source-type dialog appears — click "Upload file"
      3. File chooser opens — set the file path
      4. Click "Insert" to confirm
      5. Wait for the source card to appear
    """
    # Step 1: click "Add source" — but only if the source dialog isn't already open
    upload_file_btn = (
        page.get_by_role("button", name="Upload file")
        .or_(page.get_by_role("menuitem", name="Upload file"))
        .or_(page.locator("text=Upload file"))
        .or_(page.get_by_role("button", name="Upload from computer"))
        .or_(page.locator("text=Upload from computer"))
        .or_(page.locator("text=From computer"))
    )

    # Check if the upload dialog is already visible (e.g. opened right after new notebook)
    dialog_already_open = False
    try:
        dialog_already_open = await upload_file_btn.first.is_visible(timeout=2_000)
    except Exception:
        pass

    if not dialog_already_open:
        add_source_btn = (
            page.get_by_role("button", name="Add source")
            .or_(page.locator("[aria-label*='Add source' i]"))
            .or_(page.locator("text=Add source"))
        )
        await add_source_btn.first.click(timeout=15_000)
        await page.wait_for_timeout(1_000)

    # Step 2: click "Upload file" in the source-type dialog
    await upload_file_btn.first.click(timeout=10_000)
    await page.wait_for_timeout(500)

    # Step 3: set the file on the file input via file chooser event
    try:
        async with page.expect_file_chooser(timeout=5_000) as fc_info:
            # Some UI versions open the chooser on the upload button click itself
            pass
        file_chooser = await fc_info.value
        await file_chooser.set_files(str(pdf_path))
    except Exception:
        # Fallback: set directly on the hidden file input
        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(str(pdf_path), timeout=10_000)

    await page.wait_for_timeout(1_000)

    # Step 4: confirm upload — click "Insert" or equivalent
    try:
        confirm_btn = (
            page.get_by_role("button", name="Insert")
            .or_(page.get_by_role("button", name="Upload"))
            .or_(page.get_by_role("button", name="Add"))
            .or_(page.get_by_role("button", name="Done"))
        )
        await confirm_btn.first.click(timeout=8_000)
    except Exception:
        pass  # file input alone is sufficient in some UI versions

    # Step 5: wait for the source card to appear / processing to start
    await page.wait_for_timeout(4_000)
