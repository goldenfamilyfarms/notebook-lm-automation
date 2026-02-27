"""Audio format detection, filename sanitization, and MP3 conversion via FFmpeg."""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

RECOGNIZED_FORMATS: set[str] = {"wav", "webm", "ogg", "mp3", "m4a"}


class ConversionError(Exception):
    """Raised when audio conversion fails or FFmpeg is unavailable."""


def detect_audio_format(file_path: Path) -> str:
    """Detect audio format from file extension.

    Args:
        file_path: Path to the audio file.

    Returns:
        Lowercase format string (e.g. "wav", "mp3").

    Raises:
        ValueError: If the extension is missing or not recognized.
    """
    ext = file_path.suffix.lstrip(".").lower()
    if not ext:
        raise ValueError(f"No file extension found: {file_path}")
    if ext not in RECOGNIZED_FORMATS:
        raise ValueError(f"Unrecognized audio format '{ext}': {file_path}")
    return ext


def sanitize_filename(title: str) -> str:
    """Convert a notebook title to a filesystem-safe name.

    - Strips leading/trailing whitespace
    - Replaces spaces and runs of non-alphanumeric/non-hyphen/non-underscore chars with underscores
    - Collapses consecutive underscores
    - Strips leading/trailing underscores
    - Falls back to 'untitled' if result is empty

    Args:
        title: Raw notebook title string.

    Returns:
        Filesystem-safe string suitable for use as a filename (without extension).
    """
    name = title.strip()
    # Replace any character that isn't alphanumeric, hyphen, or underscore
    name = re.sub(r"[^\w\-]", "_", name, flags=re.UNICODE)
    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    return name if name else "untitled"


def convert_to_mp3(input_path: Path, output_dir: Path) -> Path:
    """Convert an audio file to MP3 using FFmpeg.

    The output filename is derived from the input filename stem.

    Args:
        input_path: Path to the source audio file.
        output_dir: Directory where the MP3 file will be saved.

    Returns:
        Path to the converted MP3 file.

    Raises:
        ConversionError: If FFmpeg is not installed or conversion fails.
    """
    output_path = output_dir / f"{input_path.stem}.mp3"

    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-y",              # overwrite without asking
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",  # high quality VBR
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise ConversionError(
            "FFmpeg is not installed or not found on PATH"
        )
    except subprocess.TimeoutExpired:
        raise ConversionError(
            f"FFmpeg timed out converting {input_path}"
        )

    if result.returncode != 0:
        raise ConversionError(
            f"FFmpeg failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    logger.info("Converted %s -> %s", input_path.name, output_path.name)
    return output_path
