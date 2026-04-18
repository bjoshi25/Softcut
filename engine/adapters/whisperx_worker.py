"""Isolated worker for WhisperX transcription."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.adapters.whisperx_adapter import transcribe_in_process


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WhisperX isolated worker")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--model-name", default="small")
    parser.add_argument("--language", default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--diarize", action="store_true")
    parser.add_argument("--output-path", required=True)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    speech, words, status = transcribe_in_process(
        args.video_path,
        model_name=args.model_name,
        language=args.language,
        batch_size=args.batch_size,
        diarize=args.diarize,
        progress=None,
    )
    payload = {
        "speech_segments": [segment.model_dump(mode="json") for segment in speech],
        "word_segments": [segment.model_dump(mode="json") for segment in words],
        "status": status.model_dump(mode="json"),
    }
    Path(args.output_path).write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
