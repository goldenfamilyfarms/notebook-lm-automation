# Global CLI Commands

## Playwright Browser Install

- **Command:** `python -m playwright install chromium`
- **Context:** LOCAL
- **Purpose:** Download the Chromium browser binary required by Playwright for browser automation
- **Flags:** `chromium` — installs only Chromium (not Firefox/WebKit), keeping download size minimal
- **Preconditions:** `playwright` Python package installed (`python -m pip install playwright`)
- **Expected result:** Chromium binary downloaded to `%LOCALAPPDATA%\ms-playwright\chromium-<version>\`

## Run NotebookLM Automation

- **Command:** `python -m notebooklm_automation.main`
- **Context:** LOCAL
- **Purpose:** Execute the full NotebookLM automation workflow (auth → discover → reports → audio → export)
- **Flags:**
  - `--user-data-dir <path>` — (optional) Chromium persistent profile directory. Default: `~/.notebooklm-automation/chrome-profile`
  - `--output-dir <path>` — (optional) Output directory for logs and audio files. Default: timestamped dir under `./output`
- **Preconditions:** `python -m pip install -e ".[dev]"` and `python -m playwright install chromium` completed
- **Expected result:** Browser opens, processes today's notebooks, prints RunSummary to console

## Install Project (Editable + Dev Dependencies)

- **Command:** `python -m pip install -e ".[dev]"`
- **Context:** LOCAL
- **Purpose:** Install the notebooklm-automation package in editable mode with dev dependencies (pytest, hypothesis)
- **Flags:** `-e` — editable/development install; `.[dev]` — include optional dev dependencies
- **Preconditions:** Python 3.11+, in project root directory
- **Expected result:** Package importable as `notebooklm_automation`, pytest and hypothesis available

## Run Tests

- **Command:** `python -m pytest tests/ -v`
- **Context:** LOCAL
- **Purpose:** Run the full test suite
- **Flags:** `-v` — verbose output showing individual test names and results
- **Preconditions:** `python -m pip install -e ".[dev]"` completed
- **Expected result:** All tests pass (85 currently)

## Run Packt Pipeline (Full — Claim + Split + NotebookLM)

- **Command:** `python -m notebooklm_automation.packt_pipeline`
- **Context:** LOCAL
- **Purpose:** Full Packt pipeline: claim/download books → split into chapters → create one NotebookLM notebook per chapter → run full workflow (reports, audio, export, MP3)
- **Flags:**
  - `--skip-claim` — skip Packt claim/download, use already-downloaded PDFs
  - `--skip-split` — skip PDF splitting, use already-split chapter PDFs
  - `--downloads-dir <path>` — directory containing downloaded Packt PDFs (default: `~/Downloads`)
  - `--output-dir <path>` — output directory for logs and audio (default: timestamped under `./output`)
- **Preconditions:** `python -m pip install -e ".[dev]"`, `python -m playwright install chromium`, FFmpeg installed
- **Expected result:** All Packt chapter PDFs uploaded to NotebookLM as individual notebooks, full workflow run per chapter

## Run Packt Pipeline (From Existing — Skip Claim + Split)

- **Command:** `python -m notebooklm_automation.packt_pipeline --from-existing`
- **Context:** LOCAL
- **Purpose:** Read pre-split chapter PDFs directly from `packt-books/` and create one NotebookLM notebook per chapter PDF. Skips claim and split phases entirely. Each subdirectory under `packt-books/` is treated as one book; each `Chapter_*.pdf` / `Part_*.pdf` within it becomes its own notebook.
- **Flags:**
  - `--from-existing` — read from `--books-dir` directly, skip claim + split
  - `--books-dir <path>` — root directory of pre-split books (default: `packt-books`)
  - `--user-data-dir <path>` — Chromium persistent profile (default: `~/.notebooklm-automation/chrome-profile`)
  - `--output-dir <path>` — output directory for logs and audio (default: timestamped under `./output`)
- **Preconditions:** `packt-books/` populated with subdirectories containing `Chapter_*.pdf` files, `python -m playwright install chromium`, FFmpeg installed
- **Expected result:** One NotebookLM notebook created per chapter PDF across all 60 books, full workflow (reports, audio, export, MP3) run per notebook
