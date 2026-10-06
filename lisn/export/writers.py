"""Write a RenderedDocument to .wav (soundfile), .mp3 or .m4b (ffmpeg, with chapters)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf

from lisn.errors import LisnError
from lisn.export.render import RenderedDocument

FORMATS = {".wav", ".mp3", ".m4b", ".m4a"}
INSTALL_HINT = (
    "Install ffmpeg: macOS `brew install ffmpeg`, Debian/Ubuntu `sudo apt install ffmpeg`, "
    "Windows `winget install Gyan.FFmpeg`."
)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def export_document(rendered: RenderedDocument, out: Path, title: str = "", bitrate: str = "96k") -> Path:
    suffix = out.suffix.lower()
    if suffix not in FORMATS:
        raise LisnError(f"Unsupported export format '{suffix}'. Use .wav, .mp3 or .m4b.")
    out.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".wav":
        sf.write(str(out), rendered.samples, rendered.sample_rate)
        return out
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise LisnError(f"ffmpeg is required for {suffix} export. {INSTALL_HINT}")
    with tempfile.TemporaryDirectory(prefix="lisn-export-") as tmp:
        wav = Path(tmp) / "audio.wav"
        sf.write(str(wav), rendered.samples, rendered.sample_rate)
        metadata = Path(tmp) / "chapters.txt"
        metadata.write_text(ffmetadata(rendered, title), encoding="utf-8")
        command = _ffmpeg_command(ffmpeg, wav, metadata, out, suffix, bitrate)
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=3600)
        except subprocess.CalledProcessError as exc:
            raise LisnError(f"ffmpeg failed: {exc.stderr.strip().splitlines()[-1] if exc.stderr else exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LisnError("ffmpeg timed out.") from exc
    return out


def ffmetadata(rendered: RenderedDocument, title: str) -> str:
    """ffmpeg's FFMETADATA1 format with one [CHAPTER] per ChapterMark (milliseconds)."""
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_escape(title)}")
    lines.append("encoder=lisn")
    for chapter in rendered.chapters:
        lines.extend(
            [
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={int(chapter.start * 1000)}",
                f"END={int(chapter.end * 1000)}",
                f"title={_escape(chapter.title)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")


def _ffmpeg_command(ffmpeg: str, wav: Path, metadata: Path, out: Path, suffix: str, bitrate: str) -> list[str]:
    base = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(wav),
        "-i",
        str(metadata),
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
    ]
    if suffix == ".mp3":
        return [*base, "-codec:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3", str(out)]
    return [*base, "-codec:a", "aac", "-b:a", bitrate, "-movflags", "+faststart", "-f", "mp4", str(out)]
