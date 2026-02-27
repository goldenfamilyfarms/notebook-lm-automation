"""Unit tests for converter.py — format detection, filename sanitization, and MP3 conversion."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from notebooklm_automation.converter import (
    ConversionError,
    detect_audio_format,
    sanitize_filename,
    convert_to_mp3,
)


# ---------------------------------------------------------------------------
# detect_audio_format
# ---------------------------------------------------------------------------

class TestDetectAudioFormat:
    """Tests for detect_audio_format — Validates: Requirement 6.1."""

    @pytest.mark.parametrize("ext", ["wav", "webm", "ogg", "mp3", "m4a"])
    def test_recognized_extensions(self, ext: str) -> None:
        assert detect_audio_format(Path(f"audio.{ext}")) == ext

    @pytest.mark.parametrize("ext", ["WAV", "MP3", "Ogg", "WEBM", "M4A"])
    def test_case_insensitive(self, ext: str) -> None:
        assert detect_audio_format(Path(f"audio.{ext}")) == ext.lower()

    def test_unrecognized_extension_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized audio format"):
            detect_audio_format(Path("audio.flac"))

    def test_no_extension_raises(self) -> None:
        with pytest.raises(ValueError, match="No file extension"):
            detect_audio_format(Path("audio"))

    def test_nested_path(self) -> None:
        assert detect_audio_format(Path("/some/dir/file.wav")) == "wav"


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    """Tests for sanitize_filename — Validates: Requirement 6.3."""

    def test_simple_title(self) -> None:
        assert sanitize_filename("My Notebook") == "My_Notebook"

    def test_special_characters(self) -> None:
        assert sanitize_filename("Report: Q2/Q3 (Draft)") == "Report_Q2_Q3_Draft"

    def test_unicode_preserved(self) -> None:
        result = sanitize_filename("Café résumé")
        assert "Caf" in result
        assert "r" in result

    def test_consecutive_spaces_collapsed(self) -> None:
        assert sanitize_filename("a   b") == "a_b"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert sanitize_filename("  hello  ") == "hello"

    def test_empty_string_returns_untitled(self) -> None:
        assert sanitize_filename("") == "untitled"

    def test_only_special_chars_returns_untitled(self) -> None:
        assert sanitize_filename("!!!") == "untitled"

    def test_hyphens_preserved(self) -> None:
        assert sanitize_filename("my-notebook") == "my-notebook"

    def test_underscores_preserved(self) -> None:
        assert sanitize_filename("my_notebook") == "my_notebook"


# ---------------------------------------------------------------------------
# convert_to_mp3
# ---------------------------------------------------------------------------

class TestConvertToMp3:
    """Tests for convert_to_mp3 — Validates: Requirements 6.2, 6.3, 6.4."""

    def test_successful_conversion(self, tmp_path: Path) -> None:
        input_file = tmp_path / "audio_overview.wav"
        input_file.touch()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("notebooklm_automation.converter.subprocess.run", return_value=mock_result) as mock_run:
            result = convert_to_mp3(input_file, output_dir)

        assert result == output_dir / "audio_overview.mp3"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-i" in cmd
        assert str(input_file) in cmd

    def test_ffmpeg_not_installed_raises(self, tmp_path: Path) -> None:
        input_file = tmp_path / "audio.wav"
        input_file.touch()

        with patch(
            "notebooklm_automation.converter.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(ConversionError, match="not installed"):
                convert_to_mp3(input_file, tmp_path)

    def test_ffmpeg_nonzero_exit_raises(self, tmp_path: Path) -> None:
        input_file = tmp_path / "audio.ogg"
        input_file.touch()

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="codec error"
        )
        with patch("notebooklm_automation.converter.subprocess.run", return_value=mock_result):
            with pytest.raises(ConversionError, match="FFmpeg failed"):
                convert_to_mp3(input_file, tmp_path)

    def test_ffmpeg_timeout_raises(self, tmp_path: Path) -> None:
        input_file = tmp_path / "audio.webm"
        input_file.touch()

        with patch(
            "notebooklm_automation.converter.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120),
        ):
            with pytest.raises(ConversionError, match="timed out"):
                convert_to_mp3(input_file, tmp_path)
