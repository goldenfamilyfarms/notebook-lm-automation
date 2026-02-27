"""Configuration constants for NotebookLM automation."""

from pathlib import Path

NOTEBOOKLM_URL = "https://notebooklm.google.com/"
DEFAULT_USER_DATA_DIR = Path.home() / ".notebooklm-automation" / "chrome-profile"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
PDF_MAX_AGE_HOURS = 24

PAGE_LOAD_TIMEOUT_S = 600
REPORT_GENERATION_TIMEOUT_S = 300  # seconds
AUDIO_GENERATION_TIMEOUT_S = 1800  # seconds
AUDIO_POLL_INTERVAL_S = 15

# Report formats to generate via the "Create report" modal.
# These must match the text visible on the format cards in the modal exactly.
# Standard formats (always present): Briefing Doc, Study Guide, Blog Post
# AI-suggested formats (load after ~60s): vary per notebook content
# We use the standard ones which are always available.
STANDARD_REPORT_FORMATS: list[str] = ["Briefing Doc", "Study Guide"]

# Formats to skip
EXCLUDED_REPORT_FORMATS: set[str] = {"Blog Post", "Create Your Own"}
