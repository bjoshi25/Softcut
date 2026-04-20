"""Unit tests for adversarial hardening logic."""

from __future__ import annotations

import unittest

from engine.analysis.build_timeline import (
    _build_rating_evidence,
    _build_quality_report,
    _build_visual_coverage_summary,
    _calibrate_pyscene_scores,
    _normalize_text_token,
)
from engine.fusion.boundary_fusion import BoundaryCandidate
from engine.schemas.timeline import (
    AdapterState,
    AdapterStatus,
    SceneBoundary,
    SpeechSegment,
    WordSegment,
)


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

    def test_quality_report_flags_sparse_fallback_failures(self) -> None:
        report = _build_quality_report(
            job_id="job_sparse",
            run_profile="degraded",
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
                config={
                    "coarse_clip_extract_failed": True,
                    "coarse_total_frame_count": 1000,
                    "scanned_frames": 4670,
                    "visual_flag_count": 8,
                },
            ),
            quality_cfg={
                "extreme_cut_per_minute": 45.0,
                "min_evidence_per_minute": 0.4,
                "strict_requires_transnet": True,
                "strict_requires_visual": True,
            },
        )
        self.assertIn("visual_sparse_extract_failed", report.warnings)
        self.assertIn("visual_sparse_ineffective_scanned_frames=4670", report.warnings)

    def test_quality_report_flags_sparse_low_coverage(self) -> None:
        report = _build_quality_report(
            job_id="job_sparse_low_coverage",
            run_profile="degraded",
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
                config={
                    "coarse_total_frame_count": 240,
                    "coarse_score_coverage_ratio": 0.25,
                    "scanned_frames": 120,
                    "visual_flag_count": 2,
                },
            ),
            quality_cfg={
                "extreme_cut_per_minute": 45.0,
                "min_evidence_per_minute": 0.4,
                "strict_requires_transnet": True,
                "strict_requires_visual": True,
            },
        )
        self.assertIn("visual_sparse_low_coverage_ratio=0.250", report.warnings)

    def test_visual_coverage_summary_uses_adapter_diagnostics(self) -> None:
        summary = _build_visual_coverage_summary(
            visual_mode="scene_aware_sparse",
            scene_count=121,
            opennsfw_cfg={
                "dense_window_count": 2,
                "coverage_summary": {
                    "total_scenes": 121,
                    "sampled_scenes": 119,
                    "sampled_scene_ratio": 0.983471,
                    "avg_frames_sampled_per_scene": 1.975207,
                    "escalated_scenes": 3,
                    "escalated_scene_ratio": 0.024793,
                    "dense_rescans": 2,
                },
            },
        )
        self.assertEqual(summary["total_scenes"], 121)
        self.assertEqual(summary["sampled_scenes"], 119)
        self.assertEqual(summary["dense_rescans"], 2)

    def test_quality_report_includes_coverage_summary(self) -> None:
        summary = {
            "total_scenes": 10,
            "sampled_scenes": 10,
            "sampled_scene_ratio": 1.0,
            "avg_frames_sampled_per_scene": 2.4,
            "escalated_scenes": 0,
            "escalated_scene_ratio": 0.0,
            "dense_rescans": 0,
        }
        report = _build_quality_report(
            job_id="job_cov",
            run_profile="degraded",
            duration_sec=60.0,
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
                config={"visual_flag_count": 1},
            ),
            quality_cfg={
                "extreme_cut_per_minute": 45.0,
                "min_evidence_per_minute": 0.4,
                "strict_requires_transnet": True,
                "strict_requires_visual": True,
            },
            coverage_summary=summary,
        )
        self.assertEqual(report.coverage_summary, summary)

    def test_normalize_token_handles_possessive_and_plural(self) -> None:
        self.assertEqual(_normalize_text_token("fuck's"), "fuck")
        self.assertEqual(_normalize_text_token("dicks."), "dick")

    def test_rating_evidence_captures_die_suicide_and_normalized_profanity(self) -> None:
        speech = [
            SpeechSegment(
                segment_id="speech_0001",
                start_sec=1.0,
                end_sec=2.0,
                text="We're all going to die.",
            ),
            SpeechSegment(
                segment_id="speech_0002",
                start_sec=3.0,
                end_sec=4.0,
                text="This is the famous suicide squad.",
            ),
        ]
        words = [
            WordSegment(
                word_id="w1",
                start_sec=1.2,
                end_sec=1.3,
                word="fuck's",
            ),
            WordSegment(
                word_id="w2",
                start_sec=3.2,
                end_sec=3.3,
                word="dicks.",
            ),
        ]

        evidence = _build_rating_evidence(
            speech_segments=speech,
            word_segments=words,
            visual_flags=[],
        )
        evidence_types = [item.evidence_type for item in evidence]
        dimensions = [item.dimension for item in evidence]
        self.assertIn("moderate_profanity", evidence_types)
        self.assertIn("violence", dimensions)
        violent_phrases = [
            item.references.get("phrase")
            for item in evidence
            if item.dimension == "violence"
        ]
        self.assertIn("die", violent_phrases)
        self.assertIn("suicide", violent_phrases)


if __name__ == "__main__":
    unittest.main()
