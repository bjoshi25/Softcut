"""Isolated worker for OpenNSFW2 visual scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.adapters.opennsfw2_adapter import score_full_video_in_process


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenNSFW2 visual worker")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--duration-sec", type=float, default=0.0)
    parser.add_argument("--visual-mode", default="scene_aware_sparse")
    parser.add_argument("--scene-segments-json", default="[]")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--frame-interval", type=int, default=8)
    parser.add_argument("--aggregation-size", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--progress-bar", type=int, default=0)
    parser.add_argument("--calibration-floor", type=float, default=0.18)
    parser.add_argument("--calibration-quantile", type=float, default=0.995)
    parser.add_argument("--merge-gap-sec", type=float, default=1.0)
    parser.add_argument("--max-flags-per-minute", type=float, default=18.0)
    parser.add_argument("--per-scene-max-frames", type=int, default=4)
    parser.add_argument("--boundary-cluster-sec", type=float, default=0.4)
    parser.add_argument("--long-scene-stride-sec", type=float, default=2.0)
    parser.add_argument("--suspicious-score-ratio", type=float, default=0.75)
    parser.add_argument("--dense-window-sec", type=float, default=1.5)
    parser.add_argument("--dense-frame-interval", type=int, default=1)
    parser.add_argument("--max-dense-windows", type=int, default=16)
    parser.add_argument("--output-path", required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        scene_segments = json.loads(args.scene_segments_json or "[]")
    except json.JSONDecodeError:
        scene_segments = []
    if not isinstance(scene_segments, list):
        scene_segments = []
    flags, status = score_full_video_in_process(
        args.video_path,
        fps=float(args.fps),
        duration_sec=float(args.duration_sec),
        visual_mode=str(args.visual_mode),
        scene_segments=scene_segments,
        threshold=float(args.threshold),
        frame_interval=max(1, int(args.frame_interval)),
        aggregation_size=max(1, int(args.aggregation_size)),
        batch_size=max(1, int(args.batch_size)),
        progress_bar=bool(args.progress_bar),
        calibration_floor=float(args.calibration_floor),
        calibration_quantile=float(args.calibration_quantile),
        merge_gap_sec=float(args.merge_gap_sec),
        max_flags_per_minute=float(args.max_flags_per_minute),
        per_scene_max_frames=max(1, int(args.per_scene_max_frames)),
        boundary_cluster_sec=max(0.0, float(args.boundary_cluster_sec)),
        long_scene_stride_sec=max(0.0, float(args.long_scene_stride_sec)),
        suspicious_score_ratio=max(0.0, min(1.0, float(args.suspicious_score_ratio))),
        dense_window_sec=max(0.1, float(args.dense_window_sec)),
        dense_frame_interval=max(1, int(args.dense_frame_interval)),
        max_dense_windows=max(0, int(args.max_dense_windows)),
    )
    payload = {
        "visual_flags": [flag.model_dump(mode="json") for flag in flags],
        "status": status.model_dump(mode="json"),
    }
    Path(args.output_path).write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
