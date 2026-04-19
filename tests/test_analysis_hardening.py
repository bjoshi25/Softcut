"""Unit tests for adversarial hardening logic."""

from __future__ import annotations

import unittest

from engine.analysis.build_timeline import (
    _build_quality_report,
    _calibrate_pyscene_scores,
)
from engine.fusion.boundary_fusion import BoundaryCandidate
from engine.schemas.timeline import AdapterState, AdapterStatus, SceneBoundary


class AnalysisHardeningTests(unittest.TestCase):
    def test_calibrated_pyscene_scores_use_local_and_agreement(self) -> None:
        pyscene = [
            BoundaryCandidate(frame_index=100, score=0.65, source="pyscenedetect"),
            BoundaryCandidate(frame_index=200, score=0.65, source="pyscenedetect"),
        ]
        transnet = [BoundaryCandidate(frame_index=102, score=0.8, source="transnetv2")]
        local = {100: 0.7, 200: 0.1}

        _calibrate_pyscene_scores(
            pyscene_boundaries=pyscene,
            transnet_boundaries=transnet,
            local_scores=local,
            tolerance_frames=8,
        )

        self.assertGreater(pyscene[0].score, pyscene[1].score)
        self.assertGreaterEqual(pyscene[0].score, 0.35)

    def test_quality_report_strict_blocks_missing_coverage(self) -> None:
        report = _build_quality_report(
            job_id="job_x",
            run_profile="strict",
            duration_sec=120.0,
            rating_evidence=[],
            boundary_models=[
                SceneBoundary(
                    frame_index=100,
                    sec=4.0,
                    fused_score=0.15,
                    sources=["pyscenedetect"],
                    component_scores={},
                )
            ],
            local_scores={100: 0.0},
            asr_mode="failed",
            visual_mode="disabled",
            transnet_status=AdapterStatus(
                state=AdapterState.unavailable,
                detail="missing",
                config={},
            ),
            opennsfw_status=AdapterStatus(
                state=AdapterState.unavailable,
                detail="missing",
                config={},
            ),
            quality_cfg={
                "extreme_cut_per_minute": 45.0,
                "min_evidence_per_minute": 0.4,
                "strict_requires_transnet": True,
                "strict_requires_visual": True,
            },
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.planner_eligible)
        self.assertIn("strict_requires_transnet", report.critical_findings)
        self.assertIn("strict_requires_visual", report.critical_findings)

    def test_quality_report_strict_accepts_scene_aware_visual_mode(self) -> None:
        report = _build_quality_report(
            job_id="job_y",
            run_profile="strict",
            duration_sec=120.0,
            rating_evidence=[],
            boundary_models=[],
            local_scores={},
            asr_mode="full",
            visual_mode="scene_aware_sparse",
            transnet_status=AdapterStatus(
                state=AdapterState.available,
                detail=None,
                config={},
            ),
            opennsfw_status=AdapterStatus(
                state=AdapterState.available,
                detail=None,
                config={"visual_flag_count": 0, "max_score": 0.19},
            ),
            quality_cfg={
                "extreme_cut_per_minute": 45.0,
                "min_evidence_per_minute": 0.4,
                "strict_requires_transnet": True,
                "strict_requires_visual": True,
            },
        )
        self.assertNotIn("strict_requires_visual", report.critical_findings)


if __name__ == "__main__":
    unittest.main()
