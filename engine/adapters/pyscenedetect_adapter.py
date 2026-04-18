"""PySceneDetect adapter with FFmpeg fallback."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from engine.fusion.boundary_fusion import BoundaryCandidate
from engine.schemas.timeline import AdapterState, AdapterStatus


def _dedupe_frames(boundaries: list[BoundaryCandidate], *, tolerance_frames: int = 2) -> list[BoundaryCandidate]:
    if not boundaries:
        return []
    ordered = sorted(boundaries, key=lambda item: item.frame_index)
    deduped: list[BoundaryCandidate] = [ordered[0]]
    for item in ordered[1:]:
        if abs(item.frame_index - deduped[-1].frame_index) <= tolerance_frames:
            if item.score > deduped[-1].score:
                deduped[-1] = item
            continue
        deduped.append(item)
    return deduped


def _detect_with_pyscenedetect(
    video_path: str | Path,
    *,
    threshold: float,
    min_scene_len_frames: int,
) -> list[BoundaryCandidate]:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(
        ContentDetector(
            threshold=threshold,
            min_scene_len=max(1, min_scene_len_frames),
        )
    )
    manager.detect_scenes(video, show_progress=False)
    try:
        scene_list = manager.get_scene_list(start_in_scene=True)
    except TypeError:
        # Compatibility with older PySceneDetect versions.
        scene_list = manager.get_scene_list()

    boundaries: list[BoundaryCandidate] = []
    for index, scene in enumerate(scene_list):
        # `get_scene_list()` returns tuples of (start_timecode, end_timecode).
        start = scene[0] if isinstance(scene, (tuple, list)) else scene
        if hasattr(start, "get_frames"):
            frame = int(start.get_frames())
        else:
            frame = int(start)
        # Skip first scene start at frame 0; not a cut boundary.
        if index == 0 and frame <= 0:
            continue
        boundaries.append(
            BoundaryCandidate(
                frame_index=max(0, frame),
                score=0.65,
                source="pyscenedetect",
            )
        )
    return _dedupe_frames(boundaries)


def _detect_with_ffmpeg_scene_filter(
    video_path: str | Path,
    *,
    scene_threshold: float,
) -> list[BoundaryCandidate]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(video_path),
        "-filter:v",
        f"select='gt(scene\\,{scene_threshold})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    output = f"{result.stdout}\n{result.stderr}"

    boundaries: list[BoundaryCandidate] = []
    for line in output.splitlines():
        if "showinfo" not in line:
            continue
        frame_match = re.search(r"n:\s*([0-9]+)", line)
        if not frame_match:
            continue
        frame = int(frame_match.group(1))
        score = min(0.95, max(0.30, scene_threshold + 0.45))
        boundaries.append(
            BoundaryCandidate(
                frame_index=frame,
                score=score,
                source="pyscenedetect",
            )
        )
    return _dedupe_frames(boundaries)


def detect_boundaries(
    video_path: str | Path,
    *,
    fps: float,
    threshold: float = 27.0,
    min_scene_len_sec: float = 0.8,
    ffmpeg_scene_threshold: float = 0.35,
) -> tuple[list[BoundaryCandidate], AdapterStatus]:
    """Detect scene boundaries from PySceneDetect or fallback method."""
    min_scene_len_frames = int(round(max(0.1, min_scene_len_sec) * fps))
    config = {
        "threshold": threshold,
        "min_scene_len_sec": min_scene_len_sec,
        "min_scene_len_frames": min_scene_len_frames,
        "ffmpeg_scene_threshold": ffmpeg_scene_threshold,
    }

    try:
        import scenedetect

        boundaries = _detect_with_pyscenedetect(
            video_path,
            threshold=threshold,
            min_scene_len_frames=min_scene_len_frames,
        )
        version = getattr(scenedetect, "__version__", None)
        return boundaries, AdapterStatus(
            state=AdapterState.available,
            version=str(version) if version else None,
            config=config,
        )
    except ModuleNotFoundError:
        boundaries = _detect_with_ffmpeg_scene_filter(
            video_path, scene_threshold=ffmpeg_scene_threshold
        )
        return boundaries, AdapterStatus(
            state=AdapterState.fallback,
            detail="PySceneDetect not installed; used FFmpeg scene filter fallback.",
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        boundaries = _detect_with_ffmpeg_scene_filter(
            video_path, scene_threshold=ffmpeg_scene_threshold
        )
        return boundaries, AdapterStatus(
            state=AdapterState.fallback,
            detail=f"PySceneDetect failed ({exc}); used FFmpeg scene filter fallback.",
            config=config,
        )
