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


def sample_frame_times(
    *,
    duration_sec: float,
    sample_every_sec: float,
    max_samples: int,
) -> list[float]:
    """Generate uniformly sampled frame times for visual classifiers."""
    if duration_sec <= 0:
        return []
    if sample_every_sec <= 0:
        sample_every_sec = 1.0

    times: list[float] = []
    cursor = 0.0
    while cursor < duration_sec and len(times) < max_samples:
        times.append(round(cursor, 3))
        cursor += sample_every_sec

    if times and times[-1] < duration_sec and len(times) < max_samples:
        times.append(round(max(0.0, duration_sec - 0.05), 3))
    return times


def extract_frame_image(video_path: str | Path, *, time_sec: float, output_path: str | Path) -> None:
    """Extract one frame to an image file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, time_sec):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
    )


def extract_sampled_frames(
    video_path: str | Path,
    *,
    duration_sec: float,
    output_dir: str | Path,
    sample_every_sec: float = 5.0,
    max_samples: int = 90,
) -> list[tuple[float, str]]:
    """Extract sampled frames and return (time_sec, frame_path)."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    samples = sample_frame_times(
        duration_sec=duration_sec,
        sample_every_sec=sample_every_sec,
        max_samples=max_samples,
    )
    outputs: list[tuple[float, str]] = []
    for idx, sample_sec in enumerate(samples):
        frame_path = output_root / f"frame_{idx:04d}.jpg"
        extract_frame_image(video_path, time_sec=sample_sec, output_path=frame_path)
        outputs.append((sample_sec, str(frame_path)))
    return outputs


def _extract_luma_mean_map_for_frames(
    video_path: str | Path,
    frames: list[int],
    *,
    max_select_frames: int = 600,
) -> dict[int, float]:
    """Read per-frame luma means for specific frame indices."""
    if not frames:
        return {}

    unique_frames = sorted({max(0, int(frame)) for frame in frames})
    if not unique_frames:
        return {}

    mean_by_frame: dict[int, float] = {}
    for start in range(0, len(unique_frames), max_select_frames):
        chunk = unique_frames[start : start + max_select_frames]
        select_parts = [f"eq(n\\,{frame})" for frame in chunk]
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
        for line in output.splitlines():
            if "showinfo" not in line:
                continue
            frame_match = re.search(r"n:\s*([0-9]+)", line)
            mean_match = re.search(r"mean:\[([0-9 ]+)\]", line)
            if not frame_match or not mean_match:
                continue
            first_channel = mean_match.group(1).split()[0]
            mean_by_frame[int(frame_match.group(1))] = float(first_channel)
    return mean_by_frame


def local_frame_delta_score(video_path: str | Path, frame_index: int) -> float:
    """Estimate local frame delta around a boundary frame as [0, 1]."""
    previous_frame = max(0, frame_index - 1)
    mean_by_frame = _extract_luma_mean_map_for_frames(
        video_path, [previous_frame, frame_index]
    )
    prev_mean = mean_by_frame.get(previous_frame)
    curr_mean = mean_by_frame.get(frame_index)
    if prev_mean is None or curr_mean is None:
        return 0.0
    delta = abs(curr_mean - prev_mean) / 255.0
    return max(0.0, min(1.0, delta))


def local_frame_delta_scores(
    video_path: str | Path, frame_indices: list[int]
) -> dict[int, float]:
    """Estimate local frame deltas for multiple frame indices."""
    if not frame_indices:
        return {}

    target_frames = [max(0, int(frame_idx)) for frame_idx in frame_indices]
    probe_frames: list[int] = []
    for frame_idx in target_frames:
        probe_frames.append(max(0, frame_idx - 1))
        probe_frames.append(frame_idx)

    mean_by_frame = _extract_luma_mean_map_for_frames(video_path, probe_frames)
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
