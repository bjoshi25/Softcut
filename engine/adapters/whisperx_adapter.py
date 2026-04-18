"""WhisperX adapter for ASR and word-level timing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from engine.schemas.timeline import (
    AdapterState,
    AdapterStatus,
    SpeechSegment,
    WordSegment,
)


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
    model_name: str = "small",
    language: str | None = None,
    batch_size: int = 8,
    diarize: bool = False,
) -> tuple[list[SpeechSegment], list[WordSegment], AdapterStatus]:
    """Run WhisperX transcription when available."""
    config = {
        "model_name": model_name,
        "language": language,
        "batch_size": batch_size,
        "diarize": diarize,
    }
    try:
        import whisperx
    except ModuleNotFoundError:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="WhisperX not installed.",
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive import boundary
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX import failed: {exc}",
            config=config,
        )

    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    config["device"] = device
    config["compute_type"] = compute_type

    try:
        model = whisperx.load_model(
            model_name,
            device,
            compute_type=compute_type,
            language=language,
        )
        audio = whisperx.load_audio(str(video_path))
        transcript = model.transcribe(audio, batch_size=batch_size)

        segments = transcript.get("segments", [])
        detected_language = transcript.get("language")
        if detected_language:
            config["detected_language"] = detected_language

        # Alignment is optional but gives word-level timestamps when available.
        try:
            align_model, align_metadata = whisperx.load_align_model(
                language_code=detected_language or language or "en",
                device=device,
            )
            aligned = whisperx.align(
                segments,
                align_model,
                align_metadata,
                audio,
                device,
            )
            segments = aligned.get("segments", segments)
        except Exception as exc:
            config["align_note"] = f"alignment skipped: {exc}"

        if diarize:
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if hf_token:
                try:
                    diarizer = whisperx.DiarizationPipeline(
                        use_auth_token=hf_token,
                        device=device,
                    )
                    diarization_result = diarizer(audio)
                    with_speakers = whisperx.assign_word_speakers(
                        diarization_result,
                        {"segments": segments},
                    )
                    segments = with_speakers.get("segments", segments)
                except Exception as exc:
                    config["diarization_note"] = f"diarization skipped: {exc}"
            else:
                config["diarization_note"] = "diarization requested but HUGGINGFACE_TOKEN is missing."

        speech_segments: list[SpeechSegment] = []
        word_segments: list[WordSegment] = []
        for index, segment in enumerate(segments):
            seg_id = f"speech_{index:04d}"
            segment_start = float(segment.get("start", 0.0))
            segment_end = float(segment.get("end", segment_start))
            speaker = segment.get("speaker")
            speech_segments.append(
                SpeechSegment(
                    segment_id=seg_id,
                    start_sec=max(0.0, segment_start),
                    end_sec=max(0.0, segment_end),
                    text=str(segment.get("text", "")).strip(),
                    confidence=_confidence_or_none(segment.get("confidence")),
                    speaker=str(speaker) if speaker else None,
                )
            )
            words = segment.get("words", []) or []
            for word_index, word in enumerate(words):
                word_start = float(word.get("start", segment_start))
                word_end = float(word.get("end", word_start))
                token = str(word.get("word", "")).strip()
                if not token:
                    continue
                word_segments.append(
                    WordSegment(
                        word_id=f"{seg_id}_word_{word_index:03d}",
                        start_sec=max(0.0, word_start),
                        end_sec=max(0.0, word_end),
                        word=token,
                        confidence=_confidence_or_none(word.get("score")),
                        speaker=str(word.get("speaker") or speaker) if (word.get("speaker") or speaker) else None,
                    )
                )

        version = getattr(whisperx, "__version__", None)
        return speech_segments, word_segments, AdapterStatus(
            state=AdapterState.available,
            version=str(version) if version else None,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - adapter runtime boundary
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX runtime failed: {exc}",
            config=config,
        )
