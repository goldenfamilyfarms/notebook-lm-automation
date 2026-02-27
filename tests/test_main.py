"""Unit tests for main.py — format_summary and safe_execute."""

import asyncio
import logging

import pytest

from notebooklm_automation.main import format_summary, safe_execute
from notebooklm_automation.models import RunSummary


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------

class TestFormatSummary:
    """Tests for format_summary — Validates: Requirement 8.4."""

    def test_zero_counts(self) -> None:
        summary = RunSummary()
        result = format_summary(summary)
        assert "Notebooks processed : 0" in result
        assert "Reports generated   : 0" in result
        assert "Reports failed      : 0" in result
        assert "Exports completed   : 0" in result
        assert "Exports failed      : 0" in result
        assert "Audio generated     : 0" in result
        assert "Audio converted     : 0" in result
        assert "Errors              : 0" in result

    def test_nonzero_counts(self) -> None:
        summary = RunSummary(
            notebooks_processed=3,
            reports_generated=9,
            reports_failed=1,
            exports_completed=8,
            exports_failed=2,
            audio_generated=3,
            audio_converted=2,
        )
        result = format_summary(summary)
        assert "Notebooks processed : 3" in result
        assert "Reports generated   : 9" in result
        assert "Reports failed      : 1" in result
        assert "Exports completed   : 8" in result
        assert "Exports failed      : 2" in result
        assert "Audio generated     : 3" in result
        assert "Audio converted     : 2" in result

    def test_errors_listed(self) -> None:
        summary = RunSummary(errors=["Auth failed", "Export timeout"])
        result = format_summary(summary)
        assert "Errors (2):" in result
        assert "- Auth failed" in result
        assert "- Export timeout" in result

    def test_no_errors_shows_zero(self) -> None:
        summary = RunSummary()
        result = format_summary(summary)
        assert "Errors              : 0" in result
        assert "Errors (" not in result

    def test_contains_header(self) -> None:
        result = format_summary(RunSummary())
        assert "Run Summary" in result


# ---------------------------------------------------------------------------
# safe_execute
# ---------------------------------------------------------------------------

class TestSafeExecute:
    """Tests for safe_execute — generic async error wrapper."""

    @pytest.fixture()
    def log(self) -> logging.Logger:
        return logging.getLogger("test_safe_execute")

    def test_success_returns_result(self, log: logging.Logger) -> None:
        async def _ok():
            return 42

        ok, result = asyncio.run(safe_execute(_ok(), "test op", log))
        assert ok is True
        assert result == 42

    def test_timeout_returns_false(self, log: logging.Logger) -> None:
        async def _timeout():
            raise TimeoutError("timed out")

        ok, result = asyncio.run(safe_execute(_timeout(), "test op", log))
        assert ok is False
        assert result is None

    def test_generic_exception_returns_false(self, log: logging.Logger) -> None:
        async def _fail():
            raise RuntimeError("boom")

        ok, result = asyncio.run(safe_execute(_fail(), "test op", log))
        assert ok is False
        assert result is None

    def test_success_logs_info(self, log: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
        async def _ok():
            return "done"

        with caplog.at_level(logging.INFO, logger="test_safe_execute"):
            asyncio.run(safe_execute(_ok(), "my operation", log))

        assert any("Success: my operation" in r.message for r in caplog.records)

    def test_timeout_logs_error(self, log: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
        async def _timeout():
            raise TimeoutError

        with caplog.at_level(logging.ERROR, logger="test_safe_execute"):
            asyncio.run(safe_execute(_timeout(), "slow op", log))

        assert any("Timeout: slow op" in r.message for r in caplog.records)

    def test_exception_logs_error_with_message(self, log: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
        async def _fail():
            raise ValueError("bad value")

        with caplog.at_level(logging.ERROR, logger="test_safe_execute"):
            asyncio.run(safe_execute(_fail(), "parse op", log))

        assert any("Failed: parse op" in r.message and "bad value" in r.message for r in caplog.records)

    def test_none_result_on_success(self, log: logging.Logger) -> None:
        async def _none():
            return None

        ok, result = asyncio.run(safe_execute(_none(), "null op", log))
        assert ok is True
        assert result is None
