"""FFmpeg/ffprobe utility adapter."""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class VideoMetadata:
    """Basic video metadata required by the engine."""

    fps: float
    duration_sec: float
    width: int
    height: int
    total_frames: int
    codec_name: str | None = None


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def _fraction_to_float(value: str | None) -> float:
    if not value or value == "0/0" or value == "N/A":
        return 0.0
    if "/" in value:
        num_text, den_text = value.split("/", 1)
        num = float(num_text)
        den = float(den_text)
        if den == 0:
            return 0.0
        return num / den
    return float(value)


def ffmpeg_version() -> str:
    """Return FFmpeg version string."""
    result = _run_command(["ffmpeg", "-version"])
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip()


def probe_video(video_path: str | Path) -> VideoMetadata:
    """Read video metadata using ffprobe."""
    result = _run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError(f"no video stream found in {video_path}")

    fps = _fraction_to_float(video_stream.get("avg_frame_rate")) or _fraction_to_float(
        video_stream.get("r_frame_rate")
    )
    duration_sec = float(
        video_stream.get("duration") or payload.get("format", {}).get("duration") or 0.0
    )
    if fps <= 0 or duration_sec <= 0:
        raise ValueError(f"invalid fps ({fps}) or duration ({duration_sec}) for {video_path}")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid dimensions for {video_path}")

    nb_frames = video_stream.get("nb_frames")
    total_frames = int(nb_frames) if nb_frames and nb_frames != "N/A" else 0
    if total_frames <= 0:
        total_frames = int(math.ceil(duration_sec * fps))
    total_frames = max(1, total_frames)
    return VideoMetadata(
        fps=fps,
        duration_sec=duration_sec,
        width=width,
        height=height,
        total_frames=total_frames,
        codec_name=video_stream.get("codec_name"),
    )


def _extract_luma_mean_map_for_frames(
    video_path: str | Path,
    frames: list[int],
    *,
    fps: float | None = None,
    max_select_frames: int = 80,
) -> dict[int, float]:
    """Read per-frame luma means for specific frame indices."""
    if not frames:
        return {}

    unique_frames = sorted({max(0, int(frame)) for frame in frames})
    if not unique_frames:
        return {}

    resolved_fps = float(fps or 0.0)
    if resolved_fps <= 0:
        resolved_fps = probe_video(video_path).fps

    def _run_chunk(chunk_frames: list[int], sink: dict[int, float]) -> None:
        if not chunk_frames:
            return
        select_parts = [f"eq(n\\,{frame})" for frame in chunk_frames]
        filter_expr = f"select='{'+'.join(select_parts)}',showinfo"
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                str(video_path),
                "-vf",
                filter_expr,
                "-an",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        output = f"{result.stdout}\n{result.stderr}"
        parsed = 0
        for line in output.splitlines():
            if "showinfo" not in line:
                continue
            pts_match = re.search(r"pts_time:([0-9.]+)", line)
            mean_match = re.search(r"mean:\[([0-9 ]+)\]", line)
            if not pts_match or not mean_match:
                continue
            first_channel = mean_match.group(1).split()[0]
            pts_time = float(pts_match.group(1))
            frame_index = max(0, int(round(pts_time * resolved_fps)))
            sink[frame_index] = float(first_channel)
            parsed += 1

        if parsed == 0 and len(chunk_frames) > 1:
            midpoint = len(chunk_frames) // 2
            _run_chunk(chunk_frames[:midpoint], sink)
            _run_chunk(chunk_frames[midpoint:], sink)

    mean_by_frame: dict[int, float] = {}
    for start in range(0, len(unique_frames), max_select_frames):
        chunk = unique_frames[start : start + max_select_frames]
        _run_chunk(chunk, mean_by_frame)
    return mean_by_frame


def local_frame_delta_score(
    video_path: str | Path, frame_index: int, *, fps: float | None = None
) -> float:
    """Estimate local frame delta around a boundary frame as [0, 1]."""
    previous_frame = max(0, frame_index - 1)
    mean_by_frame = _extract_luma_mean_map_for_frames(
        video_path, [previous_frame, frame_index], fps=fps
    )
    prev_mean = mean_by_frame.get(previous_frame)
    curr_mean = mean_by_frame.get(frame_index)
    if prev_mean is None or curr_mean is None:
        return 0.0
    delta = abs(curr_mean - prev_mean) / 255.0
    return max(0.0, min(1.0, delta))


def local_frame_delta_scores(
    video_path: str | Path,
    frame_indices: list[int],
    *,
    fps: float | None = None,
) -> dict[int, float]:
    """Estimate local frame deltas for multiple frame indices."""
    if not frame_indices:
        return {}

    target_frames = [max(0, int(frame_idx)) for frame_idx in frame_indices]
    probe_frames: list[int] = []
    for frame_idx in target_frames:
        probe_frames.append(max(0, frame_idx - 1))
        probe_frames.append(frame_idx)

    mean_by_frame = _extract_luma_mean_map_for_frames(
        video_path,
        probe_frames,
        fps=fps,
    )
    scores: dict[int, float] = {}
    for frame_idx in target_frames:
        prev_frame = max(0, frame_idx - 1)
        prev_mean = mean_by_frame.get(prev_frame)
        curr_mean = mean_by_frame.get(frame_idx)
        if prev_mean is None or curr_mean is None:
            scores[frame_idx] = 0.0
            continue
        delta = abs(curr_mean - prev_mean) / 255.0
        scores[frame_idx] = max(0.0, min(1.0, delta))
    return scores
