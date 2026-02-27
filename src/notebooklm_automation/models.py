"""Data models for NotebookLM automation."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Notebook:
    title: str
    creation_date: date
    element_locator: str


@dataclass
class ReportResult:
    notebook_title: str
    report_type: str
    success: bool
    error: str | None = None


@dataclass
class AudioResult:
    notebook_title: str
    file_path: Path | None
    success: bool
    error: str | None = None


@dataclass
class ExportResult:
    item_name: str
    success: bool
    error: str | None = None


@dataclass
class RunSummary:
    notebooks_processed: int = 0
    notebooks_from_pdfs: int = 0
    reports_generated: int = 0
    reports_failed: int = 0
    exports_completed: int = 0
    exports_failed: int = 0
    audio_generated: int = 0
    audio_converted: int = 0
    errors: list[str] = field(default_factory=list)
