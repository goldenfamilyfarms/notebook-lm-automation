"""PDF splitting utilities.

Splits a PDF into chapter/section chunks using bookmark outlines.
Falls back to 50-page chunks if no outline is present.

Output structure:
    packt-books/
    └── <book_title>/
        ├── <book_title>.pdf          # original renamed
        ├── Chapter_01_<name>.pdf
        ├── Chapter_02_<name>.pdf
        └── ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

PACKT_BOOKS_DIR = Path("packt-books")
FALLBACK_CHUNK_PAGES = 50


def sanitize_filename(name: str) -> str:
    """Convert a string to a filesystem-safe filename (no extension)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"_+", "_", name).strip("_. ")
    return name[:120] or "untitled"


def _extract_outline_chapters(reader: PdfReader) -> list[tuple[str, int]]:
    """Return list of (title, zero-based start page) from PDF outline/bookmarks.

    Only top-level entries that look like chapters/sections are returned.
    Returns empty list if no usable outline exists.
    """
    try:
        outline = reader.outline
    except Exception:
        return []

    if not outline:
        return []

    chapters: list[tuple[str, int]] = []
    for item in outline:
        # Skip nested lists (sub-sections at this pass)
        if isinstance(item, list):
            continue
        try:
            page_num = reader.get_destination_page_number(item)
            title = str(item.title).strip()
            if title and page_num is not None:
                chapters.append((title, page_num))
        except Exception:
            continue

    # Deduplicate consecutive entries on the same page
    seen_pages: set[int] = set()
    unique: list[tuple[str, int]] = []
    for title, page in chapters:
        if page not in seen_pages:
            seen_pages.add(page)
            unique.append((title, page))

    return unique


def _write_chunk(
    reader: PdfReader,
    start: int,
    end: int,
    out_path: Path,
) -> None:
    """Write pages [start, end) from reader to out_path.

    pypdf's _resolve_links crashes on some Packt PDFs with malformed named
    destinations. Patch it to a no-op before writing to avoid the crash.
    """
    writer = PdfWriter()
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    # Disable link resolution — avoids pypdf crash on malformed named destinations
    writer._resolve_links = lambda: None  # type: ignore[method-assign]
    with out_path.open("wb") as f:
        writer.write(f)


def split_pdf(pdf_path: Path, book_title: str) -> list[Path]:
    """Split pdf_path into chapter PDFs stored under packt-books/<book_title>/.

    Strategy (in order):
      1. Use PDF outline/bookmarks to identify chapter boundaries
      2. Fall back to FALLBACK_CHUNK_PAGES-page chunks

    Returns list of output chapter PDF paths.
    """
    book_dir = PACKT_BOOKS_DIR / sanitize_filename(book_title)
    book_dir.mkdir(parents=True, exist_ok=True)

    # Copy/rename original into the book directory
    dest_original = book_dir / f"{sanitize_filename(book_title)}.pdf"
    if not dest_original.exists():
        import shutil
        shutil.copy2(pdf_path, dest_original)
        logger.info("Copied original PDF → %s", dest_original)

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    logger.info("Splitting '%s' (%d pages)", book_title, total_pages)

    chapters = _extract_outline_chapters(reader)
    output_paths: list[Path] = []

    if chapters:
        logger.info("Using outline: %d chapter entries found", len(chapters))
        for idx, (title, start) in enumerate(chapters):
            end = chapters[idx + 1][1] if idx + 1 < len(chapters) else total_pages
            if end <= start:
                continue
            safe_title = sanitize_filename(title)
            out_name = f"Chapter_{idx + 1:02d}_{safe_title}.pdf"
            out_path = book_dir / out_name
            _write_chunk(reader, start, end, out_path)
            logger.info("  Written: %s (%d pages)", out_name, end - start)
            output_paths.append(out_path)
    else:
        logger.info("No outline found — splitting into %d-page chunks", FALLBACK_CHUNK_PAGES)
        chunk_num = 1
        for start in range(0, total_pages, FALLBACK_CHUNK_PAGES):
            end = min(start + FALLBACK_CHUNK_PAGES, total_pages)
            out_name = f"Part_{chunk_num:02d}_pages_{start + 1}-{end}.pdf"
            out_path = book_dir / out_name
            _write_chunk(reader, start, end, out_path)
            logger.info("  Written: %s", out_name)
            output_paths.append(out_path)
            chunk_num += 1

    logger.info("Split complete: %d chunks for '%s'", len(output_paths), book_title)
    return output_paths
