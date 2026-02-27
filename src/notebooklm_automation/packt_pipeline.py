"""Full Packt → NotebookLM pipeline.

Orchestrates the complete workflow:
  1. Claim + download all Packt eBooks
  2. Split each PDF by chapter (or 50-page chunks)
  3. Create a NotebookLM notebook per chapter, run full workflow
     (reports, audio overview, MP3 conversion, export to Docs)
  4. After all Packt books are processed, scan Downloads for
     yesterday's PDFs, group by domain, same NotebookLM workflow

Usage (LOCAL):
    python -m notebooklm_automation.packt_pipeline
    python -m notebooklm_automation.packt_pipeline --skip-claim
    python -m notebooklm_automation.packt_pipeline --skip-claim --skip-split
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from notebooklm_automation.auth import ensure_authenticated, launch_browser
from notebooklm_automation.audio import generate_audio_overview
from notebooklm_automation.config import (
    AUDIO_GENERATION_TIMEOUT_S,
    DEFAULT_DOWNLOADS_DIR,
    DEFAULT_USER_DATA_DIR,
    NOTEBOOKLM_URL,
    REPORT_GENERATION_TIMEOUT_S,
)
from notebooklm_automation.converter import ConversionError, convert_to_mp3, sanitize_filename
from notebooklm_automation.export import export_to_docs
from notebooklm_automation.logger_setup import create_output_dir, setup_logging
from notebooklm_automation.main import safe_execute
from notebooklm_automation.models import Notebook, RunSummary
from notebooklm_automation.packt_claim import TITLES, run as claim_and_download
from notebooklm_automation.pdf_discovery import (
    PDFGroup,
    create_notebook_from_group,
    find_recent_pdfs,
    group_pdfs_by_topic,
)
from notebooklm_automation.pdf_splitter import PACKT_BOOKS_DIR, split_pdf
from notebooklm_automation.reports import generate_all_reports

logger = logging.getLogger(__name__)

INVOICE_PATH = Path("C:/Users/derri/notebooklm/packt_invoice_198NcCVCPTmQ4Jcv.pdf")

# Settle time (seconds) after navigating home before starting the next notebook.
_POST_NOTEBOOK_SETTLE_S = 3


# ---------------------------------------------------------------------------
# Notebook processing — shared by both Packt chapter notebooks and PDF groups
# ---------------------------------------------------------------------------

async def process_notebook(
    page,
    notebook: Notebook,
    output_dir: Path,
    summary: RunSummary,
    log: logging.Logger,
) -> None:
    """Run the full workflow for a single notebook: reports → export → audio → MP3.

    Each step is fully awaited and verified before proceeding to the next.
    The function only returns after ALL steps complete (or explicitly fail).
    """
    log.info("Processing notebook: %s", notebook.title)
    summary.notebooks_processed += 1

    notebook_dir = output_dir / sanitize_filename(notebook.title)
    notebook_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Step 1: Generate all reports — wait for every report to complete    #
    # ------------------------------------------------------------------ #
    log.info("[%s] Step 1/3: Generating reports...", notebook.title)
    ok, report_results = await safe_execute(
        generate_all_reports(page, notebook, REPORT_GENERATION_TIMEOUT_S, debug_dump_dir=output_dir),
        f"Generate reports for '{notebook.title}'",
        log,
    )

    if not ok or not report_results:
        summary.errors.append(f"Report generation failed for '{notebook.title}'")
        log.warning("[%s] Reports failed — skipping export step", notebook.title)
    else:
        # Verify each report succeeded before exporting
        for rr in report_results:
            if not rr.success:
                summary.reports_failed += 1
                summary.errors.append(f"Report failed: {rr.report_type} — {rr.error}")
                log.warning("[%s] Report failed: %s", notebook.title, rr.report_type)
                continue

            summary.reports_generated += 1
            log.info("[%s] Report confirmed: %s — exporting...", notebook.title, rr.report_type)

            # ---------------------------------------------------------- #
            # Step 2: Export each confirmed report before moving on       #
            # ---------------------------------------------------------- #
            exp_ok, exp_res = await safe_execute(
                export_to_docs(page, rr.report_type),
                f"Export '{rr.report_type}'",
                log,
            )
            if exp_ok and exp_res and exp_res.success:
                summary.exports_completed += 1
                log.info("[%s] Export confirmed: %s", notebook.title, rr.report_type)
            else:
                summary.exports_failed += 1
                summary.errors.append(f"Export failed: {rr.report_type}")
                log.warning("[%s] Export failed: %s", notebook.title, rr.report_type)

    # ------------------------------------------------------------------ #
    # Step 3: Audio overview — poll until done, then download + convert   #
    # ------------------------------------------------------------------ #
    log.info("[%s] Step 2/3: Generating audio overview...", notebook.title)
    ok, audio_result = await safe_execute(
        generate_audio_overview(page, notebook, notebook_dir, AUDIO_GENERATION_TIMEOUT_S),
        f"Generate audio for '{notebook.title}'",
        log,
    )

    if not ok or not audio_result or not audio_result.success:
        summary.errors.append(f"Audio generation failed for '{notebook.title}'")
        log.warning("[%s] Audio generation failed", notebook.title)
    else:
        summary.audio_generated += 1
        log.info("[%s] Audio generation confirmed", notebook.title)

        # Export audio transcript
        exp_ok, exp_res = await safe_execute(
            export_to_docs(page, f"{notebook.title} — Audio Overview"),
            f"Export audio transcript for '{notebook.title}'",
            log,
        )
        if exp_ok and exp_res and exp_res.success:
            summary.exports_completed += 1
            log.info("[%s] Audio transcript export confirmed", notebook.title)
        else:
            summary.exports_failed += 1
            summary.errors.append(f"Audio transcript export failed: {notebook.title}")

        # Verify the audio file exists on disk before converting
        if audio_result.file_path and audio_result.file_path.exists():
            log.info("[%s] Step 3/3: Converting audio to MP3...", notebook.title)
            try:
                convert_to_mp3(audio_result.file_path, notebook_dir)
                summary.audio_converted += 1
                log.info("[%s] MP3 conversion confirmed", notebook.title)
            except ConversionError as exc:
                msg = f"MP3 conversion failed for '{notebook.title}': {exc}"
                log.error(msg)
                summary.errors.append(msg)
        else:
            msg = f"Audio file not found on disk for '{notebook.title}' — skipping MP3 conversion"
            log.warning(msg)
            summary.errors.append(msg)

    # ------------------------------------------------------------------ #
    # Navigate home and settle before the next notebook                   #
    # ------------------------------------------------------------------ #
    try:
        await page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(_POST_NOTEBOOK_SETTLE_S)
        log.info("[%s] Navigated home — ready for next notebook", notebook.title)
    except Exception as nav_exc:
        log.warning("Could not navigate home after '%s': %s", notebook.title, nav_exc)


# ---------------------------------------------------------------------------
# Phase 1: Claim + download Packt books
# ---------------------------------------------------------------------------

def _collect_existing_packt_pdfs(downloads_dir: Path) -> dict[str, Path]:
    """Return {title: path} for already-downloaded Packt PDFs in downloads_dir.

    Checks both the sanitized filename (underscores) and the original title
    (spaces) since browsers save with the original name.
    """
    existing: dict[str, Path] = {}
    for title in TITLES:
        # Try original title name first (how browsers save files)
        for candidate in (
            downloads_dir / f"{title}.pdf",
            downloads_dir / f"{sanitize_filename(title)}.pdf",
        ):
            if candidate.exists():
                existing[title] = candidate
                break
    return existing


# ---------------------------------------------------------------------------
# Phase 2: Split PDFs
# ---------------------------------------------------------------------------

def split_all_books(downloaded: dict[str, Path]) -> dict[str, list[Path]]:
    """Split each downloaded PDF. Returns {title: [chapter_pdf, ...]}."""
    chapters_map: dict[str, list[Path]] = {}
    for title, pdf_path in downloaded.items():
        book_dir = PACKT_BOOKS_DIR / sanitize_filename(title)
        existing_chapters = sorted(book_dir.glob("Chapter_*.pdf")) + sorted(book_dir.glob("Part_*.pdf"))
        if existing_chapters:
            logger.info("Already split: %s (%d chunks)", title, len(existing_chapters))
            chapters_map[title] = existing_chapters
            continue
        try:
            chapters = split_pdf(pdf_path, title)
            chapters_map[title] = chapters
        except Exception as exc:
            logger.error("Failed to split '%s': %s", title, exc)
            chapters_map[title] = []
    return chapters_map


def collect_existing_chapters(books_dir: Path) -> dict[str, list[Path]]:
    """Walk books_dir and collect pre-split chapter PDFs.

    Each subdirectory is treated as one book. Chapter PDFs are any files
    matching Chapter_*.pdf or Part_*.pdf within that subdirectory.
    Books with no chapter PDFs are skipped with a warning.

    Returns {book_title: [chapter_pdf, ...]} sorted by book title.
    """
    chapters_map: dict[str, list[Path]] = {}
    if not books_dir.exists():
        logger.error("Books directory does not exist: %s", books_dir)
        return chapters_map

    for book_dir in sorted(books_dir.iterdir()):
        if not book_dir.is_dir():
            continue
        chapters = sorted(book_dir.glob("Chapter_*.pdf")) + sorted(book_dir.glob("Part_*.pdf"))
        if not chapters:
            logger.warning("No chapter PDFs found in '%s' — skipping", book_dir.name)
            continue
        chapters_map[book_dir.name] = chapters
        logger.info("Found book: %s (%d chapters)", book_dir.name, len(chapters))

    logger.info(
        "Collected %d books with %d total chapters from %s",
        len(chapters_map),
        sum(len(v) for v in chapters_map.values()),
        books_dir,
    )
    return chapters_map


# ---------------------------------------------------------------------------
# Phase 3: NotebookLM — Packt chapter notebooks
# ---------------------------------------------------------------------------

async def process_packt_books(
    page,
    chapters_map: dict[str, list[Path]],
    output_dir: Path,
    summary: RunSummary,
    log: logging.Logger,
) -> None:
    """Create one notebook per chapter PDF and run the full workflow.

    Each chapter notebook is fully processed (reports, audio, export, MP3)
    before the loop advances to the next chapter.
    """
    for book_title, chapter_pdfs in chapters_map.items():
        if not chapter_pdfs:
            log.warning("No chapters for '%s' — skipping", book_title)
            continue

        log.info("Processing book: %s (%d chapters)", book_title, len(chapter_pdfs))

        for chapter_pdf in chapter_pdfs:
            chapter_name = chapter_pdf.stem.replace("_", " ").title()
            notebook_title = f"{book_title} — {chapter_name}"

            group = PDFGroup(topic=notebook_title, pdf_paths=[chapter_pdf])
            ok, notebook = await safe_execute(
                create_notebook_from_group(page, group),
                f"Create notebook for chapter '{chapter_name}'",
                log,
            )
            if not ok or notebook is None:
                summary.errors.append(f"Notebook creation failed: {notebook_title}")
                summary.notebooks_from_pdfs += 1
                continue

            summary.notebooks_from_pdfs += 1

            # Fully await process_notebook before advancing to the next chapter
            await process_notebook(page, notebook, output_dir, summary, log)
            log.info("Chapter complete: %s", notebook_title)


# ---------------------------------------------------------------------------
# Phase 4: Yesterday's Downloads PDFs
# ---------------------------------------------------------------------------

async def process_yesterdays_pdfs(
    page,
    downloads_dir: Path,
    output_dir: Path,
    summary: RunSummary,
    log: logging.Logger,
) -> None:
    """Scan Downloads for PDFs from yesterday, group by domain, create notebooks."""
    yesterday_paths = find_recent_pdfs(downloads_dir, max_age_hours=48)
    from_last_24h = {str(p) for p in find_recent_pdfs(downloads_dir, max_age_hours=24)}
    yesterday_only = [p for p in yesterday_paths if str(p) not in from_last_24h]

    if not yesterday_only:
        log.info("No PDFs from yesterday found in %s", downloads_dir)
        return

    groups = group_pdfs_by_topic(yesterday_only)
    log.info("Yesterday's PDFs: %d files → %d groups", len(yesterday_only), len(groups))

    for group in groups:
        ok, notebook = await safe_execute(
            create_notebook_from_group(page, group),
            f"Create notebook for group '{group.topic}'",
            log,
        )
        if not ok or notebook is None:
            summary.errors.append(f"Notebook creation failed for group '{group.topic}'")
            continue

        summary.notebooks_from_pdfs += 1

        # Fully await before moving to the next group
        await process_notebook(page, notebook, output_dir, summary, log)
        log.info("Group complete: %s", group.topic)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    invoice_path: Path,
    user_data_dir: Path,
    downloads_dir: Path,
    output_dir: Path,
    skip_claim: bool = False,
    skip_split: bool = False,
    from_existing: bool = False,
    books_dir: Path = PACKT_BOOKS_DIR,
) -> RunSummary:
    log = setup_logging(output_dir)
    summary = RunSummary()

    if from_existing:
        # Skip claim + split entirely — read pre-split chapter PDFs from books_dir
        log.info("--from-existing: reading pre-split chapters from %s", books_dir)
        chapters_map = collect_existing_chapters(books_dir)
        if not chapters_map:
            log.warning("No chapter PDFs found in %s — aborting", books_dir)
            return summary
    else:
        # --- Phase 1: Claim + download ---
        if skip_claim:
            log.info("Skipping claim step — collecting already-downloaded PDFs")
            downloaded = _collect_existing_packt_pdfs(downloads_dir)
            log.info("Found %d existing Packt PDFs", len(downloaded))
        else:
            log.info("Starting Packt claim + download for %d titles", len(TITLES))
            downloaded = await claim_and_download(invoice_path, user_data_dir, downloads_dir)
            log.info("Downloaded %d PDFs", len(downloaded))

        if not downloaded:
            log.warning("No PDFs available — aborting pipeline")
            return summary

        # --- Phase 2: Split PDFs ---
        if skip_split:
            log.info("Skipping split step — collecting existing chapter PDFs")
            chapters_map = {}
            for title in downloaded:
                book_dir = PACKT_BOOKS_DIR / sanitize_filename(title)
                chapters = sorted(book_dir.glob("Chapter_*.pdf")) + sorted(book_dir.glob("Part_*.pdf"))
                chapters_map[title] = chapters
        else:
            log.info("Splitting %d PDFs into chapters", len(downloaded))
            chapters_map = split_all_books(downloaded)

    # --- Phase 3 + 4: NotebookLM ---
    context, page = await launch_browser(user_data_dir)
    try:
        ok, authenticated = await safe_execute(
            ensure_authenticated(page),
            "Google authentication",
            log,
        )
        if not ok or not authenticated:
            summary.errors.append("Authentication failed")
            return summary

        # Phase 3: Packt chapter notebooks (fully sequential)
        await process_packt_books(page, chapters_map, output_dir, summary, log)

        # Phase 4: Yesterday's Downloads PDFs (skipped in from-existing mode)
        if not from_existing:
            log.info("Starting yesterday's Downloads PDF processing")
            await process_yesterdays_pdfs(page, downloads_dir, output_dir, summary, log)

    finally:
        await context.close()
        log.info("Browser closed")

    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Full Packt → NotebookLM pipeline")
    parser.add_argument("--invoice", type=Path, default=INVOICE_PATH)
    parser.add_argument("--user-data-dir", type=Path, default=DEFAULT_USER_DATA_DIR)
    parser.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--books-dir",
        type=Path,
        default=PACKT_BOOKS_DIR,
        help="Root directory containing pre-split book subdirectories (default: packt-books)",
    )
    parser.add_argument(
        "--from-existing",
        action="store_true",
        help=(
            "Read pre-split chapter PDFs directly from --books-dir. "
            "Skips claim and split phases entirely. "
            "Each subdirectory is treated as one book; "
            "each Chapter_*.pdf / Part_*.pdf within it becomes one notebook."
        ),
    )
    parser.add_argument(
        "--skip-claim",
        action="store_true",
        help="Skip Packt claim/download — use already-downloaded PDFs",
    )
    parser.add_argument(
        "--skip-split",
        action="store_true",
        help="Skip PDF splitting — use already-split chapter PDFs",
    )
    args = parser.parse_args()

    output_dir = args.output_dir or create_output_dir()
    summary = asyncio.run(
        run_pipeline(
            args.invoice,
            args.user_data_dir,
            args.downloads_dir,
            output_dir,
            skip_claim=args.skip_claim,
            skip_split=args.skip_split,
            from_existing=args.from_existing,
            books_dir=args.books_dir,
        )
    )

    print("\n" + "=" * 50)
    print(f"  Notebooks processed : {summary.notebooks_processed}")
    print(f"  Notebooks from PDFs : {summary.notebooks_from_pdfs}")
    print(f"  Reports generated   : {summary.reports_generated}")
    print(f"  Audio generated     : {summary.audio_generated}")
    print(f"  Audio converted     : {summary.audio_converted}")
    print(f"  Exports completed   : {summary.exports_completed}")
    print(f"  Errors              : {len(summary.errors)}")
    print("=" * 50)
    for err in summary.errors:
        print(f"  ! {err}")


if __name__ == "__main__":
    main()
