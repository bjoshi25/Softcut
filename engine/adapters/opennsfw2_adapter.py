"""OpenNSFW2 adapter for visual risk scoring."""

from __future__ import annotations

import bisect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from engine.schemas.timeline import AdapterState, AdapterStatus, VisualFlag

ProgressCallback = Callable[[str], None]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _to_float(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        return _to_float(value[-1])
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return _to_float(converted)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def _quantile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    q = max(0.0, min(1.0, float(percentile)))
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]

    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {
            "scanned_frames": 0,
            "min_score": 0.0,
            "max_score": 0.0,
            "mean_score": 0.0,
            "p90_score": 0.0,
            "p95_score": 0.0,
            "p99_score": 0.0,
        }

    ordered = sorted(scores)
    return {
        "scanned_frames": len(scores),
        "min_score": round(ordered[0], 6),
        "max_score": round(ordered[-1], 6),
        "mean_score": round(sum(scores) / len(scores), 6),
        "p90_score": round(_quantile(ordered, 0.90), 6),
        "p95_score": round(_quantile(ordered, 0.95), 6),
        "p99_score": round(_quantile(ordered, 0.99), 6),
    }


def _resolve_active_threshold(
    scores: list[float],
    *,
    configured_threshold: float,
    calibration_floor: float,
    calibration_quantile: float,
) -> tuple[float, bool, str]:
    threshold = _clamp_probability(float(configured_threshold))
    floor = _clamp_probability(float(calibration_floor))
    if not scores:
        return threshold, False, "no_scores_returned"

    max_score = max(scores)
    if max_score >= threshold:
        return threshold, False, "configured_threshold_met"
    if max_score < floor:
        return threshold, False, "max_score_below_calibration_floor"

    quantile_score = _quantile(sorted(scores), calibration_quantile)
    active_threshold = max(floor, min(threshold, quantile_score))
    return active_threshold, True, "calibrated_to_score_distribution"


def _normalize_elapsed_seconds(
    elapsed_seconds: list[Any],
    *,
    score_count: int,
    fps: float,
) -> list[float]:
    if len(elapsed_seconds) >= score_count:
        return [max(0.0, _to_float(value)) for value in elapsed_seconds[:score_count]]

    safe_fps = fps if fps > 0 else 1.0
    return [index / safe_fps for index in range(score_count)]


def _limit_evenly(values: list[int], *, max_count: int) -> list[int]:
    if max_count <= 0:
        return []
    if len(values) <= max_count:
        return values
    if max_count == 1:
        return [values[0]]
    last_index = len(values) - 1
    kept_indices = {
        int(round((slot / (max_count - 1)) * last_index)) for slot in range(max_count)
    }
    return [values[index] for index in sorted(kept_indices)]


