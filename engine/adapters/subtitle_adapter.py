"""Optional subtitle bootstrap adapter (supplemental evidence only)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from engine.schemas.timeline import AdapterState, AdapterStatus, SpeechSegment


def _parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return 0.0
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2].replace(",", "."))
    return max(0.0, hours * 3600.0 + minutes * 60.0 + seconds)


def _parse_vtt_segments(vtt_text: str) -> list[SpeechSegment]:
    segments: list[SpeechSegment] = []
    lines = [line.rstrip("\n") for line in vtt_text.splitlines()]
    idx = 0
    current_start = 0.0
    current_end = 0.0
    current_text: list[str] = []
    segment_index = 0

    time_re = re.compile(
        r"([0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3})\s*-->\s*([0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3})"
    )
    while idx < len(lines):
        line = lines[idx].strip()
        match = time_re.search(line)
        if match:
            current_start = _parse_timestamp(match.group(1))
            current_end = _parse_timestamp(match.group(2))
            current_text = []
            idx += 1
            while idx < len(lines) and lines[idx].strip():
                cleaned = re.sub(r"<[^>]+>", "", lines[idx]).strip()
                if cleaned:
                    current_text.append(cleaned)
                idx += 1
            text = " ".join(current_text).strip()
            if text:
                segments.append(
                    SpeechSegment(
                        segment_id=f"subtitle_{segment_index:04d}",
                        start_sec=current_start,
                        end_sec=max(current_start, current_end),
                        text=text,
                        confidence=0.55,
                        speaker=None,
                    )
                )
                segment_index += 1
        idx += 1
    return segments


def fetch_subtitle_segments(
    *,
    source_url: str | None,
    output_dir: str | Path,
    job_id: str,
    language: str = "en",
) -> tuple[list[SpeechSegment], AdapterStatus]:
    """Download subtitles for URL source and parse to speech segments."""
    config = {
        "language": language,
        "mode": "yt-dlp-subtitle-bootstrap",
    }
    if not source_url:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="source URL unavailable for subtitle bootstrap.",
            config=config,
        )

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = outdir / f"{job_id}_subtitle"
    outtmpl = str(stem) + ".%(ext)s"
    command = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang",
        language,
        "--sub-format",
        "vtt",
        "-o",
        outtmpl,
        source_url,
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "subtitle download failed"
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=detail,
            config=config,
        )

    candidates = sorted(outdir.glob(f"{job_id}_subtitle*.vtt"))
    if not candidates:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="no subtitle vtt file produced.",
            config=config,
        )

    text = candidates[0].read_text(encoding="utf-8", errors="ignore")
    segments = _parse_vtt_segments(text)
    if not segments:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="subtitle file parsed but yielded no segments.",
            config=config,
        )
    return segments, AdapterStatus(
        state=AdapterState.available,
        detail=f"loaded {len(segments)} subtitle segments (supplemental).",
        config=config,
    )
