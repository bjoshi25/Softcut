"""Unit tests for planner pipeline behavior."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.planning.build_plan import build_edit_plan
from engine.schemas.timeline import (
    AnalysisMetadata,
    AnalysisQualityReport,
    AnalysisTimeline,
    EditContextWindow,
    RatingEvidence,
    SafeCutPoint,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PlannerPipelineTests(unittest.TestCase):
    def _build_fixture_timeline(self) -> AnalysisTimeline:
        return AnalysisTimeline(
            job_id="job_plan_001",
            source_video="data/inbox/input.mp4",
            fps=25.0,
            duration_sec=10.0,
            rating_evidence=[
                RatingEvidence(
                    evidence_id="evidence_0000",
                    start_sec=1.0,
                    end_sec=1.2,
                    dimension="language",
                    evidence_type="strong_profanity",
                    score=0.92,
                    references={"word_id": "speech_0001_word_000"},
                ),
                RatingEvidence(
                    evidence_id="evidence_0001",
                    start_sec=2.0,
                    end_sec=2.0,
                    dimension="sexual",
                    evidence_type="nsfw_visual",
                    score=0.5,
                    references={"flag_id": "visual_0001"},
                ),
            ],
            safe_cut_points=[
                SafeCutPoint(
                    point_id="cut_0001_pre",
                    sec=1.8,
                    frame_index=45,
                    kind="pre",
                    boundary_confidence=0.8,
                    references={"evidence_id": "evidence_0001"},
                ),
                SafeCutPoint(
                    point_id="cut_0001_post",
                    sec=2.2,
                    frame_index=55,
                    kind="post",
                    boundary_confidence=0.8,
                    references={"evidence_id": "evidence_0001"},
                ),
            ],
            edit_context_windows=[
                EditContextWindow(
                    window_id="window_0000",
                    evidence_id="evidence_0000",
                    start_sec=0.9,
                    end_sec=1.3,
                    overlap_tag="compatible",
                    compatible_actions=["mute_word", "beep_word", "trim_segment"],
                ),
                EditContextWindow(
                    window_id="window_0001",
                    evidence_id="evidence_0001",
                    start_sec=1.7,
                    end_sec=2.3,
                    overlap_tag="compatible",
                    compatible_actions=["trim_segment", "remove_scene"],
                ),
            ],
            metadata=AnalysisMetadata(run_profile="degraded"),
        )

    def test_build_edit_plan_generates_expected_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="softcut_planner_test_") as temp_dir:
            temp_path = Path(temp_dir)
            timeline = self._build_fixture_timeline()
            quality_report = AnalysisQualityReport(
                job_id=timeline.job_id,
                run_profile="degraded",
                passed=True,
                planner_eligible=True,
            )

            timeline_path = temp_path / "analysis_timeline.json"
            quality_path = temp_path / "analysis_quality_report.json"
            output_path = temp_path / "edit_plan.json"
            _write_json(timeline_path, timeline.model_dump(mode="json"))
            _write_json(quality_path, quality_report.model_dump(mode="json"))

            plan, resolved = build_edit_plan(
                timeline_path=str(timeline_path),
                quality_report_path=str(quality_path),
                output_path=str(output_path),
            )

            self.assertEqual(resolved, output_path)
            self.assertEqual(len(plan.actions), 2)
            by_evidence = {action.evidence_id: action for action in plan.actions}
            self.assertEqual(by_evidence["evidence_0000"].action, "beep_word")
            self.assertEqual(by_evidence["evidence_0001"].action, "trim_segment")
            self.assertEqual(by_evidence["evidence_0001"].start_sec, 1.8)
            self.assertEqual(by_evidence["evidence_0001"].end_sec, 2.2)
            self.assertEqual(plan.summary.action_counts.get("beep_word"), 1)
            self.assertEqual(plan.summary.action_counts.get("trim_segment"), 1)

    def test_build_edit_plan_enforces_planner_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="softcut_planner_gate_") as temp_dir:
            temp_path = Path(temp_dir)
            timeline = self._build_fixture_timeline()
            quality_report = AnalysisQualityReport(
                job_id=timeline.job_id,
                run_profile="degraded",
                passed=True,
                planner_eligible=False,
            )
            timeline_path = temp_path / "analysis_timeline.json"
            quality_path = temp_path / "analysis_quality_report.json"
            _write_json(timeline_path, timeline.model_dump(mode="json"))
            _write_json(quality_path, quality_report.model_dump(mode="json"))

            with self.assertRaisesRegex(ValueError, "planner-eligible"):
                build_edit_plan(
                    timeline_path=str(timeline_path),
                    quality_report_path=str(quality_path),
                )

    def test_build_edit_plan_drops_low_score_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="softcut_planner_low_score_") as temp_dir:
            temp_path = Path(temp_dir)
            timeline = self._build_fixture_timeline()
            quality_report = AnalysisQualityReport(
                job_id=timeline.job_id,
                run_profile="degraded",
                passed=True,
                planner_eligible=True,
            )
            planner_cfg = temp_path / "planner.yaml"
            planner_cfg.write_text(
                "\n".join(
                    [
                        "planner:",
                        "  min_evidence_score: 0.95",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            timeline_path = temp_path / "analysis_timeline.json"
            quality_path = temp_path / "analysis_quality_report.json"
            _write_json(timeline_path, timeline.model_dump(mode="json"))
            _write_json(quality_path, quality_report.model_dump(mode="json"))

            plan, _resolved = build_edit_plan(
                timeline_path=str(timeline_path),
                quality_report_path=str(quality_path),
                config_path=str(planner_cfg),
            )

            self.assertEqual(len(plan.actions), 0)
            self.assertEqual(plan.summary.dropped_low_score, 2)


if __name__ == "__main__":
    unittest.main()