def _scene_representative_frame_indices(
    scene_segments: list[dict[str, Any]],
    *,
    fps: float,
    total_frames: int,
    per_scene_max_frames: int,
    boundary_cluster_sec: float,
    long_scene_stride_sec: float,
) -> list[int]:
    if not scene_segments:
        return []

    safe_fps = fps if fps > 0 else 1.0
    boundary_cluster_frames = max(1, int(round(max(0.0, boundary_cluster_sec) * safe_fps)))
    stride_frames = int(round(max(0.0, long_scene_stride_sec) * safe_fps))
    selected: list[int] = []
    last_frame = max(0, total_frames - 1)

    for raw_scene in scene_segments:
        start_frame = raw_scene.get("start_frame")
        end_frame = raw_scene.get("end_frame")
        if start_frame is None:
            start_frame = int(round(max(0.0, _to_float(raw_scene.get("start_sec"))) * safe_fps))
        if end_frame is None:
            end_frame = int(round(max(0.0, _to_float(raw_scene.get("end_sec"))) * safe_fps))
        start = max(0, min(int(start_frame), last_frame))
        end = max(start, min(int(end_frame), last_frame))
        midpoint = start + ((end - start) // 2)

        scene_candidates = {
            start,
            min(end, start + boundary_cluster_frames),
            midpoint,
            max(start, end - boundary_cluster_frames),
            end,
        }
        if stride_frames > 0 and (end - start) > stride_frames:
            cursor = start + stride_frames
            while cursor < end:
                scene_candidates.add(cursor)
                cursor += stride_frames

        scene_frames = _limit_evenly(
            sorted(scene_candidates),
            max_count=max(1, int(per_scene_max_frames)),
        )
        selected.extend(scene_frames)

    return sorted({max(0, min(last_frame, int(frame))) for frame in selected})


def _dense_windows_from_scores(
    elapsed_seconds: list[float],
    scores: list[float],
    *,
    threshold: float,
    radius_sec: float,
    max_windows: int,
    duration_sec: float,
) -> list[tuple[float, float]]:
    if not elapsed_seconds or not scores or max_windows <= 0:
        return []

    candidates = [
        (max(0.0, float(sec)), _clamp_probability(float(score)))
        for sec, score in zip(elapsed_seconds, scores, strict=False)
        if _clamp_probability(float(score)) >= _clamp_probability(float(threshold))
    ]
    if not candidates:
        return []

    candidates.sort(key=lambda item: item[1], reverse=True)
    centers: list[float] = []
    safe_radius = max(0.0, float(radius_sec))
    for sec, _score in candidates:
        if any(abs(sec - center) <= safe_radius for center in centers):
            continue
        centers.append(sec)
        if len(centers) >= max_windows:
            break

    if not centers:
        return []
    centers.sort()
    safe_duration = max(0.0, float(duration_sec))
    windows: list[tuple[float, float]] = []
    for center in centers:
        start = max(0.0, center - safe_radius)
        end = min(safe_duration, center + safe_radius)
        if end < start:
            end = start
        if not windows or start > windows[-1][1]:
            windows.append((start, end))
            continue
        windows[-1] = (windows[-1][0], max(windows[-1][1], end))
    return windows


def _frame_indices_from_windows(
    windows: list[tuple[float, float]],
    *,
    fps: float,
    total_frames: int,
    frame_step: int,
) -> list[int]:
    if not windows or total_frames <= 0:
        return []
    safe_fps = fps if fps > 0 else 1.0
    safe_step = max(1, int(frame_step))
    last_frame = max(0, total_frames - 1)
    output: list[int] = []
    for start_sec, end_sec in windows:
        start_frame = max(0, min(last_frame, int(math.floor(max(0.0, start_sec) * safe_fps))))
        end_frame = max(
            start_frame,
            min(last_frame, int(math.ceil(max(0.0, end_sec) * safe_fps))),
        )
        output.extend(range(start_frame, end_frame + 1, safe_step))
    return sorted(set(output))


def _merge_windows(
    windows: list[tuple[float, float]],
    *,
    duration_sec: float,
) -> list[tuple[float, float]]:
    if not windows:
        return []
    safe_duration = max(0.0, float(duration_sec))
    normalized = []
    for start, end in windows:
        s = max(0.0, min(safe_duration, float(start)))
        e = max(s, min(safe_duration, float(end)))
        normalized.append((s, e))
    normalized.sort(key=lambda item: item[0])
    merged: list[tuple[float, float]] = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
            continue
        merged.append((start, end))
    return merged


def _windows_from_frame_indices(
    frame_indices: list[int],
    *,
    fps: float,
    radius_sec: float,
    duration_sec: float,
    max_windows: int,
) -> list[tuple[float, float]]:
    if not frame_indices or max_windows <= 0:
        return []
    safe_fps = fps if fps > 0 else 1.0
    selected = _limit_evenly(
        sorted(set(int(max(0, frame)) for frame in frame_indices)),
        max_count=max(1, int(max_windows)),
    )
    safe_radius = max(0.02, float(radius_sec))
    raw_windows = []
    for frame in selected:
        center = frame / safe_fps
        raw_windows.append((center - safe_radius, center + safe_radius))
    return _merge_windows(raw_windows, duration_sec=duration_sec)


def _scene_sampling_coverage(
    *,
    scene_segments: list[dict[str, Any]],
    sampled_seconds: list[float],
    dense_windows: list[tuple[float, float]],
    fps: float,
) -> dict[str, Any]:
    """Summarize scene-level sparse coverage and dense escalations."""
    total_scenes = len(scene_segments)
    baseline = {
        "total_scenes": total_scenes,
        "sampled_scenes": 0,
        "sampled_scene_ratio": 0.0,
        "avg_frames_sampled_per_scene": 0.0,
        "escalated_scenes": 0,
        "escalated_scene_ratio": 0.0,
        "dense_rescans": len(dense_windows),
    }
    if total_scenes <= 0:
        return baseline

    safe_fps = fps if fps > 0 else 1.0
    sampled_frames = sorted(
        {max(0, int(round(max(0.0, float(sec)) * safe_fps))) for sec in sampled_seconds}
    )
    dense_window_frames = [
        (
            max(0, int(math.floor(max(0.0, float(start)) * safe_fps))),
            max(0, int(math.ceil(max(0.0, float(end)) * safe_fps))),
        )
        for start, end in dense_windows
    ]

    sampled_scene_count = 0
    escalated_scene_count = 0
    sampled_frame_total = 0
    for raw_scene in scene_segments:
        start_frame = raw_scene.get("start_frame")
        end_frame = raw_scene.get("end_frame")
        if start_frame is None:
            start_frame = int(round(max(0.0, _to_float(raw_scene.get("start_sec"))) * safe_fps))
        if end_frame is None:
            end_frame = int(round(max(0.0, _to_float(raw_scene.get("end_sec"))) * safe_fps))
        start = max(0, int(start_frame))
        end = max(start, int(end_frame))

        left = bisect.bisect_left(sampled_frames, start)
        right = bisect.bisect_right(sampled_frames, end)
        scene_sample_count = max(0, right - left)
        sampled_frame_total += scene_sample_count
        if scene_sample_count > 0:
            sampled_scene_count += 1

        if any(
            not (window_end < start or window_start > end)
            for window_start, window_end in dense_window_frames
        ):
            escalated_scene_count += 1

    sampled_ratio = sampled_scene_count / max(1, total_scenes)
    escalated_ratio = escalated_scene_count / max(1, total_scenes)
    baseline.update(
        {
            "sampled_scenes": sampled_scene_count,
            "sampled_scene_ratio": round(sampled_ratio, 6),
            "avg_frames_sampled_per_scene": round(sampled_frame_total / max(1, total_scenes), 6),
            "escalated_scenes": escalated_scene_count,
            "escalated_scene_ratio": round(escalated_ratio, 6),
        }
    )
    return baseline


def _extract_temporal_clip(
    video_path: str | Path,
    *,
    start_sec: float,
    end_sec: float,
    output_path: Path,
    target_fps: float | None = None,
) -> tuple[bool, str | None]:
    start = max(0.0, float(start_sec))
    end = max(start + 0.05, float(end_sec))
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.6f}",
        "-to",
        f"{end:.6f}",
        "-i",
        str(video_path),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "35",
        "-pix_fmt",
        "yuv420p",
    ]
    if target_fps is not None and float(target_fps) > 0:
        command.extend(["-vf", f"fps={max(0.1, float(target_fps)):.6f}"])
    command.append(str(output_path))
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (
            (result.stderr or result.stdout or "ffmpeg_temporal_extract_failed")
            .strip()
            .splitlines()
        )
        return False, detail[-1] if detail else "ffmpeg_temporal_extract_failed"
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return False, "empty_temporal_clip"
    return True, None


