"""Build fused analysis timelines from source videos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from engine.adapters import (
    ffmpeg_adapter,
    opennsfw2_adapter,
    pyscenedetect_adapter,
    transnetv2_adapter,
    whisperx_adapter,
    yt_dlp_adapter,
)
from engine.fusion.boundary_fusion import (
    BoundaryFusionConfig,
    fuse_boundaries,
)
from engine.schemas.timeline import (
    AdapterState,
    AdapterStatus,
    AnalysisMetadata,
    AnalysisTimeline,
    RatingEvidence,
    SceneBoundary,
    SceneSegment,
    SpeechSegment,
    WordSegment,
)

PROFANITY_TERMS = {
    "fuck",
    "fucking",
    "shit",
    "bitch",
    "asshole",
    "motherfucker",
    "dick",
    "cunt",
}

DEFAULT_ANALYSIS_CONFIG: dict[str, Any] = {
    "fusion": {
        "cluster_tolerance_frames": 8,
        "nms_window_frames": 8,
    },
    "adapters": {
        "pyscenedetect": {
            "threshold": 27.0,
            "min_scene_len_sec": 0.8,
            "ffmpeg_scene_threshold": 0.35,
        },
        "transnetv2": {
            "threshold": 0.5,
            "min_gap_frames": 4,
        },
        "whisperx": {
            "model_name": "small",
            "batch_size": 8,
            "diarize": False,
        },
        "opennsfw2": {
            "threshold": 0.65,
        },
    },
    "sampling": {
        "sample_every_sec": 5.0,
        "max_visual_samples": 90,
    },
}

ProgressCallback = Callable[[str], None]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _read_url_from_file(path: str) -> str:
    url_file = Path(path)
    if not url_file.exists():
        raise FileNotFoundError(f"url file not found: {path}")

    for raw_line in url_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    raise ValueError(f"url file has no usable URL lines: {path}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_analysis_config(config_path: str) -> tuple[dict[str, Any], list[str]]:
    path = Path(config_path)
    notes: list[str] = []
    if not path.exists():
        notes.append(f"config file not found at {config_path}; using built-in defaults.")
        return DEFAULT_ANALYSIS_CONFIG, notes

    try:
        import yaml
    except ModuleNotFoundError:
        notes.append("PyYAML not installed; using built-in defaults for analysis config.")
        return DEFAULT_ANALYSIS_CONFIG, notes

    with path.open("r", encoding="utf-8") as config_file:
        loaded = yaml.safe_load(config_file) or {}
    if not isinstance(loaded, dict):
        notes.append(f"invalid config format in {config_path}; using built-in defaults.")
        return DEFAULT_ANALYSIS_CONFIG, notes

    return _deep_merge(DEFAULT_ANALYSIS_CONFIG, loaded), notes


def _clip_time(value: float, duration_sec: float) -> float:
    return max(0.0, min(float(value), duration_sec))


def _sanitize_speech_segments(
    segments: list[SpeechSegment], *, duration_sec: float
) -> list[SpeechSegment]:
    sanitized: list[SpeechSegment] = []
    for segment in segments:
        start = _clip_time(segment.start_sec, duration_sec)
        end = _clip_time(segment.end_sec, duration_sec)
        if end < start:
            end = start
        sanitized.append(
            segment.model_copy(update={"start_sec": start, "end_sec": end})
        )
    return sanitized


def _sanitize_word_segments(
    segments: list[WordSegment], *, duration_sec: float
) -> list[WordSegment]:
    sanitized: list[WordSegment] = []
    for segment in segments:
        start = _clip_time(segment.start_sec, duration_sec)
        end = _clip_time(segment.end_sec, duration_sec)
        if end < start:
            end = start
        sanitized.append(
            segment.model_copy(update={"start_sec": start, "end_sec": end})
        )
    return sanitized


def _dedupe_boundaries(
    boundaries: list[SceneBoundary], *, tolerance_frames: int
) -> list[SceneBoundary]:
    if not boundaries:
        return []
    ordered = sorted(boundaries, key=lambda item: item.frame_index)
    deduped: list[SceneBoundary] = [ordered[0]]
    for boundary in ordered[1:]:
        if abs(boundary.frame_index - deduped[-1].frame_index) <= tolerance_frames:
            if boundary.fused_score > deduped[-1].fused_score:
                deduped[-1] = boundary
            continue
        deduped.append(boundary)
    return deduped


def _build_scenes(
    *,
    boundaries: list[SceneBoundary],
    fps: float,
    duration_sec: float,
    total_frames: int,
) -> list[SceneSegment]:
    if total_frames <= 0:
        return []

    max_end_frame = max(0, total_frames - 1)
    usable_boundaries = [
        boundary
        for boundary in boundaries
        if 0 < boundary.frame_index < max_end_frame
    ]

    scenes: list[SceneSegment] = []
    start_frame = 0
    for index, boundary in enumerate(usable_boundaries):
        end_frame = max(start_frame, boundary.frame_index - 1)
        start_sec = start_frame / fps
        end_sec = min(duration_sec, (end_frame + 1) / fps)
        scenes.append(
            SceneSegment(
                scene_id=f"scene_{index:04d}",
                start_frame=start_frame,
                end_frame=end_frame,
                start_sec=round(start_sec, 6),
                end_sec=round(end_sec, 6),
                boundary_score=round(boundary.fused_score, 6),
            )
        )
        start_frame = boundary.frame_index

    end_sec = min(duration_sec, (max_end_frame + 1) / fps)
    scenes.append(
        SceneSegment(
            scene_id=f"scene_{len(scenes):04d}",
            start_frame=start_frame,
            end_frame=max_end_frame,
            start_sec=round(start_frame / fps, 6),
            end_sec=round(end_sec, 6),
            boundary_score=0.0,
        )
    )
    return scenes


def _build_rating_evidence(
    *,
    speech_segments: list[SpeechSegment],
    word_segments: list[WordSegment],
    visual_flags: list,
) -> list[RatingEvidence]:
    evidence: list[RatingEvidence] = []
    index = 0

    for word in word_segments:
        token = word.word.strip().lower().strip(".,!?\"'()[]{}")
        if token in PROFANITY_TERMS:
            evidence.append(
                RatingEvidence(
                    evidence_id=f"evidence_{index:04d}",
                    start_sec=word.start_sec,
                    end_sec=word.end_sec,
                    dimension="language",
                    evidence_type="strong_profanity",
                    score=0.85,
                    references={"word_id": word.word_id},
                )
            )
            index += 1

    for speech in speech_segments:
        text = speech.text.lower()
        if "kill" in text or "murder" in text:
            evidence.append(
                RatingEvidence(
                    evidence_id=f"evidence_{index:04d}",
                    start_sec=speech.start_sec,
                    end_sec=speech.end_sec,
                    dimension="violence",
                    evidence_type="violent_dialogue",
                    score=0.60,
                    references={"segment_id": speech.segment_id},
                )
            )
            index += 1

    for flag in visual_flags:
        evidence.append(
            RatingEvidence(
                evidence_id=f"evidence_{index:04d}",
                start_sec=flag.sec,
                end_sec=flag.sec,
                dimension="sexual",
                evidence_type=flag.label,
                score=flag.score,
                references={"flag_id": flag.flag_id},
            )
        )
        index += 1
    return evidence


def _adapter_available_status() -> AdapterStatus:
    return AdapterStatus(state=AdapterState.available)


def build_analysis_timeline(
    *,
    input_video_path: str | None = None,
    source_url: str | None = None,
    job_id: str,
    artifacts_root: str = "artifacts",
    work_root: str = "data/work",
    download_dir: str = "data/inbox",
    sample_every_sec: float | None = None,
    max_visual_samples: int | None = None,
    diarize: bool | None = None,
    config_path: str = "configs/analysis.yaml",
    progress: ProgressCallback | None = None,
    download_progress: ProgressCallback | None = None,
) -> tuple[AnalysisTimeline, Path]:
    if (input_video_path is None and source_url is None) or (
        input_video_path is not None and source_url is not None
    ):
        raise ValueError("provide exactly one source: input_video_path or source_url")

    ingest_status: AdapterStatus
    source_notes: list[str] = []
    if source_url is not None:
        _emit(progress, "Downloading source video from URL.")
        source_path, ingest_status = yt_dlp_adapter.download_video_from_url(
            source_url=source_url,
            output_dir=download_dir,
            job_id=job_id,
            progress=download_progress,
        )
        source_notes.append(f"source_url={source_url}")
    else:
        source_path = Path(str(input_video_path))
        if not source_path.exists():
            raise FileNotFoundError(f"input video not found: {input_video_path}")
        ingest_status = AdapterStatus(
            state=AdapterState.available,
            detail="Using local file input.",
            config={"mode": "local_file"},
        )

    _emit(progress, "Loading analysis config.")
    analysis_config, config_notes = _load_analysis_config(config_path)
    fusion_cfg = analysis_config["fusion"]
    adapter_cfg = analysis_config["adapters"]
    sampling_cfg = analysis_config["sampling"]

    resolved_sample_every_sec = (
        sample_every_sec
        if sample_every_sec is not None
        else float(sampling_cfg["sample_every_sec"])
    )
    resolved_max_visual_samples = (
        max_visual_samples
        if max_visual_samples is not None
        else int(sampling_cfg["max_visual_samples"])
    )
    resolved_diarize = (
        diarize
        if diarize is not None
        else bool(adapter_cfg["whisperx"].get("diarize", False))
    )

    _emit(progress, "Probing source video metadata.")
    video_metadata = ffmpeg_adapter.probe_video(source_path)
    ffmpeg_status = _adapter_available_status().model_copy(
        update={
            "version": ffmpeg_adapter.ffmpeg_version(),
            "config": {
                "probe": "ffprobe -show_streams -show_format",
            },
        }
    )

    _emit(progress, "Running scene boundary detector (PySceneDetect/fallback).")
    pyscene_boundaries, pyscene_status = pyscenedetect_adapter.detect_boundaries(
        source_path,
        fps=video_metadata.fps,
        threshold=float(adapter_cfg["pyscenedetect"]["threshold"]),
        min_scene_len_sec=float(adapter_cfg["pyscenedetect"]["min_scene_len_sec"]),
        ffmpeg_scene_threshold=float(
            adapter_cfg["pyscenedetect"]["ffmpeg_scene_threshold"]
        ),
    )
    _emit(progress, "Running shot boundary detector (TransNetV2 when available).")
    transnet_boundaries, transnet_status = transnetv2_adapter.detect_boundaries(
        source_path,
        threshold=float(adapter_cfg["transnetv2"]["threshold"]),
        min_gap_frames=int(adapter_cfg["transnetv2"]["min_gap_frames"]),
    )

    _emit(progress, "Computing local frame deltas and fusing detector boundaries.")
    fusion_config = BoundaryFusionConfig(
        cluster_tolerance_frames=int(fusion_cfg["cluster_tolerance_frames"]),
        nms_window_frames=int(fusion_cfg["nms_window_frames"]),
    )
    local_scores = ffmpeg_adapter.local_frame_delta_scores(
        source_path,
        [
            candidate.frame_index
            for candidate in [*pyscene_boundaries, *transnet_boundaries]
        ],
    )
    canonical_boundaries = fuse_boundaries(
        transnet_boundaries=transnet_boundaries,
        pyscene_boundaries=pyscene_boundaries,
        local_frame_delta_scores_by_frame=local_scores,
        config=fusion_config,
    )

    boundary_models = _dedupe_boundaries(
        [
            SceneBoundary(
                frame_index=boundary.frame_index,
                sec=round(boundary.frame_index / video_metadata.fps, 6),
                fused_score=round(boundary.fused_score, 6),
                sources=boundary.sources,
                component_scores={
                    key: round(value, 6)
                    for key, value in boundary.component_scores.items()
                },
            )
            for boundary in canonical_boundaries
        ],
        tolerance_frames=fusion_config.cluster_tolerance_frames,
    )

    _emit(progress, "Building canonical scene timeline.")
    scenes = _build_scenes(
        boundaries=boundary_models,
        fps=video_metadata.fps,
        duration_sec=video_metadata.duration_sec,
        total_frames=video_metadata.total_frames,
    )

    _emit(progress, "Running speech analysis (WhisperX when available).")
    speech_segments, word_segments, whisperx_status = whisperx_adapter.transcribe(
        source_path,
        model_name=str(adapter_cfg["whisperx"]["model_name"]),
        batch_size=int(adapter_cfg["whisperx"]["batch_size"]),
        diarize=resolved_diarize,
    )
    speech_segments = _sanitize_speech_segments(
        speech_segments, duration_sec=video_metadata.duration_sec
    )
    word_segments = _sanitize_word_segments(
        word_segments, duration_sec=video_metadata.duration_sec
    )

    _emit(progress, "Sampling frames for visual analysis.")
    work_dir = Path(work_root) / job_id / "frames"
    sampled_frames = ffmpeg_adapter.extract_sampled_frames(
        source_path,
        duration_sec=video_metadata.duration_sec,
        output_dir=work_dir,
        sample_every_sec=resolved_sample_every_sec,
        max_samples=resolved_max_visual_samples,
    )
    _emit(progress, "Running visual NSFW scoring (OpenNSFW2 when available).")
    visual_flags, opennsfw_status = opennsfw2_adapter.score_sampled_frames(
        sampled_frames,
        fps=video_metadata.fps,
        threshold=float(adapter_cfg["opennsfw2"]["threshold"]),
    )

    _emit(progress, "Building rating evidence and writing artifact.")
    rating_evidence = _build_rating_evidence(
        speech_segments=speech_segments,
        word_segments=word_segments,
        visual_flags=visual_flags,
    )

    metadata = AnalysisMetadata(
        detector_configs={
            "fusion": {
                "cluster_tolerance_frames": fusion_config.cluster_tolerance_frames,
                "nms_window_frames": fusion_config.nms_window_frames,
                "score_formula": (
                    "0.45*transnet + 0.25*pyscene + 0.20*agreement + 0.10*local_delta"
                ),
            },
            "pyscenedetect": pyscene_status.config,
            "transnetv2": transnet_status.config,
            "whisperx": whisperx_status.config,
            "opennsfw2": opennsfw_status.config,
            "sampling": {
                "sample_every_sec": resolved_sample_every_sec,
                "max_visual_samples": resolved_max_visual_samples,
            },
            "source_ingest": ingest_status.config,
        },
        adapter_status={
            "source_ingest": ingest_status,
            "ffmpeg": ffmpeg_status,
            "pyscenedetect": pyscene_status,
            "transnetv2": transnet_status,
            "whisperx": whisperx_status,
            "opennsfw2": opennsfw_status,
        },
        fusion={
            "candidate_count": len(pyscene_boundaries) + len(transnet_boundaries),
            "canonical_boundary_count": len(boundary_models),
            "cluster_tolerance_frames": fusion_config.cluster_tolerance_frames,
            "nms_window_frames": fusion_config.nms_window_frames,
        },
        notes=[*config_notes, *source_notes],
    )

    timeline = AnalysisTimeline(
        job_id=job_id,
        source_video=str(source_path),
        fps=round(video_metadata.fps, 6),
        duration_sec=round(video_metadata.duration_sec, 6),
        scenes=scenes,
        speech_segments=speech_segments,
        word_segments=word_segments,
        visual_flags=visual_flags,
        rating_evidence=rating_evidence,
        boundaries=boundary_models,
        metadata=metadata,
    )

    output_dir = Path(artifacts_root) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "analysis_timeline.json"
    output_path.write_text(
        json.dumps(timeline.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return timeline, output_path


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build fused analysis timeline.")
    parser.add_argument(
        "--input",
        default=None,
        help="Path to source video (e.g. data/inbox/input.mp4).",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Source video URL (e.g. YouTube URL) to download before analysis.",
    )
    parser.add_argument(
        "--url-file",
        default=None,
        help="Path to a text file containing a URL (uses first non-empty non-comment line).",
    )
    parser.add_argument("--job-id", required=True, help="Job identifier.")
    parser.add_argument(
        "--artifacts-root",
        default="artifacts",
        help="Artifact root directory.",
    )
    parser.add_argument(
        "--work-root",
        default="data/work",
        help="Working directory for sampled frames.",
    )
    parser.add_argument(
        "--download-dir",
        default="data/inbox",
        help="Download destination directory when --url is used.",
    )
    parser.add_argument(
        "--sample-every-sec",
        type=float,
        default=None,
        help="Visual model sampling interval in seconds.",
    )
    parser.add_argument(
        "--max-visual-samples",
        type=int,
        default=None,
        help="Maximum number of visual samples.",
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Enable WhisperX diarization when token/model dependencies are available.",
    )
    parser.add_argument(
        "--config",
        default="configs/analysis.yaml",
        help="YAML config path for analysis thresholds and adapter settings.",
    )
    return parser


def main() -> None:
    class _StepPrinter:
        def __init__(self) -> None:
            self.step = 0

        def __call__(self, message: str) -> None:
            self.step += 1
            print(f"[step {self.step:02d}] {message}", flush=True)

    def _download_detail(message: str) -> None:
        print(f"  [download] {message}", flush=True)

    parser = _build_cli()
    args = parser.parse_args()
    sources_selected = sum(
        bool(value) for value in [args.input, args.url, args.url_file]
    )
    if sources_selected != 1:
        parser.error("provide exactly one of --input, --url, or --url-file")

    resolved_url = args.url
    if args.url_file:
        resolved_url = _read_url_from_file(args.url_file)

    step_printer = _StepPrinter()
    step_printer("Starting analysis pipeline.")
    timeline, output_path = build_analysis_timeline(
        input_video_path=args.input,
        source_url=resolved_url,
        job_id=args.job_id,
        artifacts_root=args.artifacts_root,
        work_root=args.work_root,
        download_dir=args.download_dir,
        sample_every_sec=args.sample_every_sec,
        max_visual_samples=args.max_visual_samples,
        diarize=args.diarize if args.diarize else None,
        config_path=args.config,
        progress=step_printer,
        download_progress=_download_detail,
    )
    step_printer("Analysis completed.")
    print(f"analysis_timeline: {output_path}")
    print(f"duration_sec: {timeline.duration_sec}")
    print(f"fps: {timeline.fps}")
    print(f"scene_count: {len(timeline.scenes)}")


if __name__ == "__main__":
    main()
