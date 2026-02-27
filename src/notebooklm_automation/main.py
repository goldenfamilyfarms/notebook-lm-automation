"""Main orchestrator for NotebookLM automation.

Wires together authentication, notebook discovery, report generation,
audio overview, export, and MP3 conversion into a single CLI-driven run.

Requirements: 2.3, 2.4, 8.4
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

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
from notebooklm_automation.discovery import find_todays_notebooks
from notebooklm_automation.export import export_to_docs
from notebooklm_automation.logger_setup import create_output_dir, setup_logging
from notebooklm_automation.models import RunSummary
from notebooklm_automation.pdf_discovery import (
    create_notebook_from_group,
    find_recent_pdfs,
    group_pdfs_by_topic,
)
from notebooklm_automation.reports import generate_all_reports

logger = logging.getLogger(__name__)


async def safe_execute(
    coro: Any,
    description: str,
    logger: logging.Logger,
) -> tuple[bool, Any]:
    """Wrap any async operation with error handling and logging.

    Returns:
        A ``(success, result)`` tuple. On failure *result* is ``None``.
    """
    try:
        result = await coro
        logger.info("Success: %s", description)
        return True, result
    except TimeoutError:
        logger.error("Timeout: %s", description)
        return False, None
    except Exception as e:
        logger.error("Failed: %s — %s", description, e, exc_info=True)
        return False, None


def format_summary(summary: RunSummary) -> str:
    """Format a RunSummary as a human-readable string for printing.

    Validates: Requirement 8.4
    """
    lines = [
        "=" * 50,
        "Run Summary",
        "=" * 50,
        f"  Notebooks processed : {summary.notebooks_processed}",
        f"  Notebooks from PDFs : {summary.notebooks_from_pdfs}",
        f"  Reports generated   : {summary.reports_generated}",
        f"  Reports failed      : {summary.reports_failed}",
        f"  Exports completed   : {summary.exports_completed}",
        f"  Exports failed      : {summary.exports_failed}",
        f"  Audio generated     : {summary.audio_generated}",
        f"  Audio converted     : {summary.audio_converted}",
    ]
    if summary.errors:
        lines.append(f"  Errors ({len(summary.errors)}):")
        for err in summary.errors:
            lines.append(f"    - {err}")
    else:
        lines.append("  Errors              : 0")
    lines.append("=" * 50)
    return "\n".join(lines)


async def run(
    user_data_dir: Path,
    output_dir: Path,
    target_date: date | None = None,
    downloads_dir: Path | None = None,
) -> RunSummary:
    """Full orchestration: auth → discover → PDF discovery → loop(reports → export → audio → convert) → summary.

    Requirements: 2.3, 2.4, 8.4, 9.4, 9.5, 9.6, 9.8, 9.9
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    log = setup_logging(output_dir)
    summary = RunSummary()
    context = None

    try:
        # 1. Launch browser and authenticate.
        log.info("Launching browser with profile: %s", user_data_dir)
        context, page = await launch_browser(user_data_dir)

        ok, authenticated = await safe_execute(
            ensure_authenticated(page),
            "Google authentication",
            log,
        )
        if not ok or not authenticated:
            summary.errors.append("Authentication failed")
            return summary

        # 2. Discover today's notebooks (req 2.3, 2.4).
        ok, notebooks = await safe_execute(
            find_todays_notebooks(page, target_date),
            "Discover today's notebooks",
            log,
        )
        if not ok or notebooks is None:
            summary.errors.append("Notebook discovery failed")
            return summary

        if not notebooks:
            log.info("No notebooks match today's date — will check Downloads for recent PDFs")

        # 3. Scan Downloads folder for recent PDFs and create notebooks (req 9.4–9.8).
        resolved_downloads_dir = downloads_dir or DEFAULT_DOWNLOADS_DIR
        pdf_paths = find_recent_pdfs(resolved_downloads_dir)
        if pdf_paths:
            pdf_groups = group_pdfs_by_topic(pdf_paths)
            log.info("Found %d PDF group(s) from %d recent PDF(s)", len(pdf_groups), len(pdf_paths))
            for group in pdf_groups:
                ok, pdf_notebook = await safe_execute(
                    create_notebook_from_group(page, group),
                    f"Create notebook from PDF group '{group.topic}'",
                    log,
                )
                if ok and pdf_notebook is not None:
                    notebooks.append(pdf_notebook)
                    summary.notebooks_from_pdfs += 1
                else:
                    # Requirement 9.8: log and continue with remaining groups
                    summary.errors.append(f"Notebook creation failed for PDF group '{group.topic}'")
        else:
            log.info("No recent PDFs found in %s — skipping PDF notebook creation", resolved_downloads_dir)

        if not notebooks:
            log.info("No notebooks to process (no date matches, no recent PDFs) — terminating gracefully")
            return summary

        # 4. Process each notebook sequentially (req 2.4, 9.6).
        for notebook in notebooks:
            log.info("Processing notebook: %s", notebook.title)
            summary.notebooks_processed += 1

            notebook_dir = output_dir / sanitize_filename(notebook.title)
            notebook_dir.mkdir(parents=True, exist_ok=True)

            # 3a. Generate all reports.
            ok, report_results = await safe_execute(
                generate_all_reports(page, notebook, REPORT_GENERATION_TIMEOUT_S),
                f"Generate reports for '{notebook.title}'",
                log,
            )

            if ok and report_results:
                for rr in report_results:
                    if rr.success:
                        summary.reports_generated += 1

                        # 3b. Export each successful report to Google Docs.
                        export_ok, export_result = await safe_execute(
                            export_to_docs(page, rr.report_type),
                            f"Export report '{rr.report_type}' to Docs",
                            log,
                        )
                        if export_ok and export_result and export_result.success:
                            summary.exports_completed += 1
                        else:
                            summary.exports_failed += 1
                            summary.errors.append(
                                f"Export failed: {rr.report_type}"
                            )
                    else:
                        summary.reports_failed += 1
                        summary.errors.append(
                            f"Report failed: {rr.report_type} — {rr.error}"
                        )
            else:
                summary.errors.append(
                    f"Report generation failed for '{notebook.title}'"
                )

            # 3c. Generate audio overview.
            ok, audio_result = await safe_execute(
                generate_audio_overview(
                    page, notebook, notebook_dir, AUDIO_GENERATION_TIMEOUT_S,
                ),
                f"Generate audio for '{notebook.title}'",
                log,
            )

            if ok and audio_result and audio_result.success:
                summary.audio_generated += 1

                # 3d. Export audio transcript to Google Docs.
                export_ok, export_result = await safe_execute(
                    export_to_docs(page, f"{notebook.title} — Audio Overview"),
                    f"Export audio transcript for '{notebook.title}' to Docs",
                    log,
                )
                if export_ok and export_result and export_result.success:
                    summary.exports_completed += 1
                else:
                    summary.exports_failed += 1
                    summary.errors.append(
                        f"Audio transcript export failed: {notebook.title}"
                    )

                # 3e. Convert audio to MP3.
                if audio_result.file_path:
                    try:
                        convert_to_mp3(audio_result.file_path, notebook_dir)
                        summary.audio_converted += 1
                        log.info(
                            "Audio converted to MP3 for '%s'", notebook.title,
                        )
                    except ConversionError as exc:
                        msg = f"MP3 conversion failed for '{notebook.title}': {exc}"
                        log.error(msg)
                        summary.errors.append(msg)
            else:
                summary.errors.append(
                    f"Audio generation failed for '{notebook.title}'"
                )

            # Navigate back to the home page before processing the next notebook.
            try:
                from notebooklm_automation.config import NOTEBOOKLM_URL
                await page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(2_000)
            except Exception as nav_exc:
                log.warning("Could not navigate back to home page: %s", nav_exc)

    finally:
        if context:
            await context.close()
            log.info("Browser closed")

    return summary


