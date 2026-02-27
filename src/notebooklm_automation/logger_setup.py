"""Logging configuration and output directory management."""

import logging
from datetime import datetime
from pathlib import Path

LOG_FILENAME = "run.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
OUTPUT_DIR_FORMAT = "%Y-%m-%dT%H-%M-%S"


def create_output_dir(base_dir: Path | None = None) -> Path:
    """Create a timestamped output directory for the current run.

    Args:
        base_dir: Parent directory for output. Defaults to ``./output``.

    Returns:
        Path to the created timestamped directory.
    """
    if base_dir is None:
        base_dir = Path("output")

    timestamp = datetime.now().strftime(OUTPUT_DIR_FORMAT)
    output_dir = base_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def setup_logging(output_dir: Path) -> logging.Logger:
    """Configure logging to both console (INFO+) and file (DEBUG+).

    The log file ``run.log`` is placed inside *output_dir*.

    Args:
        output_dir: Directory where the log file will be written.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("notebooklm_automation")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls
    logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler — INFO and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler — DEBUG and above
    log_path = output_dir / LOG_FILENAME
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
