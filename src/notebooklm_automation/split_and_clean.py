"""Standalone script: finish PDF splitting + clean junk chapters.

Usage (LOCAL):
    python -m notebooklm_automation.split_and_clean
    python -m notebooklm_automation.split_and_clean --books-dir packt-books --downloads-dir C:/Users/derri/Downloads

What it does:
  1. For every title in TITLES that has a downloaded PDF in downloads-dir,
     split it into chapters (skips books already split).
  2. Walk every book directory under books-dir and delete any chapter PDF
     whose name matches known junk patterns (cover, preface, TOC, etc.).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from notebooklm_automation.config import DEFAULT_DOWNLOADS_DIR
from notebooklm_automation.packt_claim import TITLES
from notebooklm_automation.pdf_splitter import PACKT_BOOKS_DIR, sanitize_filename, split_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Junk chapter patterns — case-insensitive match against the chapter filename
# ---------------------------------------------------------------------------
_JUNK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"cover",
        r"title[_\s-]*page",
        r"copy[_\s-]*right",
        r"copyright",
        r"credits",
        r"preface",
        r"foreword",
        r"acknowledgement",
        r"acknowledgment",
        r"table[_\s-]*of[_\s-]*contents",
        r"\btoc\b",
        r"who[_\s-]*is[_\s-]*this[_\s-]*book[_\s-]*for",
        r"about[_\s-]*the[_\s-]*author",
        r"about[_\s-]*the[_\s-]*reviewer",
        r"contributors",
        r"join[_\s-]*our[_\s-]*discord",
        r"join[_\s-]*our[_\s-]*community",
        r"other[_\s-]*books[_\s-]*you[_\s-]*may[_\s-]*enjoy",
        r"packt[_\s-]*page",
        r"dedication",
        r"index$",
    ]
]


def _is_junk(path: Path) -> bool:
    """Return True if the chapter filename matches a junk pattern."""
    stem = path.stem.lower()
    return any(p.search(stem) for p in _JUNK_PATTERNS)


# ---------------------------------------------------------------------------
# Phase 1: Split any unsplit books
# ---------------------------------------------------------------------------

def split_remaining(downloads_dir: Path, books_dir: Path) -> None:
    logger.info("=== Phase 1: Splitting remaining books ===")
    split_count = 0
    skip_count = 0

    for title in TITLES:
        safe = sanitize_filename(title)
        # Check original title name (browser saves) and sanitized name
        pdf_path = None
        for candidate in (
            downloads_dir / f"{title}.pdf",
            downloads_dir / f"{safe}.pdf",
        ):
            if candidate.exists():
                pdf_path = candidate
                break

        if not pdf_path:
            logger.debug("No PDF found for '%s' — skipping", title)
            continue

        book_dir = books_dir / safe
        existing = (
            sorted(book_dir.glob("Chapter_*.pdf"))
            + sorted(book_dir.glob("Part_*.pdf"))
        )
        if existing:
            logger.info("Already split: %s (%d chunks) — skipping", title, len(existing))
            skip_count += 1
            continue

        try:
            chunks = split_pdf(pdf_path, title)
            logger.info("Split: %s → %d chunks", title, len(chunks))
            split_count += 1
        except Exception as exc:
            logger.error("Failed to split '%s': %s", title, exc)

    logger.info("Phase 1 done. Split: %d, Skipped (already done): %d", split_count, skip_count)


# ---------------------------------------------------------------------------
# Phase 2: Remove junk chapters from all book directories
# ---------------------------------------------------------------------------

def clean_junk_chapters(books_dir: Path) -> None:
    logger.info("=== Phase 2: Cleaning junk chapters ===")
    removed = 0
    kept = 0

    for book_dir in sorted(books_dir.iterdir()):
        if not book_dir.is_dir():
            continue

        chapters = sorted(book_dir.glob("Chapter_*.pdf")) + sorted(book_dir.glob("Part_*.pdf"))
        for chapter in chapters:
            if _is_junk(chapter):
                logger.info("  REMOVE  %s / %s", book_dir.name, chapter.name)
                chapter.unlink()
                removed += 1
            else:
                kept += 1

    logger.info("Phase 2 done. Removed: %d junk files, Kept: %d chapter files", removed, kept)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Split remaining PDFs and clean junk chapters")
    parser.add_argument(
        "--books-dir",
        type=Path,
        default=PACKT_BOOKS_DIR,
        help="Root directory for split books (default: packt-books)",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=DEFAULT_DOWNLOADS_DIR,
        help="Directory containing downloaded Packt PDFs",
    )
    parser.add_argument(
        "--skip-split",
        action="store_true",
        help="Skip splitting — only run the cleanup phase",
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="Skip cleanup — only run the split phase",
    )
    args = parser.parse_args()

    if not args.skip_split:
        split_remaining(args.downloads_dir, args.books_dir)

    if not args.skip_clean:
        clean_junk_chapters(args.books_dir)

    logger.info("All done.")


if __name__ == "__main__":
    main()