def _score_temporal_windows(
    opennsfw2: Any,
    video_path: str | Path,
    *,
    windows: list[tuple[float, float]],
    fps: float,
    duration_sec: float,
    frame_interval: int,
    aggregation_size: int,
    batch_size: int,
    progress_bar: bool,
    target_fps: float | None,
    clip_prefix: str,
) -> tuple[list[float], list[float], dict[str, Any]]:
    if not windows:
        return [], [], {
            "requested_window_count": 0,
            "window_failures": 0,
            "requested_frame_count": 0,
            "scored_frame_count": 0,
            "clip_extract_failed": False,
        }

    safe_fps = fps if fps > 0 else 1.0
    safe_duration = max(0.0, float(duration_sec))
    merged_windows = _merge_windows(windows, duration_sec=safe_duration)
    guessed_fps = float(target_fps) if target_fps is not None else (safe_fps / max(1, int(frame_interval)))
    guessed_fps = max(0.1, guessed_fps)
    requested_frames = int(
        sum(max(1.0, (end - start) * guessed_fps) for start, end in merged_windows)
    )

    all_times: list[float] = []
    all_scores: list[float] = []
    failures = 0
    last_error: str | None = None
    for index, (start, end) in enumerate(merged_windows):
        with tempfile.TemporaryDirectory(prefix=f"{clip_prefix}_{index:04d}_") as temp_dir:
            window_clip_path = Path(temp_dir) / "window.mp4"
            ok, error = _extract_temporal_clip(
                video_path,
                start_sec=start,
                end_sec=end,
                output_path=window_clip_path,
                target_fps=target_fps,
            )
            if not ok:
                failures += 1
                last_error = error
                continue
            elapsed_seconds, scores = _predict_video_scores(
                opennsfw2,
                window_clip_path,
                frame_interval=max(1, int(frame_interval)),
                aggregation_size=max(1, int(aggregation_size)),
                batch_size=max(1, int(batch_size)),
                progress_bar=progress_bar,
            )
            if not scores:
                continue
            normalized_elapsed = _normalize_elapsed_seconds(
                elapsed_seconds,
                score_count=len(scores),
                fps=guessed_fps,
            )
            all_times.extend(
                min(safe_duration, max(0.0, start + float(sec)))
                for sec in normalized_elapsed
            )
            all_scores.extend(scores)

    diagnostics = {
        "requested_window_count": len(merged_windows),
        "window_failures": failures,
        "requested_frame_count": requested_frames,
        "scored_frame_count": len(all_scores),
        "clip_extract_failed": failures > 0 and not all_scores,
        "partial_clip_extract_failures": failures > 0 and bool(all_scores),
    }
    if last_error:
        diagnostics["clip_extract_error"] = last_error
    return all_times, all_scores, diagnostics


def _select_expression_for_frames(frame_indices: list[int]) -> str:
    return "+".join(f"eq(n\\,{int(frame)})" for frame in frame_indices)


def _extract_selected_frames_clip(
    video_path: str | Path,
    *,
    frame_indices: list[int],
    output_path: Path,
) -> tuple[bool, str | None]:
    if not frame_indices:
        return False, "no_frame_indices"
    select_expr = _select_expression_for_frames(frame_indices)
    if not select_expr:
        return False, "empty_select_expression"

    filter_graph = f"select='{select_expr}',setpts=N/FRAME_RATE/TB"

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-an",
        "-vsync",
        "vfr",
        str(output_path),
    ]
    filter_script_path: Path | None = None
    if len(filter_graph) > 4000:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ffscript",
            prefix="softcut_opennsfw2_select_",
            delete=False,
        ) as filter_script:
            filter_script.write(filter_graph)
            filter_script_path = Path(filter_script.name)
        command[8:8] = ["-filter_script:v", str(filter_script_path)]
    else:
        command[8:8] = ["-vf", filter_graph]

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if filter_script_path is not None:
        filter_script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = (
            (result.stderr or result.stdout or "ffmpeg_extract_failed")
            .strip()
            .splitlines()
        )
        return False, detail[-1] if detail else "ffmpeg_extract_failed"
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return False, "empty_extracted_clip"
    return True, None


def _predict_video_scores(
    opennsfw2: Any,
    video_path: str | Path,
    *,
    frame_interval: int,
    aggregation_size: int,
    batch_size: int,
    progress_bar: bool,
) -> tuple[list[Any], list[float]]:
    elapsed_seconds, raw_scores = opennsfw2.predict_video_frames(
        str(video_path),
        frame_interval=max(1, int(frame_interval)),
        aggregation_size=max(1, int(aggregation_size)),
        batch_size=max(1, int(batch_size)),
        progress_bar=bool(progress_bar),
    )
    return list(elapsed_seconds), [
        _clamp_probability(_to_float(score)) for score in list(raw_scores)
    ]