async def diagnose(user_data_dir: Path) -> None:
    """Dump NotebookLM DOM structure to help identify correct selectors."""
    from notebooklm_automation.auth import ensure_authenticated, launch_browser

    context, page = await launch_browser(user_data_dir)
    try:
        authenticated = await ensure_authenticated(page)
        if not authenticated:
            print("Authentication failed — cannot diagnose")
            return

        await page.wait_for_timeout(3_000)

        # Click the first notebook card to get inside a notebook
        cards = await page.query_selector_all("mat-card.project-button-card")
        if cards:
            await cards[0].click()
            await page.wait_for_timeout(3_000)
            print(f"\nNavigated into notebook. URL: {page.url}\n")
        else:
            print("\nNo notebook cards found — dumping home page DOM\n")

        result = await page.evaluate("""() => {
            const info = {};

            // 1. All buttons on the page
            const buttons = [...document.querySelectorAll('button')];
            info.buttons = buttons.map(b => ({
                text: b.innerText?.trim().slice(0, 80),
                ariaLabel: b.getAttribute('aria-label'),
                classes: b.className,
                id: b.id,
            })).filter(b => b.text || b.ariaLabel).slice(0, 40);

            // 2. All mat-icon text values (Angular Material icons)
            const icons = [...document.querySelectorAll('mat-icon')];
            info.matIcons = [...new Set(icons.map(i => i.innerText?.trim()))].slice(0, 30);

            // 3. Current URL
            info.url = window.location.href;

            // 4. Top-level nav / toolbar items
            const navItems = [...document.querySelectorAll('[role="tab"], [role="menuitem"], mat-tab, .tab-label')];
            info.navItems = navItems.map(n => n.innerText?.trim()).filter(Boolean).slice(0, 20);

            return info;
        }""")

        import json
        print("\n=== NotebookLM DOM Diagnostic ===\n")
        output = json.dumps(result, indent=2)
        print(output)
        # Also write to file for easy sharing
        diag_path = Path("output") / "diagnose.json"
        diag_path.parent.mkdir(exist_ok=True)
        diag_path.write_text(output)
        print(f"\nDiagnostic saved to: {diag_path}")
    finally:
        await context.close()


def main() -> None:
    """CLI entry point with argparse."""
    parser = argparse.ArgumentParser(
        description="NotebookLM Automation — process today's notebooks",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=DEFAULT_USER_DATA_DIR,
        help=f"Chromium user data directory (default: {DEFAULT_USER_DATA_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: timestamped dir under ./output)",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Target date to process (default: today). Example: --date 2026-02-26",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=None,
        help=f"Downloads directory to scan for recent PDFs (default: {DEFAULT_DOWNLOADS_DIR})",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Dump DOM structure to identify correct selectors, then exit",
    )
    args = parser.parse_args()

    if args.diagnose:
        asyncio.run(diagnose(args.user_data_dir))
        return

    if args.output_dir:
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = create_output_dir()

    # On Windows, Playwright requires ProactorEventLoop (the default) for subprocess support.
    # Do NOT switch to WindowsSelectorEventLoopPolicy here.
    summary = asyncio.run(run(args.user_data_dir, output_dir, args.date, args.downloads_dir))
    print(format_summary(summary))


if __name__ == "__main__":
    main()
