"""OpenAI Whisper OSS adapter (fallback ASR)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.schemas.timeline import AdapterState, AdapterStatus, SpeechSegment, WordSegment


def _confidence_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= numeric <= 1.0:
        return numeric
    return None


def transcribe(
    video_path: str | Path,
    *,
    model_name: str = "base",
    language: str | None = None,
) -> tuple[list[SpeechSegment], list[WordSegment], AdapterStatus]:
    config = {"model_name": model_name, "language": language}
    try:
        import whisper
    except ModuleNotFoundError:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="openai-whisper not installed.",
            config=config,
        )
    except Exception as exc:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"openai-whisper import failed: {exc}",
            config=config,
        )

    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(
            str(video_path),
            language=language,
            word_timestamps=True,
            fp16=False,
            task="transcribe",
        )
        raw_segments = result.get("segments", []) or []
        speech_segments: list[SpeechSegment] = []
        word_segments: list[WordSegment] = []
        for idx, segment in enumerate(raw_segments):
            seg_id = f"speech_{idx:04d}"
            start_sec = max(0.0, float(segment.get("start", 0.0)))
            end_sec = max(start_sec, float(segment.get("end", start_sec)))
            text = str(segment.get("text", "")).strip()
            speech_segments.append(
                SpeechSegment(
                    segment_id=seg_id,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    text=text,
                    confidence=_confidence_or_none(segment.get("avg_logprob")),
                    speaker=None,
                )
            )
            words = segment.get("words", []) or []
            for widx, word in enumerate(words):
                token = str(word.get("word", "")).strip()
                if not token:
                    continue
                wstart = max(0.0, float(word.get("start", start_sec)))
                wend = max(wstart, float(word.get("end", wstart)))
                word_segments.append(
                    WordSegment(
                        word_id=f"{seg_id}_word_{widx:03d}",
                        start_sec=wstart,
                        end_sec=wend,
                        word=token,
                        confidence=_confidence_or_none(word.get("probability")),
                        speaker=None,
                    )
                )
        return speech_segments, word_segments, AdapterStatus(
            state=AdapterState.available,
            detail=f"openai-whisper produced {len(speech_segments)} speech segments.",
            config=config,
        )
    except Exception as exc:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"openai-whisper runtime failed: {exc}",
            config=config,
        )
