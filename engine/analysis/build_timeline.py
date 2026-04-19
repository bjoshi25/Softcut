"""Build fused analysis timelines from source videos."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from engine.adapters import (
    ffmpeg_whisper_adapter,
    ffmpeg_adapter,
    openai_whisper_adapter,
    opennsfw2_adapter,
    pyscenedetect_adapter,
    subtitle_adapter,
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
    AnalysisQualityReport,
    AnalysisTimeline,
    ContinuityFeature,
    EditContextWindow,
    RatingEvidence,
    SafeCutPoint,
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

LANGUAGE_INTENSITY_MAP = {
    "fuck": 0.92,
    "fucking": 0.92,
    "motherfucker": 0.95,
    "shit": 0.78,
    "bullshit": 0.76,
    "bitch": 0.72,
    "asshole": 0.82,
    "dick": 0.66,
    "damn": 0.45,
    "hell": 0.40,
}

SUGGESTIVE_PHRASES = {
    "make out": 0.55,
    "hook up": 0.58,
    "sex": 0.72,
    "nude": 0.75,
}

VIOLENCE_PHRASES = {
    "kill": 0.62,
    "murder": 0.74,
    "shoot": 0.58,
    "blood": 0.52,
    "explode": 0.56,
}

DEFAULT_ANALYSIS_CONFIG: dict[str, Any] = {
    "run_profile": "degraded",
    "fusion": {
        "cluster_tolerance_frames": 8,
        "nms_window_frames": 8,
    },
    "adapters": {
        "pyscenedetect": {
            "threshold": 27.0,
            "min_scene_len_sec": 1.0,
            "ffmpeg_scene_threshold": 0.35,
        },
        "transnetv2": {
            "threshold": 0.58,
            "min_gap_frames": 8,
            "model_dir": None,
        },
        "whisperx": {
            "model_name": "small",
            "language": None,
            "batch_size": 8,
            "diarize": False,
        },
        "openai_whisper": {
            "enabled": True,
            "model_name": "base",
        },
        "ffmpeg_whisper": {
            "enabled": False,
            "model_path": None,
            "language": "auto",
            "queue": 10,
            "use_gpu": True,
        },
        "opennsfw2": {
            "mode": "scene_aware_sparse",
            "threshold": 0.25,
            "frame_interval": 8,
            "aggregation_size": 1,
            "batch_size": 8,
            "progress_bar": False,
            "calibration_floor": 0.18,
            "calibration_quantile": 0.995,
            "merge_gap_sec": 1.0,
            "max_flags_per_minute": 18.0,
            "per_scene_max_frames": 4,
            "boundary_cluster_sec": 0.4,
            "long_scene_stride_sec": 2.0,
            "suspicious_score_ratio": 0.75,
            "dense_window_sec": 1.5,
            "dense_frame_interval": 1,
            "max_dense_windows": 16,
        },
        "subtitle_bootstrap": {
            "enabled": False,
            "language": "en",
            "min_segments_for_use": 10,
        },
    },
    "quality": {
        "min_evidence_per_minute": 0.4,
        "extreme_cut_per_minute": 45.0,
        "low_confidence_threshold": 0.2,
        "strict_requires_transnet": True,
        "strict_requires_visual": True,
    },
    "runtime": {
        "asr_timeout_sec": 900,
        "visual_timeout_sec": 1800,
        "visual_progress_interval_sec": 15.0,
        "visual_omp_threads": 2,
        "visual_tf_interop_threads": 2,
        "visual_tf_intraop_threads": 2,
        "overwrite_job_artifacts": True,
        "prune_other_artifacts": False,
        "keep_artifact_jobs": 1,
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


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if overwrite and output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)


def _prune_old_artifact_dirs(
    artifacts_root: Path,
    *,
    keep_job_id: str,
    keep_count: int,
) -> list[str]:
    if keep_count < 1:
        keep_count = 1
    if not artifacts_root.exists():
        return []

    job_dirs = [path for path in artifacts_root.iterdir() if path.is_dir()]
    if not job_dirs:
        return []

    keep_names = {keep_job_id}
    other_dirs = [path for path in job_dirs if path.name != keep_job_id]
    other_dirs.sort(
        key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
        reverse=True,
    )
    for directory in other_dirs[: max(0, keep_count - 1)]:
        keep_names.add(directory.name)

    removed: list[str] = []
    for directory in job_dirs:
        if directory.name in keep_names:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        removed.append(directory.name)
    return sorted(removed)


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
        token = _normalize_text_token(word.word)
        base_score = LANGUAGE_INTENSITY_MAP.get(token)
        if base_score is not None or token in PROFANITY_TERMS:
            score = max(base_score or 0.70, 0.70)
            evidence_type = "strong_profanity" if score >= 0.80 else "moderate_profanity"
            evidence.append(
                RatingEvidence(
                    evidence_id=f"evidence_{index:04d}",
                    start_sec=word.start_sec,
                    end_sec=word.end_sec,
                    dimension="language",
                    evidence_type=evidence_type,
                    score=min(0.98, score),
                    references={"word_id": word.word_id},
                )
            )
            index += 1

    for speech in speech_segments:
        text = speech.text.lower()
        for phrase, score in VIOLENCE_PHRASES.items():
            if phrase in text:
                evidence.append(
                    RatingEvidence(
                        evidence_id=f"evidence_{index:04d}",
                        start_sec=speech.start_sec,
                        end_sec=speech.end_sec,
                        dimension="violence",
                        evidence_type="violent_dialogue",
                        score=score,
                        references={"segment_id": speech.segment_id, "phrase": phrase},
                    )
                )
                index += 1
                break
        for phrase, score in SUGGESTIVE_PHRASES.items():
            if phrase in text:
                evidence.append(
                    RatingEvidence(
                        evidence_id=f"evidence_{index:04d}",
                        start_sec=speech.start_sec,
                        end_sec=speech.end_sec,
                        dimension="suggestive_dialogue",
                        evidence_type="suggestive_dialogue",
                        score=score,
                        references={"segment_id": speech.segment_id, "phrase": phrase},
                    )
                )
                index += 1
                break

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


def _normalize_text_token(value: str) -> str:
    cleaned = value.strip().lower().strip(".,!?\"'()[]{}")
    if cleaned.endswith("ing") and len(cleaned) > 5:
        return cleaned[:-3]
    if cleaned.endswith("ed") and len(cleaned) > 4:
        return cleaned[:-2]
    return cleaned


def _calibrate_pyscene_scores(
    *,
    pyscene_boundaries: list,
    transnet_boundaries: list,
    local_scores: dict[int, float],
    tolerance_frames: int,
) -> None:
    transnet_frames = [boundary.frame_index for boundary in transnet_boundaries]
    for candidate in pyscene_boundaries:
        local = local_scores.get(candidate.frame_index, 0.0)
        agreement = 1.0 if any(
            abs(candidate.frame_index - frame) <= tolerance_frames
            for frame in transnet_frames
        ) else 0.0
        calibrated = 0.35 + 0.40 * local + 0.25 * agreement
        candidate.score = max(0.15, min(0.98, calibrated))


def _score_entropy(values: list[float]) -> float:
    if not values:
        return 0.0
    bins = [0, 0, 0, 0, 0]
    for value in values:
        index = min(4, max(0, int(value * 5)))
        bins[index] += 1
    total = float(sum(bins))
    entropy = 0.0
    for count in bins:
        if count <= 0:
            continue
        p = count / total
        entropy += -p * math.log2(p)
    return entropy / math.log2(5.0)


def _speech_density_between(
    speech_segments: list[SpeechSegment], start_sec: float, end_sec: float
) -> float:
    window = max(0.01, end_sec - start_sec)
    spoken = 0.0
    for segment in speech_segments:
        overlap_start = max(start_sec, segment.start_sec)
        overlap_end = min(end_sec, segment.end_sec)
        if overlap_end > overlap_start:
            spoken += overlap_end - overlap_start
    return max(0.0, min(1.0, spoken / window))


def _nearest_boundary(
    sec: float, boundaries: list[SceneBoundary]
) -> tuple[SceneBoundary | None, float]:
    if not boundaries:
        return None, 9999.0
    nearest = min(boundaries, key=lambda boundary: abs(boundary.sec - sec))
    return nearest, abs(nearest.sec - sec)


def _build_edit_ready_features(
    *,
    fps: float,
    duration_sec: float,
    rating_evidence: list[RatingEvidence],
    boundaries: list[SceneBoundary],
    local_scores: dict[int, float],
    speech_segments: list[SpeechSegment],
) -> tuple[list[SafeCutPoint], list[EditContextWindow], list[ContinuityFeature]]:
    safe_cut_points: list[SafeCutPoint] = []
    edit_windows: list[EditContextWindow] = []
    continuity_features: list[ContinuityFeature] = []

    for index, evidence in enumerate(rating_evidence):
        anchor_start = max(0.0, evidence.start_sec - 0.30)
        anchor_end = min(duration_sec, evidence.end_sec + 0.30)
        for kind, anchor_sec in (("pre", anchor_start), ("post", anchor_end)):
            frame_index = max(0, int(round(anchor_sec * fps)))
            local = local_scores.get(frame_index, 0.0)
            nearest_boundary, proximity = _nearest_boundary(anchor_sec, boundaries)
            boundary_conf = nearest_boundary.fused_score if nearest_boundary else 0.0
            speech_density = _speech_density_between(
                speech_segments,
                max(0.0, anchor_sec - 0.5),
                min(duration_sec, anchor_sec + 0.5),
            )
            safe_cut_points.append(
                SafeCutPoint(
                    point_id=f"cut_{index:04d}_{kind}",
                    sec=round(anchor_sec, 6),
                    frame_index=frame_index,
                    kind=kind,
                    motion_score=round(local, 6),
                    speech_density=round(speech_density, 6),
                    boundary_confidence=round(boundary_conf, 6),
                    references={"evidence_id": evidence.evidence_id},
                )
            )
            continuity_features.append(
                ContinuityFeature(
                    feature_id=f"continuity_{index:04d}_{kind}",
                    start_sec=max(0.0, anchor_sec - 0.25),
                    end_sec=min(duration_sec, anchor_sec + 0.25),
                    motion_score=round(local, 6),
                    speech_density=round(speech_density, 6),
                    scene_proximity_sec=round(proximity, 6),
                    boundary_confidence=round(boundary_conf, 6),
                    references={"evidence_id": evidence.evidence_id},
                )
            )
        edit_windows.append(
            EditContextWindow(
                window_id=f"window_{index:04d}",
                evidence_id=evidence.evidence_id,
                start_sec=max(0.0, evidence.start_sec - 0.40),
                end_sec=min(duration_sec, evidence.end_sec + 0.40),
                pre_pad_sec=0.40,
                post_pad_sec=0.40,
                overlap_tag="compatible",
                compatible_actions=[
                    "mute_word",
                    "beep_word",
                    "trim_segment",
                    "remove_scene",
                ],
            )
        )
    return safe_cut_points, edit_windows, continuity_features


def _determine_asr_mode(
    *,
    speech_segments: list[SpeechSegment],
    whisperx_status: AdapterStatus,
    ffmpeg_whisper_status: AdapterStatus,
    openai_whisper_status: AdapterStatus,
) -> str:
    if speech_segments and (
        whisperx_status.state == AdapterState.available
        or ffmpeg_whisper_status.state == AdapterState.available
        or openai_whisper_status.state == AdapterState.available
    ):
        return "full"
    if speech_segments:
        return "degraded"
    return "failed"


def _determine_visual_mode(opennsfw_status: AdapterStatus) -> str:
    if opennsfw_status.state != AdapterState.available:
        return "disabled"
    mode = str(opennsfw_status.config.get("visual_mode") or opennsfw_status.config.get("mode") or "")
    normalized = mode.strip().lower()
    if "scene_aware_sparse" in normalized:
        return "scene_aware_sparse"
    return "full"


def _build_quality_report(
    *,
    job_id: str,
    run_profile: str,
    duration_sec: float,
    rating_evidence: list[RatingEvidence],
    boundary_models: list[SceneBoundary],
    local_scores: dict[int, float],
    asr_mode: str,
    visual_mode: str,
    transnet_status: AdapterStatus,
    opennsfw_status: AdapterStatus,
    quality_cfg: dict[str, Any],
) -> AnalysisQualityReport:
    warnings: list[str] = []
    critical_findings: list[str] = []
    next_actions: list[str] = []

    local_all_zero = bool(local_scores) and all(score == 0.0 for score in local_scores.values())
    if local_all_zero:
        critical_findings.append("local_frame_delta_all_zero")
        next_actions.append("Fix ffmpeg showinfo mapping and verify non-zero local deltas.")

    single_detector_only = transnet_status.state != AdapterState.available
    if single_detector_only:
        warnings.append("single_detector_only")
        next_actions.append("Install/enable TransNetV2 for multi-detector fusion confidence.")

    cut_density = (len(boundary_models) / max(1.0, duration_sec / 60.0))
    if cut_density >= float(quality_cfg["extreme_cut_per_minute"]):
        warnings.append(f"extreme_cut_density={cut_density:.2f}/min")

    evidence_per_min = len(rating_evidence) / max(1.0, duration_sec / 60.0)
    if evidence_per_min < float(quality_cfg["min_evidence_per_minute"]):
        warnings.append(f"low_evidence_density={evidence_per_min:.2f}/min")
        next_actions.append("Increase evidence recall (lexicon/phrases/subtitles/visual adapters).")

    if asr_mode == "failed":
        critical_findings.append("asr_failed")
    elif asr_mode == "degraded":
        warnings.append("asr_degraded")

    visual_available = visual_mode != "disabled"
    if not visual_available:
        warnings.append("visual_disabled")
    elif int(opennsfw_status.config.get("visual_flag_count", 0) or 0) == 0:
        max_score = float(opennsfw_status.config.get("max_score", 0.0) or 0.0)
        warnings.append(f"visual_zero_flags_max_score={max_score:.3f}")
        next_actions.append(
            "Inspect OpenNSFW2 score diagnostics; add a complementary visual adapter "
            "if the trailer risk is violence rather than nudity/sexual content."
        )

    planner_eligible = asr_mode != "failed" and (visual_available or run_profile != "strict")
    if run_profile == "strict":
        if bool(quality_cfg.get("strict_requires_transnet", True)) and single_detector_only:
            critical_findings.append("strict_requires_transnet")
        if bool(quality_cfg.get("strict_requires_visual", True)) and not visual_available:
            critical_findings.append("strict_requires_visual")
        planner_eligible = planner_eligible and not critical_findings

    passed = planner_eligible and not critical_findings
    return AnalysisQualityReport(
        job_id=job_id,
        run_profile=run_profile,
        passed=passed,
        critical_findings=critical_findings,
        warnings=warnings,
        next_actions=next_actions,
        planner_eligible=planner_eligible,
    )

def build_analysis_timeline(
    *,
    input_video_path: str | None = None,
    source_url: str | None = None,
    job_id: str,
    artifacts_root: str = "artifacts",
    work_root: str = "data/work",
    download_dir: str = "data/inbox",
    diarize: bool | None = None,
    overwrite_job_artifacts: bool | None = None,
    prune_other_artifacts: bool | None = None,
    keep_artifact_jobs: int | None = None,
    config_path: str = "configs/analysis.yaml",
    progress: ProgressCallback | None = None,
    download_progress: ProgressCallback | None = None,
    speech_progress: ProgressCallback | None = None,
) -> tuple[AnalysisTimeline, Path]:
    if (input_video_path is None and source_url is None) or (
        input_video_path is not None and source_url is not None
    ):
        raise ValueError("provide exactly one source: input_video_path or source_url")

    ingest_status: AdapterStatus
    source_notes: list[str] = []
    step_timings: dict[str, float] = {}
    if source_url is not None:
        _emit(progress, "Downloading source video from URL.")
        stage_start = time.monotonic()
        source_path, ingest_status = yt_dlp_adapter.download_video_from_url(
            source_url=source_url,
            output_dir=download_dir,
            job_id=job_id,
            progress=download_progress,
        )
        step_timings["download_source_sec"] = round(time.monotonic() - stage_start, 4)
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
    run_profile = str(analysis_config.get("run_profile") or "degraded").strip().lower()
    if run_profile not in {"strict", "degraded"}:
        run_profile = "degraded"
    fusion_cfg = analysis_config["fusion"]
    adapter_cfg = analysis_config["adapters"]
    quality_cfg = analysis_config["quality"]
    runtime_cfg = analysis_config["runtime"]

    resolved_diarize = (
        diarize
        if diarize is not None
        else bool(adapter_cfg["whisperx"].get("diarize", False))
    )
    resolved_overwrite_job_artifacts = (
        overwrite_job_artifacts
        if overwrite_job_artifacts is not None
        else bool(runtime_cfg.get("overwrite_job_artifacts", True))
    )
    resolved_prune_other_artifacts = (
        prune_other_artifacts
        if prune_other_artifacts is not None
        else bool(runtime_cfg.get("prune_other_artifacts", False))
    )
    resolved_keep_artifact_jobs = (
        int(keep_artifact_jobs)
        if keep_artifact_jobs is not None
        else int(runtime_cfg.get("keep_artifact_jobs", 1))
    )

    _emit(progress, "Running preflight capability checks.")
    ffmpeg_whisper_cfg = adapter_cfg.get("ffmpeg_whisper", {})
    subtitle_cfg = adapter_cfg.get("subtitle_bootstrap", {})
    preflight_capabilities = {
        "run_profile": run_profile,
        "ffmpeg_whisper_enabled": bool(ffmpeg_whisper_cfg.get("enabled", False)),
        "subtitle_bootstrap_enabled": bool(subtitle_cfg.get("enabled", False)),
        "strict_mode": run_profile == "strict",
        "expected_risks": [],
    }

    _emit(progress, "Probing source video metadata.")
    stage_start = time.monotonic()
    video_metadata = ffmpeg_adapter.probe_video(source_path)
    step_timings["probe_video_sec"] = round(time.monotonic() - stage_start, 4)
    ffmpeg_status = _adapter_available_status().model_copy(
        update={
            "version": ffmpeg_adapter.ffmpeg_version(),
            "config": {
                "probe": "ffprobe -show_streams -show_format",
            },
        }
    )

    _emit(progress, "Running scene boundary detector (PySceneDetect/fallback).")
    stage_start = time.monotonic()
    pyscene_boundaries, pyscene_status = pyscenedetect_adapter.detect_boundaries(
        source_path,
        fps=video_metadata.fps,
        threshold=float(adapter_cfg["pyscenedetect"]["threshold"]),
        min_scene_len_sec=float(adapter_cfg["pyscenedetect"]["min_scene_len_sec"]),
        ffmpeg_scene_threshold=float(
            adapter_cfg["pyscenedetect"]["ffmpeg_scene_threshold"]
        ),
    )
    step_timings["detect_pyscene_sec"] = round(time.monotonic() - stage_start, 4)
    _emit(progress, "Running shot boundary detector (TransNetV2 when available).")
    stage_start = time.monotonic()
    transnet_boundaries, transnet_status = transnetv2_adapter.detect_boundaries(
        source_path,
        threshold=float(adapter_cfg["transnetv2"]["threshold"]),
        min_gap_frames=int(adapter_cfg["transnetv2"]["min_gap_frames"]),
        model_dir=(
            str(adapter_cfg["transnetv2"].get("model_dir")).strip()
            if adapter_cfg["transnetv2"].get("model_dir") is not None
            else None
        ),
    )
    step_timings["detect_transnet_sec"] = round(time.monotonic() - stage_start, 4)

    candidate_frame_indices = [
        candidate.frame_index
        for candidate in [*pyscene_boundaries, *transnet_boundaries]
    ]
    _emit(
        progress,
        (
            "Computing local frame deltas and fusing detector boundaries "
            f"({len(candidate_frame_indices)} candidates)."
        ),
    )
    fusion_config = BoundaryFusionConfig(
        cluster_tolerance_frames=int(fusion_cfg["cluster_tolerance_frames"]),
        nms_window_frames=int(fusion_cfg["nms_window_frames"]),
    )
    stage_start = time.monotonic()
    local_scores = ffmpeg_adapter.local_frame_delta_scores(
        source_path,
        candidate_frame_indices,
        fps=video_metadata.fps,
    )
    _calibrate_pyscene_scores(
        pyscene_boundaries=pyscene_boundaries,
        transnet_boundaries=transnet_boundaries,
        local_scores=local_scores,
        tolerance_frames=fusion_config.cluster_tolerance_frames,
    )
    step_timings["compute_local_delta_sec"] = round(time.monotonic() - stage_start, 4)
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
    stage_start = time.monotonic()
    scenes = _build_scenes(
        boundaries=boundary_models,
        fps=video_metadata.fps,
        duration_sec=video_metadata.duration_sec,
        total_frames=video_metadata.total_frames,
    )
    step_timings["build_scenes_sec"] = round(time.monotonic() - stage_start, 4)

    _emit(progress, "Running speech analysis (ffmpeg whisper/WhisperX fallback).")
    stage_start = time.monotonic()
    configured_whisperx_language = adapter_cfg["whisperx"].get("language")
    resolved_whisperx_language = (
        str(configured_whisperx_language).strip()
        if configured_whisperx_language is not None
        else None
    )
    if resolved_whisperx_language == "":
        resolved_whisperx_language = None

    ffmpeg_whisper_cfg = adapter_cfg.get("ffmpeg_whisper", {})
    ffmpeg_whisper_enabled = bool(ffmpeg_whisper_cfg.get("enabled", False))
    ffmpeg_whisper_language = ffmpeg_whisper_cfg.get("language")
    if ffmpeg_whisper_language is None:
        ffmpeg_whisper_language = "auto"
    ffmpeg_whisper_language = str(ffmpeg_whisper_language).strip()
    if ffmpeg_whisper_language == "":
        ffmpeg_whisper_language = "auto"

    speech_segments: list[SpeechSegment] = []
    word_segments: list[WordSegment] = []
    openai_whisper_cfg = adapter_cfg.get("openai_whisper", {})
    openai_whisper_status = AdapterStatus(
        state=AdapterState.fallback,
        detail="Not used.",
        config=openai_whisper_cfg,
    )
    subtitle_status = AdapterStatus(
        state=AdapterState.fallback,
        detail="Subtitle bootstrap disabled.",
        config=subtitle_cfg,
    )
    if ffmpeg_whisper_enabled:
        _emit(progress, "Trying ffmpeg whisper filter.")
        ffmpeg_speech, ffmpeg_words, ffmpeg_whisper_status = (
            ffmpeg_whisper_adapter.transcribe(
                source_path,
                model_path=ffmpeg_whisper_cfg.get("model_path"),
                language=None
                if ffmpeg_whisper_language == "auto"
                else ffmpeg_whisper_language,
                queue=int(ffmpeg_whisper_cfg.get("queue", 10)),
                use_gpu=bool(ffmpeg_whisper_cfg.get("use_gpu", True)),
            )
        )
        if ffmpeg_whisper_status.state == AdapterState.available and ffmpeg_speech:
            speech_segments = ffmpeg_speech
            word_segments = ffmpeg_words
            whisperx_status = AdapterStatus(
                state=AdapterState.fallback,
                detail="Skipped because ffmpeg whisper succeeded.",
                config=adapter_cfg["whisperx"],
            )
        else:
            _emit(progress, "ffmpeg whisper unavailable/failed; falling back to WhisperX.")
            speech_segments, word_segments, whisperx_status = whisperx_adapter.transcribe(
                source_path,
                model_name=str(adapter_cfg["whisperx"]["model_name"]),
                language=resolved_whisperx_language,
                batch_size=int(adapter_cfg["whisperx"]["batch_size"]),
                diarize=resolved_diarize,
                timeout_sec=int(runtime_cfg.get("asr_timeout_sec", 900)),
                progress=speech_progress,
            )
    else:
        ffmpeg_whisper_status = AdapterStatus(
            state=AdapterState.fallback,
            detail="Disabled by config; using WhisperX.",
            config=ffmpeg_whisper_cfg,
        )
        speech_segments, word_segments, whisperx_status = whisperx_adapter.transcribe(
            source_path,
            model_name=str(adapter_cfg["whisperx"]["model_name"]),
            language=resolved_whisperx_language,
            batch_size=int(adapter_cfg["whisperx"]["batch_size"]),
            diarize=resolved_diarize,
            timeout_sec=int(runtime_cfg.get("asr_timeout_sec", 900)),
            progress=speech_progress,
        )

    if not speech_segments and bool(openai_whisper_cfg.get("enabled", True)):
        _emit(progress, "WhisperX empty/unavailable; falling back to openai-whisper.")
        speech_segments, word_segments, openai_whisper_status = openai_whisper_adapter.transcribe(
            source_path,
            model_name=str(openai_whisper_cfg.get("model_name") or "base"),
            language=resolved_whisperx_language,
        )

    if not speech_segments and bool(subtitle_cfg.get("enabled", False)):
        _emit(progress, "ASR empty; trying subtitle bootstrap (supplemental).")
        subtitle_segments, subtitle_status = subtitle_adapter.fetch_subtitle_segments(
            source_url=source_url,
            output_dir=download_dir,
            job_id=job_id,
            language=str(subtitle_cfg.get("language") or "en"),
        )
        min_required = int(subtitle_cfg.get("min_segments_for_use", 10))
        if len(subtitle_segments) >= min_required:
            speech_segments = subtitle_segments
            word_segments = []
            if whisperx_status.state == AdapterState.unavailable:
                whisperx_status = whisperx_status.model_copy(
                    update={
                        "state": AdapterState.fallback,
                        "detail": "WhisperX unavailable; using subtitle bootstrap.",
                    }
                )
    step_timings["speech_analysis_sec"] = round(time.monotonic() - stage_start, 4)

    speech_segments = _sanitize_speech_segments(
        speech_segments, duration_sec=video_metadata.duration_sec
    )
    word_segments = _sanitize_word_segments(
        word_segments, duration_sec=video_metadata.duration_sec
    )

    opennsfw_cfg = adapter_cfg["opennsfw2"]
    _emit(
        progress,
        "Running scene-aware sparse visual NSFW scan (OpenNSFW2 + dense fallback).",
    )
    stage_start = time.monotonic()
    scene_segments_payload = [
        {
            "start_frame": scene.start_frame,
            "end_frame": scene.end_frame,
            "start_sec": scene.start_sec,
            "end_sec": scene.end_sec,
        }
        for scene in scenes
    ]
    visual_flags, opennsfw_status = opennsfw2_adapter.score_full_video(
        source_path,
        fps=video_metadata.fps,
        duration_sec=video_metadata.duration_sec,
        visual_mode=str(opennsfw_cfg.get("mode") or "scene_aware_sparse"),
        scene_segments=scene_segments_payload,
        threshold=float(opennsfw_cfg["threshold"]),
        frame_interval=int(opennsfw_cfg.get("frame_interval", 8)),
        aggregation_size=int(opennsfw_cfg.get("aggregation_size", 1)),
        batch_size=int(opennsfw_cfg.get("batch_size", 8)),
        progress_bar=bool(opennsfw_cfg.get("progress_bar", False)),
        calibration_floor=float(opennsfw_cfg.get("calibration_floor", 0.18)),
        calibration_quantile=float(opennsfw_cfg.get("calibration_quantile", 0.995)),
        merge_gap_sec=float(opennsfw_cfg.get("merge_gap_sec", 1.0)),
        max_flags_per_minute=float(opennsfw_cfg.get("max_flags_per_minute", 18.0)),
        per_scene_max_frames=int(opennsfw_cfg.get("per_scene_max_frames", 4)),
        boundary_cluster_sec=float(opennsfw_cfg.get("boundary_cluster_sec", 0.4)),
        long_scene_stride_sec=float(opennsfw_cfg.get("long_scene_stride_sec", 2.0)),
        suspicious_score_ratio=float(opennsfw_cfg.get("suspicious_score_ratio", 0.75)),
        dense_window_sec=float(opennsfw_cfg.get("dense_window_sec", 1.5)),
        dense_frame_interval=int(opennsfw_cfg.get("dense_frame_interval", 1)),
        max_dense_windows=int(opennsfw_cfg.get("max_dense_windows", 16)),
        timeout_sec=int(runtime_cfg.get("visual_timeout_sec", 1800)),
        progress=(lambda message: _emit(progress, message)),
        progress_interval_sec=float(
            runtime_cfg.get("visual_progress_interval_sec", 15.0)
        ),
        omp_threads=(
            int(runtime_cfg["visual_omp_threads"])
            if runtime_cfg.get("visual_omp_threads") is not None
            else None
        ),
        tf_interop_threads=(
            int(runtime_cfg["visual_tf_interop_threads"])
            if runtime_cfg.get("visual_tf_interop_threads") is not None
            else None
        ),
        tf_intraop_threads=(
            int(runtime_cfg["visual_tf_intraop_threads"])
            if runtime_cfg.get("visual_tf_intraop_threads") is not None
            else None
        ),
    )
    step_timings["visual_scoring_sec"] = round(time.monotonic() - stage_start, 4)

    _emit(progress, "Building rating evidence and writing artifact.")
    stage_start = time.monotonic()
    rating_evidence = _build_rating_evidence(
        speech_segments=speech_segments,
        word_segments=word_segments,
        visual_flags=visual_flags,
    )
    safe_cut_points, edit_context_windows, continuity_features = _build_edit_ready_features(
        fps=video_metadata.fps,
        duration_sec=video_metadata.duration_sec,
        rating_evidence=rating_evidence,
        boundaries=boundary_models,
        local_scores=local_scores,
        speech_segments=speech_segments,
    )
    step_timings["build_evidence_sec"] = round(time.monotonic() - stage_start, 4)

    asr_mode = _determine_asr_mode(
        speech_segments=speech_segments,
        whisperx_status=whisperx_status,
        ffmpeg_whisper_status=ffmpeg_whisper_status,
        openai_whisper_status=openai_whisper_status,
    )
    visual_mode = _determine_visual_mode(opennsfw_status)
    detector_coverage = (
        sum(
            1
            for status in [pyscene_status, transnet_status]
            if status.state == AdapterState.available
        )
        / 2.0
    )
    fused_scores = [boundary.fused_score for boundary in boundary_models]
    low_conf_threshold = float(quality_cfg.get("low_confidence_threshold", 0.2))
    low_conf_ratio = (
        sum(1 for score in fused_scores if score < low_conf_threshold) / max(1, len(fused_scores))
    )
    boundary_quality = {
        "detector_coverage": round(detector_coverage, 6),
        "score_entropy": round(_score_entropy(fused_scores), 6),
        "low_confidence_ratio": round(low_conf_ratio, 6),
        "local_delta_all_zero": bool(local_scores) and all(
            score == 0.0 for score in local_scores.values()
        ),
        "cut_density_per_min": round(
            len(boundary_models) / max(1.0, video_metadata.duration_sec / 60.0), 6
        ),
    }
    quality_flags: list[str] = []
    if boundary_quality["local_delta_all_zero"]:
        quality_flags.append("local_delta_all_zero")
    if detector_coverage < 1.0:
        quality_flags.append("single_detector_only")
    if visual_mode == "disabled":
        quality_flags.append("visual_mode_disabled")
    elif not visual_flags:
        quality_flags.append("visual_zero_flags")
    if asr_mode != "full":
        quality_flags.append(f"asr_mode_{asr_mode}")

    if detector_coverage < 1.0:
        preflight_capabilities["expected_risks"].append("single_detector_fusion")
    if visual_mode == "disabled":
        preflight_capabilities["expected_risks"].append("visual_under_instrumented")
    elif not visual_flags:
        preflight_capabilities["expected_risks"].append("visual_zero_flags")
    if asr_mode != "full":
        preflight_capabilities["expected_risks"].append("asr_under_instrumented")

    quality_report = _build_quality_report(
        job_id=job_id,
        run_profile=run_profile,
        duration_sec=video_metadata.duration_sec,
        rating_evidence=rating_evidence,
        boundary_models=boundary_models,
        local_scores=local_scores,
        asr_mode=asr_mode,
        visual_mode=visual_mode,
        transnet_status=transnet_status,
        opennsfw_status=opennsfw_status,
        quality_cfg=quality_cfg,
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
            "ffmpeg_whisper": ffmpeg_whisper_status.config,
            "whisperx": whisperx_status.config,
            "openai_whisper": openai_whisper_status.config,
            "subtitle_bootstrap": subtitle_status.config,
            "opennsfw2": opennsfw_status.config,
            "source_ingest": ingest_status.config,
        },
        adapter_status={
            "source_ingest": ingest_status,
            "ffmpeg": ffmpeg_status,
            "pyscenedetect": pyscene_status,
            "transnetv2": transnet_status,
            "ffmpeg_whisper": ffmpeg_whisper_status,
            "whisperx": whisperx_status,
            "openai_whisper": openai_whisper_status,
            "subtitle_bootstrap": subtitle_status,
            "opennsfw2": opennsfw_status,
        },
        fusion={
            "candidate_count": len(pyscene_boundaries) + len(transnet_boundaries),
            "canonical_boundary_count": len(boundary_models),
            "cluster_tolerance_frames": fusion_config.cluster_tolerance_frames,
            "nms_window_frames": fusion_config.nms_window_frames,
        },
        run_profile=run_profile,
        asr_mode=asr_mode,
        visual_mode=visual_mode,
        quality_flags=quality_flags,
        step_timings=step_timings,
        boundary_quality=boundary_quality,
        capability_matrix=preflight_capabilities,
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
        safe_cut_points=safe_cut_points,
        edit_context_windows=edit_context_windows,
        continuity_features=continuity_features,
        boundaries=boundary_models,
        metadata=metadata,
    )

    output_dir = Path(artifacts_root) / job_id
    _prepare_output_dir(output_dir, overwrite=resolved_overwrite_job_artifacts)
    output_path = output_dir / "analysis_timeline.json"
    output_path.write_text(
        json.dumps(timeline.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    quality_report_path = output_dir / "analysis_quality_report.json"
    quality_report_path.write_text(
        json.dumps(quality_report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    _emit(
        progress,
        (
            "Quality report written: "
            f"passed={quality_report.passed} "
            f"critical={len(quality_report.critical_findings)} "
            f"warnings={len(quality_report.warnings)}"
        ),
    )
    if resolved_prune_other_artifacts:
        pruned = _prune_old_artifact_dirs(
            Path(artifacts_root),
            keep_job_id=job_id,
            keep_count=resolved_keep_artifact_jobs,
        )
        if pruned:
            _emit(
                progress,
                f"Pruned old artifact folders: {', '.join(pruned)}",
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
        help="Working directory for transient analysis files.",
    )
    parser.add_argument(
        "--download-dir",
        default="data/inbox",
        help="Download destination directory when --url is used.",
    )
    parser.add_argument(
        "--overwrite-job-artifacts",
        action="store_true",
        help="Overwrite the current job artifact folder before writing outputs.",
    )
    parser.add_argument(
        "--prune-other-artifacts",
        action="store_true",
        help="Prune older artifact job folders after a successful run.",
    )
    parser.add_argument(
        "--keep-artifact-jobs",
        type=int,
        default=None,
        help="When pruning, keep at most this many artifact job folders (including current).",
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
            if message.startswith("Visual scan "):
                print(f"  [visual] {message}", flush=True)
                return
            self.step += 1
            print(f"[step {self.step:02d}] {message}", flush=True)

    def _download_detail(message: str) -> None:
        print(f"  [download] {message}", flush=True)

    def _speech_detail(message: str) -> None:
        print(f"  [speech] {message}", flush=True)

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
        diarize=args.diarize if args.diarize else None,
        overwrite_job_artifacts=(
            True if args.overwrite_job_artifacts else None
        ),
        prune_other_artifacts=(
            True if args.prune_other_artifacts else None
        ),
        keep_artifact_jobs=args.keep_artifact_jobs,
        config_path=args.config,
        progress=step_printer,
        download_progress=_download_detail,
        speech_progress=_speech_detail,
    )
    step_printer("Analysis completed.")
    print(f"analysis_timeline: {output_path}")
    print(f"analysis_quality_report: {output_path.parent / 'analysis_quality_report.json'}")
    print(f"duration_sec: {timeline.duration_sec}")
    print(f"fps: {timeline.fps}")
    print(f"scene_count: {len(timeline.scenes)}")


if __name__ == "__main__":
    main()
