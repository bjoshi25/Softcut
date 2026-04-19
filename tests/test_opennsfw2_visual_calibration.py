"""Unit tests for OpenNSFW2 score calibration and sparse sampling helpers."""

from __future__ import annotations

import unittest

from engine.adapters.opennsfw2_adapter import (
    _dense_windows_from_scores,
    _scene_representative_frame_indices,
    _visual_flags_from_frame_scores,
)


class OpenNSFW2VisualCalibrationTests(unittest.TestCase):
    def test_calibrates_threshold_when_score_tail_is_real(self) -> None:
        elapsed = [index / 24.0 for index in range(20)]
        scores = [0.02] * 18 + [0.21, 0.23]

        flags, diagnostics = _visual_flags_from_frame_scores(
            elapsed,
            scores,
            fps=24.0,
            threshold=0.35,
            calibration_floor=0.18,
            calibration_quantile=0.95,
            merge_gap_sec=1.0,
            max_flags_per_minute=18.0,
        )

        self.assertTrue(diagnostics["threshold_calibrated"])
        self.assertEqual(diagnostics["calibration_reason"], "calibrated_to_score_distribution")
        self.assertGreaterEqual(len(flags), 1)
        self.assertLess(diagnostics["active_threshold"], diagnostics["configured_threshold"])

    def test_merges_dense_frame_hits_into_smooth_events(self) -> None:
        elapsed = [index / 24.0 for index in range(48)]
        scores = [0.4] * 24 + [0.01] * 24

        flags, diagnostics = _visual_flags_from_frame_scores(
            elapsed,
            scores,
            fps=24.0,
            threshold=0.25,
            calibration_floor=0.18,
            calibration_quantile=0.995,
            merge_gap_sec=1.0,
            max_flags_per_minute=18.0,
        )

        self.assertEqual(diagnostics["raw_hit_count"], 24)
        self.assertEqual(diagnostics["visual_event_count_before_density_limit"], 1)
        self.assertEqual(len(flags), 1)

    def test_zero_flags_include_score_diagnostics(self) -> None:
        elapsed = [0.0, 0.04, 0.08]
        scores = [0.01, 0.02, 0.03]

        flags, diagnostics = _visual_flags_from_frame_scores(
            elapsed,
            scores,
            fps=24.0,
            threshold=0.25,
            calibration_floor=0.18,
            calibration_quantile=0.995,
            merge_gap_sec=1.0,
            max_flags_per_minute=18.0,
        )

        self.assertEqual(flags, [])
        self.assertEqual(diagnostics["visual_flag_count"], 0)
        self.assertEqual(diagnostics["max_score"], 0.03)
        self.assertEqual(
            diagnostics["calibration_reason"],
            "max_score_below_calibration_floor",
        )

    def test_scene_representative_frames_cover_boundaries_and_mid(self) -> None:
        frames = _scene_representative_frame_indices(
            [
                {
                    "start_frame": 0,
                    "end_frame": 120,
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                }
            ],
            fps=24.0,
            total_frames=240,
            per_scene_max_frames=5,
            boundary_cluster_sec=0.5,
            long_scene_stride_sec=2.0,
        )

        self.assertGreaterEqual(len(frames), 4)
        self.assertIn(0, frames)
        self.assertIn(60, frames)
        self.assertIn(120, frames)

    def test_dense_window_selection_limits_overlap(self) -> None:
        windows = _dense_windows_from_scores(
            [1.0, 1.2, 7.0, 7.3, 20.0],
            [0.40, 0.41, 0.35, 0.36, 0.10],
            threshold=0.30,
            radius_sec=1.0,
            max_windows=2,
            duration_sec=30.0,
        )

        self.assertEqual(len(windows), 2)
        self.assertLessEqual(windows[0][0], 1.0)
        self.assertGreaterEqual(windows[0][1], 1.2)


if __name__ == "__main__":
    unittest.main()
