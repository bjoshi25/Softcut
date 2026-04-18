"""WhisperX adapter for ASR and word-level timing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from engine.schemas.timeline import (
    AdapterState,
    AdapterStatus,
    SpeechSegment,
    WordSegment,
)

ProgressCallback = Callable[[str], None]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


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
    timeout_sec: int = 900,
    progress: ProgressCallback | None = None,
) -> tuple[list[SpeechSegment], list[WordSegment], AdapterStatus]:
    """Run WhisperX transcription in an isolated worker process.

    Native crashes (e.g., torch/ctranslate segfaults) should not crash the whole job.
    """
    config = {
        "model_name": model_name,
        "language": language,
        "batch_size": batch_size,
        "diarize": diarize,
        "timeout_sec": timeout_sec,
        "mode": "isolated_worker",
        "chunk_policy": "single_chunk_worker",
    }

    _emit(progress, "Starting WhisperX worker process.")
    with tempfile.NamedTemporaryFile(
        suffix=".json",
        prefix="softcut_whisperx_",
        delete=False,
    ) as tmp:
        output_path = Path(tmp.name)

    command = [
        sys.executable,
        "-m",
        "engine.adapters.whisperx_worker",
        "--video-path",
        str(video_path),
        "--model-name",
        model_name,
        "--batch-size",
        str(batch_size),
        "--output-path",
        str(output_path),
    ]
    if language:
        command.extend(["--language", language])
    if diarize:
        command.append("--diarize")

    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(30, int(timeout_sec)),
            env={
                **os.environ,
                # More stable defaults for older macOS CPUs / ctranslate2 on WhisperX.
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1"),
                "CT2_NUM_THREADS": os.environ.get("CT2_NUM_THREADS", "1"),
                "TOKENIZERS_PARALLELISM": os.environ.get("TOKENIZERS_PARALLELISM", "false"),
            },
        )
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        _emit(progress, f"WhisperX worker timed out after {timeout_sec}s.")
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX worker timed out after {timeout_sec}s.",
            config=config,
        )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "worker failed"
        output_path.unlink(missing_ok=True)
        _emit(progress, f"WhisperX worker failed (exit {proc.returncode}).")
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX worker failed (exit {proc.returncode}): {detail}",
            config=config,
        )
    if not output_path.exists():
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="WhisperX worker completed but returned no output.",
            config=config,
        )

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX worker output parse failed: {exc}",
            config=config,
        )
    finally:
        output_path.unlink(missing_ok=True)

    speech_payload = payload.get("speech_segments", [])
    word_payload = payload.get("word_segments", [])
    status_payload = payload.get("status", {})
    speech_segments = [SpeechSegment.model_validate(item) for item in speech_payload]
    word_segments = [WordSegment.model_validate(item) for item in word_payload]
    status = AdapterStatus.model_validate(status_payload)
    _emit(
        progress,
        f"WhisperX worker returned speech={len(speech_segments)} words={len(word_segments)}.",
    )
    return speech_segments, word_segments, status


def transcribe_in_process(
    video_path: str | Path,
    *,
    model_name: str = "small",
    language: str | None = None,
    batch_size: int = 8,
    diarize: bool = False,
    progress: ProgressCallback | None = None,
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
    # int8 can be fast, but float32 is safer on older CPU-only macOS setups.
    compute_type = "float16" if device == "cuda" else "float32"
    config["device"] = device
    config["compute_type"] = compute_type

    try:
        if language:
            _emit(
                progress,
                f"Loading WhisperX model={model_name} device={device} language={language}.",
            )
        else:
            _emit(
                progress,
                (
                    f"Loading WhisperX model={model_name} device={device} with language auto-detect "
                    "(slower than fixed language)."
                ),
            )
        model = whisperx.load_model(
            model_name,
            device,
            compute_type=compute_type,
            language=language,
        )

        _emit(progress, "Loading audio for ASR.")
        audio = whisperx.load_audio(str(video_path))

        _emit(progress, "Transcribing audio (this can take a while on CPU).")
        transcribe_start = time.monotonic()
        transcript = model.transcribe(audio, batch_size=batch_size)
        _emit(
            progress,
            f"Transcription finished in {time.monotonic() - transcribe_start:.1f}s.",
        )

        segments = transcript.get("segments", [])
        detected_language = transcript.get("language")
        if detected_language:
            config["detected_language"] = detected_language
            _emit(progress, f"Detected language: {detected_language}.")

        # Alignment is optional but gives word-level timestamps when available.
        try:
            _emit(progress, "Running word-level alignment.")
            align_start = time.monotonic()
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
            _emit(
                progress,
                f"Alignment finished in {time.monotonic() - align_start:.1f}s.",
            )
        except Exception as exc:
            config["align_note"] = f"alignment skipped: {exc}"
            _emit(progress, f"Alignment skipped: {exc}")

        if diarize:
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if hf_token:
                try:
                    _emit(progress, "Running diarization.")
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
                    _emit(progress, f"Diarization skipped: {exc}")
            else:
                config["diarization_note"] = (
                    "diarization requested but HUGGINGFACE_TOKEN is missing."
                )
                _emit(progress, "Diarization requested but HUGGINGFACE_TOKEN is missing.")

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
                        speaker=(
                            str(word.get("speaker") or speaker)
                            if (word.get("speaker") or speaker)
                            else None
                        ),
                    )
                )

        version = getattr(whisperx, "__version__", None)
        _emit(
            progress,
            f"Built ASR segments: speech={len(speech_segments)} words={len(word_segments)}.",
        )
        return speech_segments, word_segments, AdapterStatus(
            state=AdapterState.available,
            version=str(version) if version else None,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - adapter runtime boundary
        _emit(progress, f"WhisperX runtime failed: {exc}")
        return [], [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"WhisperX runtime failed: {exc}",
            config=config,
        )
