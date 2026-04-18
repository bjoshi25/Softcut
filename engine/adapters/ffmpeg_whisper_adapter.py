"""FFmpeg whisper-filter adapter for ASR."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engine.schemas.timeline import (
    AdapterState,
    AdapterStatus,
    SpeechSegment,
    WordSegment,
)


def _parse_time_like(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return 0.0
    if ":" not in text:
        try:
            return max(0.0, float(text))
        except ValueError:
            return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hh = float(parts[0])
            mm = float(parts[1])
            ss = float(parts[2])
            return max(0.0, hh * 3600.0 + mm * 60.0 + ss)
    except ValueError:
        return 0.0
    return 0.0


def _filter_available() -> bool:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        return False
    listing = f"{proc.stdout}\n{proc.stderr}".lower()
    return " whisper " in listing or listing.endswith(" whisper")


def _build_segments(payload: Any) -> tuple[list[SpeechSegment], list[WordSegment]]:
    if isinstance(payload, dict):
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list):
            raw_segments = payload.get("transcription")
            if not isinstance(raw_segments, list):
                raw_segments = []
    elif isinstance(payload, list):
        raw_segments = payload
    else:
        raw_segments = []

    speech_segments: list[SpeechSegment] = []
    word_segments: list[WordSegment] = []
    for seg_index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        seg_id = f"speech_{seg_index:04d}"
        start_sec = _parse_time_like(item.get("start", item.get("t0")))
        end_sec = _parse_time_like(item.get("end", item.get("t1")))
        if end_sec < start_sec:
            end_sec = start_sec
        text = str(item.get("text", item.get("sentence", ""))).strip()
        if not text:
            continue
        speech_segments.append(
            SpeechSegment(
                segment_id=seg_id,
                start_sec=start_sec,
                end_sec=end_sec,
                text=text,
                confidence=None,
                speaker=None,
            )
        )

        words = item.get("words")
        if not isinstance(words, list):
            words = item.get("tokens")
            if not isinstance(words, list):
                words = []
        for word_index, word_item in enumerate(words):
            if not isinstance(word_item, dict):
                continue
            token = str(word_item.get("word", word_item.get("text", ""))).strip()
            if not token:
                continue
            word_start = _parse_time_like(word_item.get("start", word_item.get("t0")))
            word_end = _parse_time_like(word_item.get("end", word_item.get("t1")))
            if word_end < word_start:
                word_end = word_start
            word_segments.append(
                WordSegment(
                    word_id=f"{seg_id}_word_{word_index:03d}",
                    start_sec=word_start,
                    end_sec=word_end,
                    word=token,
                    confidence=None,
                    speaker=None,
                )
            )
    return speech_segments, word_segments


def transcribe(
    video_path: str | Path,
    *,
    model_path: str | None,
    language: str | None = None,
    queue: int = 10,
    use_gpu: bool = True,
) -> tuple[list[SpeechSegment], list[WordSegment], AdapterStatus]:
    """Run FFmpeg whisper filter when available/configured."""
    config: dict[str, Any] = {
        "model_path": model_path,
        "language": language,
        "queue": queue,
        "use_gpu": use_gpu,
        "format": "json",
    }
    if not _filter_available():
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="ffmpeg whisper filter unavailable in local ffmpeg build.",
            config=config,
        )
    if not model_path:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="ffmpeg whisper filter available but no model_path configured.",
            config=config,
        )
    model_file = Path(model_path)
    if not model_file.exists():
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"ffmpeg whisper model not found: {model_path}",
            config=config,
        )

    with tempfile.NamedTemporaryFile(
        suffix=".json",
        prefix="softcut_whisper_",
        delete=False,
    ) as temp_file:
        output_path = Path(temp_file.name)

    whisper_parts = [f"model={model_file}"]
    if language:
        whisper_parts.append(f"language={language}")
    whisper_parts.append(f"queue={max(1, int(queue))}")
    whisper_parts.append(f"use_gpu={'true' if use_gpu else 'false'}")
    whisper_parts.append("format=json")
    whisper_parts.append(f"destination={output_path}")
    whisper_filter = ":".join(whisper_parts)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(video_path),
        "-vn",
        "-af",
        whisper_filter,
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "ffmpeg whisper execution failed."
        output_path.unlink(missing_ok=True)
        return [], [], AdapterStatus(
            state=AdapterState.failed,
            detail=detail,
            config=config,
        )

    if not output_path.exists():
        return [], [], AdapterStatus(
            state=AdapterState.failed,
            detail="ffmpeg whisper completed but produced no JSON output.",
            config=config,
        )

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        return [], [], AdapterStatus(
            state=AdapterState.failed,
            detail=f"failed parsing ffmpeg whisper JSON: {exc}",
            config=config,
        )
    finally:
        output_path.unlink(missing_ok=True)

    speech_segments, word_segments = _build_segments(payload)
    return speech_segments, word_segments, AdapterStatus(
        state=AdapterState.available,
        detail=(
            "Speech generated by ffmpeg whisper filter."
            if speech_segments
            else "ffmpeg whisper returned no segments."
        ),
        config=config,
    )