def _score_selected_frames(
    opennsfw2: Any,
    video_path: str | Path,
    *,
    frame_indices: list[int],
    fps: float,
    batch_size: int,
    progress_bar: bool,
    clip_prefix: str,
) -> tuple[list[float], list[float], dict[str, Any]]:
    if not frame_indices:
        return [], [], {"requested_frame_count": 0, "scored_frame_count": 0}

    safe_fps = fps if fps > 0 else 1.0
    with tempfile.TemporaryDirectory(prefix=f"{clip_prefix}_") as temp_dir:
        sampled_clip_path = Path(temp_dir) / "sampled_frames.mp4"
        extracted, extract_error = _extract_selected_frames_clip(
            video_path,
            frame_indices=frame_indices,
            output_path=sampled_clip_path,
        )
        if not extracted:
            diagnostics = {
                "requested_frame_count": len(frame_indices),
                "scored_frame_count": 0,
                "clip_extract_failed": True,
                "clip_extract_error": extract_error,
            }
            # Recovery path for parser/command limits: split into smaller chunks.
            if len(frame_indices) <= 20:
                return [], [], diagnostics

            merged_seconds: list[float] = []
            merged_scores: list[float] = []
            chunk_failures = 0
            if len(frame_indices) <= 120:
                chunk_size = max(20, len(frame_indices) // 2)
            else:
                chunk_size = 120
            for start in range(0, len(frame_indices), chunk_size):
                chunk = frame_indices[start : start + chunk_size]
                chunk_seconds, chunk_scores, chunk_diag = _score_selected_frames(
                    opennsfw2,
                    video_path,
                    frame_indices=chunk,
                    fps=fps,
                    batch_size=batch_size,
                    progress_bar=progress_bar,
                    clip_prefix=f"{clip_prefix}_chunk",
                )
                if not chunk_scores:
                    chunk_failures += 1
                    continue
                merged_seconds.extend(chunk_seconds)
                merged_scores.extend(chunk_scores)
                if chunk_diag.get("clip_extract_failed"):
                    chunk_failures += 1
            if not merged_scores:
                diagnostics["chunk_recovery_attempted"] = True
                diagnostics["chunk_recovery_failures"] = chunk_failures
                return [], [], diagnostics
            ordered = sorted(
                zip(merged_seconds, merged_scores, strict=False),
                key=lambda item: item[0],
            )
            diagnostics.update(
                {
                    "chunk_recovery_attempted": True,
                    "chunk_recovery_failures": chunk_failures,
                    "scored_frame_count": len(ordered),
                    "clip_extract_failed": False,
                }
            )
            return (
                [item[0] for item in ordered],
                [item[1] for item in ordered],
                diagnostics,
            )

        _elapsed, scores = _predict_video_scores(
            opennsfw2,
            sampled_clip_path,
            frame_interval=1,
            aggregation_size=1,
            batch_size=batch_size,
            progress_bar=progress_bar,
        )
        scored_count = min(len(frame_indices), len(scores))
        mapped_scores = scores[:scored_count]
        mapped_seconds = [frame_indices[index] / safe_fps for index in range(scored_count)]
        return mapped_seconds, mapped_scores, {
            "requested_frame_count": len(frame_indices),
            "scored_frame_count": scored_count,
        }


def _merge_points_by_frame(
    elapsed_seconds: list[float],
    scores: list[float],
    *,
    fps: float,
) -> tuple[list[float], list[float]]:
    safe_fps = fps if fps > 0 else 1.0
    points_by_frame: dict[int, float] = {}
    for sec, score in zip(elapsed_seconds, scores, strict=False):
        frame_index = max(0, int(round(max(0.0, float(sec)) * safe_fps)))
        clamped = _clamp_probability(float(score))
        previous = points_by_frame.get(frame_index)
        if previous is None or clamped > previous:
            points_by_frame[frame_index] = clamped

    ordered = sorted(points_by_frame.items(), key=lambda item: item[0])
    merged_seconds = [frame_index / safe_fps for frame_index, _ in ordered]
    merged_scores = [score for _, score in ordered]
    return merged_seconds, merged_scores


def _score_scene_aware_sparse(
    opennsfw2: Any,
    video_path: str | Path,
    *,
    fps: float,
    duration_sec: float,
    scene_segments: list[dict[str, Any]],
    threshold: float,
    calibration_floor: float,
    frame_interval: int,
    aggregation_size: int,
    batch_size: int,
    progress_bar: bool,
    per_scene_max_frames: int,
    max_coarse_frames: int,
    boundary_cluster_sec: float,
    long_scene_stride_sec: float,
    suspicious_score_ratio: float,
    dense_window_sec: float,
    dense_frame_interval: int,
    max_dense_windows: int,
) -> tuple[list[float], list[float], dict[str, Any]]:
    safe_fps = fps if fps > 0 else 1.0
    safe_duration = max(0.01, float(duration_sec))
    total_frames = max(1, int(math.ceil(safe_duration * safe_fps)))
    configured_interval = max(1, int(frame_interval))
    coarse_interval = configured_interval
    if int(max_coarse_frames) > 0:
        coarse_interval = max(
            coarse_interval,
            int(math.ceil(total_frames / max(1, int(max_coarse_frames)))),
        )
    target_coarse_fps = safe_fps / max(1, coarse_interval)
    expected_coarse_frames = max(1, int(round(safe_duration * target_coarse_fps)))
    coarse_seconds, coarse_scores, coarse_diag = _score_temporal_windows(
        opennsfw2,
        video_path,
        windows=[(0.0, safe_duration)],
        fps=safe_fps,
        duration_sec=safe_duration,
        frame_interval=1,
        aggregation_size=1,
        batch_size=batch_size,
        progress_bar=progress_bar,
        target_fps=target_coarse_fps,
        clip_prefix="softcut_opennsfw2_coarse_window",
    )
    strategy_config: dict[str, Any] = {
        "coarse_interval": coarse_interval,
        "coarse_global_frame_count": expected_coarse_frames,
        "coarse_scene_frame_count": 0,
        "coarse_total_frame_count": expected_coarse_frames,
        "coarse_frame_count_capped": coarse_interval > configured_interval,
        "max_coarse_frames": max(1, int(max_coarse_frames)),
        "target_coarse_fps": round(target_coarse_fps, 6),
        "coarse_scored_frame_count": len(coarse_scores),
        "dense_window_count": 0,
        "dense_frame_count": 0,
        **{f"coarse_{key}": value for key, value in coarse_diag.items()},
    }

    fallback_global_interval = False
    if not coarse_scores:
        elapsed_seconds, fallback_scores = _predict_video_scores(
            opennsfw2,
            video_path,
            frame_interval=coarse_interval,
            aggregation_size=max(1, int(aggregation_size)),
            batch_size=batch_size,
            progress_bar=progress_bar,
        )
        normalized = _normalize_elapsed_seconds(
            elapsed_seconds,
            score_count=len(fallback_scores),
            fps=safe_fps,
        )
        strategy_config["coarse_clip_fallback"] = "global_interval"
        strategy_config["coarse_scored_frame_count"] = len(fallback_scores)
        strategy_config["coarse_fallback_interval"] = coarse_interval
        coarse_seconds = normalized
        coarse_scores = fallback_scores
        fallback_global_interval = True

    if not coarse_scores:
        return [], [], strategy_config
    requested = max(1, int(strategy_config.get("coarse_total_frame_count", len(coarse_scores))))
    strategy_config["coarse_score_coverage_ratio"] = round(
        len(coarse_scores) / requested,
        6,
    )

    # Add scene-representative micro-windows not already covered by coarse points.
    if not fallback_global_interval and scene_segments:
        rep_frames = _scene_representative_frame_indices(
            scene_segments,
            fps=safe_fps,
            total_frames=total_frames,
            per_scene_max_frames=max(1, int(per_scene_max_frames)),
            boundary_cluster_sec=boundary_cluster_sec,
            long_scene_stride_sec=long_scene_stride_sec,
        )
        coarse_hit_frames = {max(0, int(round(sec * safe_fps))) for sec in coarse_seconds}
        coverage_tolerance = max(1, coarse_interval // 2)

        def _is_covered(frame_index: int) -> bool:
            return any(
                (frame_index + delta) in coarse_hit_frames
                for delta in range(-coverage_tolerance, coverage_tolerance + 1)
            )

        uncovered = [frame for frame in rep_frames if not _is_covered(frame)]
        max_extra_windows = min(
            max(8, int(max(1, int(max_coarse_frames)) // 5)),
            48,
        )
        extra_windows = _windows_from_frame_indices(
            uncovered,
            fps=safe_fps,
            radius_sec=max(0.08, float(boundary_cluster_sec) * 0.5),
            duration_sec=safe_duration,
            max_windows=max_extra_windows,
        )
        strategy_config["coarse_scene_frame_count"] = len(rep_frames)
        strategy_config["coarse_uncovered_scene_frame_count"] = len(uncovered)
        strategy_config["coarse_scene_window_count"] = len(extra_windows)
        if extra_windows:
            extra_seconds, extra_scores, extra_diag = _score_temporal_windows(
                opennsfw2,
                video_path,
                windows=extra_windows,
                fps=safe_fps,
                duration_sec=safe_duration,
                frame_interval=1,
                aggregation_size=1,
                batch_size=batch_size,
                progress_bar=progress_bar,
                target_fps=None,
                clip_prefix="softcut_opennsfw2_scene_window",
            )
            strategy_config.update({f"coarse_scene_{key}": value for key, value in extra_diag.items()})
            if extra_scores:
                coarse_seconds, coarse_scores = _merge_points_by_frame(
                    [*coarse_seconds, *extra_seconds],
                    [*coarse_scores, *extra_scores],
                    fps=safe_fps,
                )
                strategy_config["coarse_scored_frame_count"] = len(coarse_scores)

    suspicion_threshold = max(
        _clamp_probability(float(calibration_floor)),
        _clamp_probability(float(threshold)) * _clamp_probability(float(suspicious_score_ratio)),
    )
    dense_windows = _dense_windows_from_scores(
        coarse_seconds,
        coarse_scores,
        threshold=suspicion_threshold,
        radius_sec=max(0.1, float(dense_window_sec)),
        max_windows=max(0, int(max_dense_windows)),
        duration_sec=max(0.0, float(duration_sec)),
    )
    strategy_config["suspicion_threshold"] = round(suspicion_threshold, 6)
    strategy_config["dense_window_count"] = len(dense_windows)
    strategy_config["dense_window_sec"] = round(max(0.1, float(dense_window_sec)), 6)
    if int(max_dense_windows) <= 0:
        strategy_config["dense_skipped_reason"] = "disabled_by_config"
    if fallback_global_interval:
        strategy_config["dense_skipped_reason"] = "coarse_fallback_global_interval"

    dense_seconds: list[float] = []
    dense_scores: list[float] = []
    if dense_windows and not fallback_global_interval:
        dense_seconds, dense_scores, dense_diag = _score_temporal_windows(
            opennsfw2,
            video_path,
            windows=dense_windows,
            fps=safe_fps,
            duration_sec=safe_duration,
            frame_interval=max(1, int(dense_frame_interval)),
            aggregation_size=1,
            batch_size=batch_size,
            progress_bar=progress_bar,
            target_fps=None,
            clip_prefix="softcut_opennsfw2_dense_window",
        )
        strategy_config["dense_frame_count"] = int(dense_diag.get("requested_frame_count", 0) or 0)
        strategy_config["dense_scored_frame_count"] = len(dense_scores)
        strategy_config.update({f"dense_{key}": value for key, value in dense_diag.items()})

    merged_seconds, merged_scores = _merge_points_by_frame(
        [*coarse_seconds, *dense_seconds],
        [*coarse_scores, *dense_scores],
        fps=safe_fps,
    )
    strategy_config["coverage_summary"] = _scene_sampling_coverage(
        scene_segments=scene_segments,
        sampled_seconds=merged_seconds,
        dense_windows=dense_windows,
        fps=safe_fps,
    )
    strategy_config["merged_scored_frame_count"] = len(merged_scores)
    return merged_seconds, merged_scores, strategy_config


def _visual_flags_from_frame_scores(
    elapsed_seconds: list[Any],
    raw_scores: list[Any],
    *,
    fps: float,
    threshold: float,
    calibration_floor: float,
    calibration_quantile: float,
    merge_gap_sec: float,
    max_flags_per_minute: float,
) -> tuple[list[VisualFlag], dict[str, Any]]:
    """Convert scored frame samples into smooth visual events."""
    scores = [_clamp_probability(_to_float(score)) for score in raw_scores]
    times = _normalize_elapsed_seconds(
        elapsed_seconds,
        score_count=len(scores),
        fps=fps,
    )
    active_threshold, calibrated, calibration_reason = _resolve_active_threshold(
        scores,
        configured_threshold=threshold,
        calibration_floor=calibration_floor,
        calibration_quantile=calibration_quantile,
    )
    diagnostics: dict[str, Any] = {
        **_score_summary(scores),
        "configured_threshold": round(_clamp_probability(float(threshold)), 6),
        "active_threshold": round(active_threshold, 6),
        "calibration_floor": round(_clamp_probability(float(calibration_floor)), 6),
        "calibration_quantile": round(
            max(0.0, min(1.0, float(calibration_quantile))), 6
        ),
        "threshold_calibrated": calibrated,
        "calibration_reason": calibration_reason,
        "merge_gap_sec": round(max(0.0, float(merge_gap_sec)), 6),
        "max_flags_per_minute": round(max(0.0, float(max_flags_per_minute)), 6),
    }

    hits = [
        (index, times[index], score)
        for index, score in enumerate(scores)
        if score >= active_threshold
    ]
    diagnostics["raw_hit_count"] = len(hits)
    if not hits:
        diagnostics["visual_flag_count"] = 0
        return [], diagnostics

    gap = max(0.0, float(merge_gap_sec))
    runs: list[list[tuple[int, float, float]]] = []
    current_run: list[tuple[int, float, float]] = []
    for hit in hits:
        if not current_run or hit[1] - current_run[-1][1] <= gap:
            current_run.append(hit)
            continue
        runs.append(current_run)
        current_run = [hit]
    if current_run:
        runs.append(current_run)

    events: list[dict[str, Any]] = []
    for run in runs:
        peak_index, peak_sec, peak_score = max(run, key=lambda item: item[2])
        events.append(
            {
                "source_index": peak_index,
                "sec": peak_sec,
                "score": peak_score,
                "start_sec": run[0][1],
                "end_sec": run[-1][1],
                "hit_count": len(run),
            }
        )

    diagnostics["visual_event_count_before_density_limit"] = len(events)
    max_density = max(0.0, float(max_flags_per_minute))
    suppressed_by_density = 0
    if max_density > 0.0:
        duration_sec = max(times, default=0.0)
        max_events = max(1, int(math.ceil(max(1.0, duration_sec / 60.0) * max_density)))
        diagnostics["visual_event_density_limit"] = max_events
        if len(events) > max_events:
            suppressed_by_density = len(events) - max_events
            events = sorted(
                events,
                key=lambda item: (float(item["score"]), int(item["hit_count"])),
                reverse=True,
            )[:max_events]
            events = sorted(events, key=lambda item: float(item["sec"]))

    diagnostics["visual_events_suppressed_by_density_limit"] = suppressed_by_density

    flags: list[VisualFlag] = []
    safe_fps = fps if fps > 0 else 1.0
    for output_index, event in enumerate(events):
        sec = max(0.0, float(event["sec"]))
        flags.append(
            VisualFlag(
                flag_id=f"visual_{output_index:06d}",
                sec=sec,
                frame_index=max(0, int(round(sec * safe_fps))),
                label="nsfw_visual",
                score=round(float(event["score"]), 6),
                source="opennsfw2",
            )
        )

    diagnostics["visual_flag_count"] = len(flags)
    diagnostics["merged_visual_event_count"] = len(flags)
    return flags, diagnostics


def score_full_video_in_process(
    video_path: str | Path,
    *,
    fps: float,
    duration_sec: float | None = None,
    visual_mode: str = "scene_aware_sparse",
    scene_segments: list[dict[str, Any]] | None = None,
    threshold: float = 0.35,
    frame_interval: int = 8,
    aggregation_size: int = 1,
    batch_size: int = 8,
    progress_bar: bool = False,
    calibration_floor: float = 0.18,
    calibration_quantile: float = 0.995,
    merge_gap_sec: float = 1.0,
    max_flags_per_minute: float = 18.0,
    per_scene_max_frames: int = 4,
    max_coarse_frames: int = 240,
    boundary_cluster_sec: float = 0.4,
    long_scene_stride_sec: float = 2.0,
    suspicious_score_ratio: float = 0.75,
    dense_window_sec: float = 1.5,
    dense_frame_interval: int = 1,
    max_dense_windows: int = 16,
) -> tuple[list[VisualFlag], AdapterStatus]:
    """Score video frames with OpenNSFW2 using configurable sparse/full strategies."""
    resolved_mode = str(visual_mode or "scene_aware_sparse").strip().lower()
    if resolved_mode not in {"scene_aware_sparse", "full_video_every_frame"}:
        resolved_mode = "scene_aware_sparse"
    resolved_scene_segments = list(scene_segments or [])
    resolved_duration_sec = (
        max(0.0, float(duration_sec))
        if duration_sec is not None
        else max(
            [0.0]
            + [max(0.0, _to_float(segment.get("end_sec"))) for segment in resolved_scene_segments]
        )
    )
    config = {
        "visual_mode": resolved_mode,
        "duration_sec": resolved_duration_sec,
        "scene_segment_count": len(resolved_scene_segments),
        "threshold": threshold,
        "frame_interval": max(1, int(frame_interval)),
        "aggregation_size": max(1, int(aggregation_size)),
        "batch_size": max(1, int(batch_size)),
        "progress_bar": bool(progress_bar),
        "calibration_floor": calibration_floor,
        "calibration_quantile": calibration_quantile,
        "merge_gap_sec": merge_gap_sec,
        "max_flags_per_minute": max_flags_per_minute,
        "per_scene_max_frames": max(1, int(per_scene_max_frames)),
        "max_coarse_frames": max(1, int(max_coarse_frames)),
        "boundary_cluster_sec": max(0.0, float(boundary_cluster_sec)),
        "long_scene_stride_sec": max(0.0, float(long_scene_stride_sec)),
        "suspicious_score_ratio": _clamp_probability(float(suspicious_score_ratio)),
        "dense_window_sec": max(0.1, float(dense_window_sec)),
        "dense_frame_interval": max(1, int(dense_frame_interval)),
        "max_dense_windows": max(0, int(max_dense_windows)),
        "mode": resolved_mode,
    }
    try:
        import opennsfw2
    except ModuleNotFoundError:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="OpenNSFW2 not installed.",
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive import boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 import failed: {exc}",
            config=config,
        )

    if not hasattr(opennsfw2, "predict_video_frames"):
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="OpenNSFW2 runtime does not expose predict_video_frames().",
            config=config,
        )

    try:
        elapsed_seconds: list[float]
        scores: list[float]
        strategy_diagnostics: dict[str, Any] = {}
        if resolved_mode == "scene_aware_sparse":
            elapsed_seconds, scores, strategy_diagnostics = _score_scene_aware_sparse(
                opennsfw2,
                video_path,
                fps=fps,
                duration_sec=max(0.01, resolved_duration_sec),
                scene_segments=resolved_scene_segments,
                threshold=threshold,
                calibration_floor=calibration_floor,
                frame_interval=max(1, int(frame_interval)),
                aggregation_size=max(1, int(aggregation_size)),
                batch_size=max(1, int(batch_size)),
                progress_bar=bool(progress_bar),
                per_scene_max_frames=max(1, int(per_scene_max_frames)),
                max_coarse_frames=max(1, int(max_coarse_frames)),
                boundary_cluster_sec=max(0.0, float(boundary_cluster_sec)),
                long_scene_stride_sec=max(0.0, float(long_scene_stride_sec)),
                suspicious_score_ratio=_clamp_probability(float(suspicious_score_ratio)),
                dense_window_sec=max(0.1, float(dense_window_sec)),
                dense_frame_interval=max(1, int(dense_frame_interval)),
                max_dense_windows=max(0, int(max_dense_windows)),
            )
        else:
            raw_elapsed_seconds, raw_scores = _predict_video_scores(
                opennsfw2,
                video_path,
                frame_interval=max(1, int(frame_interval)),
                aggregation_size=max(1, int(aggregation_size)),
                batch_size=max(1, int(batch_size)),
                progress_bar=bool(progress_bar),
            )
            elapsed_seconds = _normalize_elapsed_seconds(
                raw_elapsed_seconds,
                score_count=len(raw_scores),
                fps=fps,
            )
            scores = raw_scores
            strategy_diagnostics = {"full_video_scan": True}
        flags, diagnostics = _visual_flags_from_frame_scores(
            elapsed_seconds,
            scores,
            fps=fps,
            threshold=threshold,
            calibration_floor=calibration_floor,
            calibration_quantile=calibration_quantile,
            merge_gap_sec=merge_gap_sec,
            max_flags_per_minute=max_flags_per_minute,
        )
        config.update(strategy_diagnostics)
        config.update(diagnostics)
        version = getattr(opennsfw2, "__version__", None)
        detail = None
        if diagnostics.get("threshold_calibrated"):
            detail = (
                "Visual threshold calibrated from score distribution "
                f"({diagnostics['configured_threshold']} -> {diagnostics['active_threshold']})."
            )
        elif not flags:
            detail = (
                "No visual scores crossed the active threshold "
                f"(reason={diagnostics.get('calibration_reason')}, "
                f"max_score={diagnostics.get('max_score')})."
            )
        return flags, AdapterStatus(
            state=AdapterState.available,
            version=str(version) if version else None,
            detail=detail,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - adapter runtime boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 runtime failed: {exc}",
            config=config,
        )


def score_full_video(
    video_path: str | Path,
    *,
    fps: float,
    duration_sec: float | None = None,
    visual_mode: str = "scene_aware_sparse",
    scene_segments: list[dict[str, Any]] | None = None,
    threshold: float = 0.35,
    frame_interval: int = 8,
    aggregation_size: int = 1,
    batch_size: int = 8,
    progress_bar: bool = False,
    calibration_floor: float = 0.18,
    calibration_quantile: float = 0.995,
    merge_gap_sec: float = 1.0,
    max_flags_per_minute: float = 18.0,
    per_scene_max_frames: int = 4,
    max_coarse_frames: int = 240,
    boundary_cluster_sec: float = 0.4,
    long_scene_stride_sec: float = 2.0,
    suspicious_score_ratio: float = 0.75,
    dense_window_sec: float = 1.5,
    dense_frame_interval: int = 1,
    max_dense_windows: int = 16,
    timeout_sec: int = 1800,
    progress: ProgressCallback | None = None,
    progress_interval_sec: float = 15.0,
    omp_threads: int | None = None,
    tf_interop_threads: int | None = None,
    tf_intraop_threads: int | None = None,
) -> tuple[list[VisualFlag], AdapterStatus]:
    """Run OpenNSFW2 scoring in an isolated worker process."""
    resolved_mode = str(visual_mode or "scene_aware_sparse").strip().lower()
    if resolved_mode not in {"scene_aware_sparse", "full_video_every_frame"}:
        resolved_mode = "scene_aware_sparse"
    resolved_scene_segments = list(scene_segments or [])
    resolved_omp_threads = (
        max(1, int(omp_threads)) if omp_threads is not None else None
    )
    resolved_tf_interop_threads = (
        max(1, int(tf_interop_threads)) if tf_interop_threads is not None else None
    )
    resolved_tf_intraop_threads = (
        max(1, int(tf_intraop_threads)) if tf_intraop_threads is not None else None
    )
    resolved_progress_interval_sec = max(5.0, float(progress_interval_sec))
    config = {
        "visual_mode": resolved_mode,
        "duration_sec": (
            max(0.0, float(duration_sec))
            if duration_sec is not None
            else max(
                [0.0]
                + [
                    max(0.0, _to_float(segment.get("end_sec")))
                    for segment in resolved_scene_segments
                ]
            )
        ),
        "scene_segment_count": len(resolved_scene_segments),
        "threshold": threshold,
        "frame_interval": max(1, int(frame_interval)),
        "aggregation_size": max(1, int(aggregation_size)),
        "batch_size": max(1, int(batch_size)),
        "progress_bar": bool(progress_bar),
        "calibration_floor": calibration_floor,
        "calibration_quantile": calibration_quantile,
        "merge_gap_sec": merge_gap_sec,
        "max_flags_per_minute": max_flags_per_minute,
        "per_scene_max_frames": max(1, int(per_scene_max_frames)),
        "max_coarse_frames": max(1, int(max_coarse_frames)),
        "boundary_cluster_sec": max(0.0, float(boundary_cluster_sec)),
        "long_scene_stride_sec": max(0.0, float(long_scene_stride_sec)),
        "suspicious_score_ratio": _clamp_probability(float(suspicious_score_ratio)),
        "dense_window_sec": max(0.1, float(dense_window_sec)),
        "dense_frame_interval": max(1, int(dense_frame_interval)),
        "max_dense_windows": max(0, int(max_dense_windows)),
        "timeout_sec": max(60, int(timeout_sec)),
        "progress_interval_sec": resolved_progress_interval_sec,
        "omp_threads": resolved_omp_threads,
        "tf_interop_threads": resolved_tf_interop_threads,
        "tf_intraop_threads": resolved_tf_intraop_threads,
        "mode": f"{resolved_mode}_worker",
    }

    with tempfile.NamedTemporaryFile(
        suffix=".json",
        prefix="softcut_opennsfw2_",
        delete=False,
    ) as temp_file:
        output_path = Path(temp_file.name)

    command = [
        sys.executable,
        "-m",
        "engine.adapters.opennsfw2_worker",
        "--video-path",
        str(video_path),
        "--fps",
        str(fps),
        "--duration-sec",
        str(config["duration_sec"]),
        "--visual-mode",
        resolved_mode,
        "--scene-segments-json",
        json.dumps(resolved_scene_segments),
        "--threshold",
        str(threshold),
        "--frame-interval",
        str(max(1, int(frame_interval))),
        "--aggregation-size",
        str(max(1, int(aggregation_size))),
        "--batch-size",
        str(max(1, int(batch_size))),
        "--progress-bar",
        "1" if progress_bar else "0",
        "--calibration-floor",
        str(calibration_floor),
        "--calibration-quantile",
        str(calibration_quantile),
        "--merge-gap-sec",
        str(merge_gap_sec),
        "--max-flags-per-minute",
        str(max_flags_per_minute),
        "--per-scene-max-frames",
        str(max(1, int(per_scene_max_frames))),
        "--max-coarse-frames",
        str(max(1, int(max_coarse_frames))),
        "--boundary-cluster-sec",
        str(max(0.0, float(boundary_cluster_sec))),
        "--long-scene-stride-sec",
        str(max(0.0, float(long_scene_stride_sec))),
        "--suspicious-score-ratio",
        str(_clamp_probability(float(suspicious_score_ratio))),
        "--dense-window-sec",
        str(max(0.1, float(dense_window_sec))),
        "--dense-frame-interval",
        str(max(1, int(dense_frame_interval))),
        "--max-dense-windows",
        str(max(0, int(max_dense_windows))),
        "--output-path",
        str(output_path),
    ]

    with tempfile.NamedTemporaryFile(
        suffix=".log",
        prefix="softcut_opennsfw2_stdout_",
        delete=False,
    ) as stdout_file:
        stdout_path = Path(stdout_file.name)
    with tempfile.NamedTemporaryFile(
        suffix=".log",
        prefix="softcut_opennsfw2_stderr_",
        delete=False,
    ) as stderr_file:
        stderr_path = Path(stderr_file.name)

    started_at = time.monotonic()
    _emit(
        progress,
        (
            "Visual scan worker started "
            f"(mode={resolved_mode}, frame_interval={config['frame_interval']}, "
            f"aggregation_size={config['aggregation_size']}, "
            f"batch_size={config['batch_size']})."
        ),
    )

    try:
        with tempfile.TemporaryDirectory(prefix="softcut_opennsfw2_cache_") as cache_dir:
            mpl_cache = Path(cache_dir) / "matplotlib"
            xdg_cache = Path(cache_dir) / "xdg"
            mpl_cache.mkdir(parents=True, exist_ok=True)
            xdg_cache.mkdir(parents=True, exist_ok=True)
            env = {
                **os.environ,
                "TF_CPP_MIN_LOG_LEVEL": os.environ.get("TF_CPP_MIN_LOG_LEVEL", "2"),
                "MPLCONFIGDIR": str(mpl_cache),
                "XDG_CACHE_HOME": str(xdg_cache),
            }
            if resolved_omp_threads is not None:
                env["OMP_NUM_THREADS"] = str(resolved_omp_threads)
            elif "OMP_NUM_THREADS" not in env:
                env["OMP_NUM_THREADS"] = "1"
            if resolved_tf_interop_threads is not None:
                env["TF_NUM_INTEROP_THREADS"] = str(resolved_tf_interop_threads)
            elif "TF_NUM_INTEROP_THREADS" not in env:
                env["TF_NUM_INTEROP_THREADS"] = "1"
            if resolved_tf_intraop_threads is not None:
                env["TF_NUM_INTRAOP_THREADS"] = str(resolved_tf_intraop_threads)
            elif "TF_NUM_INTRAOP_THREADS" not in env:
                env["TF_NUM_INTRAOP_THREADS"] = "1"

            with stdout_path.open("w", encoding="utf-8") as stdout_stream, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_stream:
                proc = subprocess.Popen(
                    command,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    text=True,
                    env=env,
                )
                deadline = started_at + max(60, int(timeout_sec))
                last_progress_emit = started_at
                while proc.poll() is None:
                    now = time.monotonic()
                    if now >= deadline:
                        proc.kill()
                        proc.wait(timeout=5)
                        raise TimeoutError(
                            f"OpenNSFW2 worker timed out after {max(60, int(timeout_sec))}s."
                        )
                    if now - last_progress_emit >= resolved_progress_interval_sec:
                        elapsed = int(now - started_at)
                        _emit(
                            progress,
                            (
                                "Visual scan in progress "
                                f"({elapsed}s elapsed, batch_size={config['batch_size']})."
                            ),
                        )
                        last_progress_emit = now
                    time.sleep(1.0)
                return_code = int(proc.returncode or 0)
    except TimeoutError as exc:
        output_path.unlink(missing_ok=True)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=str(exc),
            config=config,
        )
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 worker launch failed: {exc}",
            config=config,
        )

    try:
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        stdout_text = ""
    try:
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        stderr_text = ""
    finally:
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)

    if return_code != 0:
        detail = stderr_text.strip() or stdout_text.strip() or "worker failed"
        output_path.unlink(missing_ok=True)
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 worker failed (exit {return_code}): {detail}",
            config=config,
        )

    if not output_path.exists():
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="OpenNSFW2 worker completed but returned no output.",
            config=config,
        )

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 worker output parse failed: {exc}",
            config=config,
        )
    finally:
        output_path.unlink(missing_ok=True)

    flags_payload = payload.get("visual_flags", [])
    status_payload = payload.get("status", {})
    flags = [VisualFlag.model_validate(item) for item in flags_payload]
    status = AdapterStatus.model_validate(status_payload)
    status = status.model_copy(
        update={
            "config": {
                **config,
                **status.config,
            }
        }
    )
    elapsed = int(time.monotonic() - started_at)
    _emit(
        progress,
        f"Visual scan completed in {elapsed}s (visual_flags={len(flags)}).",
    )
    return flags, status
