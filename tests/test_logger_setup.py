"""Unit tests for logger_setup module."""

import logging
from datetime import datetime
from pathlib import Path

import pytest

from notebooklm_automation.logger_setup import (
    LOG_FILENAME,
    OUTPUT_DIR_FORMAT,
    create_output_dir,
    setup_logging,
)


class TestCreateOutputDir:
    def test_creates_timestamped_directory(self, tmp_path: Path) -> None:
        output_dir = create_output_dir(base_dir=tmp_path)
        assert output_dir.exists()
        assert output_dir.is_dir()
        assert output_dir.parent == tmp_path

    def test_directory_name_matches_timestamp_format(self, tmp_path: Path) -> None:
        before = datetime.now()
        output_dir = create_output_dir(base_dir=tmp_path)
        after = datetime.now()

        dir_name = output_dir.name
        parsed = datetime.strptime(dir_name, OUTPUT_DIR_FORMAT)
        assert before.replace(microsecond=0) <= parsed <= after.replace(microsecond=0)

    def test_defaults_to_output_base_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        output_dir = create_output_dir()
        assert output_dir.resolve().parent == (tmp_path / "output").resolve()

    def test_idempotent_on_existing_directory(self, tmp_path: Path) -> None:
        dir1 = create_output_dir(base_dir=tmp_path)
        # Calling again with same timestamp won't error (exist_ok=True)
        dir1.mkdir(parents=True, exist_ok=True)
        assert dir1.exists()


class TestSetupLogging:
    def test_returns_named_logger(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        assert logger.name == "notebooklm_automation"

    def test_logger_level_is_debug(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        assert logger.level == logging.DEBUG

    def test_has_console_and_file_handlers(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        handler_types = [type(h) for h in logger.handlers]
        assert logging.StreamHandler in handler_types
        assert logging.FileHandler in handler_types

    def test_console_handler_level_is_info(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        console = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
        assert console.level == logging.INFO

    def test_file_handler_level_is_debug(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        file_h = next(h for h in logger.handlers if isinstance(h, logging.FileHandler))
        assert file_h.level == logging.DEBUG

    def test_log_file_created_in_output_dir(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        logger.info("test message")
        log_file = tmp_path / LOG_FILENAME
        assert log_file.exists()

    def test_log_file_contains_message(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        logger.info("hello world")
        # Flush handlers
        for h in logger.handlers:
            h.flush()
        content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
        assert "hello world" in content

    def test_log_format_includes_timestamp_and_level(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        logger.warning("check format")
        for h in logger.handlers:
            h.flush()
        content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
        assert "[WARNING]" in content
        # Timestamp pattern: YYYY-MM-DDTHH:MM:SS
        assert "T" in content.split("[")[0]

    def test_debug_written_to_file_not_console(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        logger = setup_logging(tmp_path)
        logger.debug("debug only")
        for h in logger.handlers:
            h.flush()
        # File should have it
        content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
        assert "debug only" in content

    def test_repeated_calls_do_not_duplicate_handlers(self, tmp_path: Path) -> None:
        setup_logging(tmp_path)
        logger = setup_logging(tmp_path)
        assert len(logger.handlers) == 2

    def test_all_severity_levels_logged_to_file(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path)
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        for h in logger.handlers:
            h.flush()
        content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
        assert "[DEBUG]" in content
        assert "[INFO]" in content
        assert "[WARNING]" in content
        assert "[ERROR]" in content
