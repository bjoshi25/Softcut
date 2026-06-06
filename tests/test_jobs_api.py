"""Route-level tests for async jobs orchestration handlers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from io import BytesIO
from unittest.mock import patch

from fastapi.exceptions import HTTPException

from apps.api.routes.jobs import (
    _create_job_from_upload_payload,
    CreateUrlJobRequest,
    QueuePlannerRequest,
    create_job_from_url,
    get_job_results,
    get_job_status,
    queue_planner_only,
)
from engine.schemas.planner import EditPlanArtifact, PlannerSummary
from engine.schemas.timeline import AnalysisMetadata, AnalysisTimeline, SceneSegment


def _sync_submit(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    fn(*args, **kwargs)


def _fake_analysis(*, input_video_path=None, source_url=None, job_id, artifacts_root, **kwargs):  # type: ignore[no-untyped-def]
    artifact_dir = Path(artifacts_root) / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timeline = AnalysisTimeline(
        job_id=job_id,
        source_video=str(input_video_path or source_url or "source.mp4"),
        fps=25.0,
        duration_sec=10.0,
        scenes=[
            SceneSegment(
                scene_id="scene_0000",
                start_frame=0,
                end_frame=249,
                start_sec=0.0,
                end_sec=10.0,
                boundary_score=0.5,
            )
        ],
        metadata=AnalysisMetadata(run_profile="degraded"),
    )
    timeline_path = artifact_dir / "analysis_timeline.json"
    timeline_path.write_text(json.dumps(timeline.model_dump(mode="json")), encoding="utf-8")
    quality = {
        "job_id": job_id,
        "run_profile": "degraded",
        "passed": True,
        "critical_findings": [],
        "warnings": [],
        "next_actions": [],
        "coverage_summary": {"total_scenes": 1, "sampled_scenes": 1},
        "planner_eligible": True,
    }
    (artifact_dir / "analysis_quality_report.json").write_text(json.dumps(quality), encoding="utf-8")
    return timeline, timeline_path


def _fake_plan(*, timeline_path, quality_report_path, output_path=None, **kwargs):  # type: ignore[no-untyped-def]
    timeline = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    job_id = timeline["job_id"]
    resolved_output = Path(output_path or (Path(timeline_path).parent / "edit_plan.json"))
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    plan = EditPlanArtifact(
        job_id=job_id,
        source_video=timeline["source_video"],
        run_profile="degraded",
        summary=PlannerSummary(
            candidate_windows=1,
            planned_actions=1,
            action_counts={"trim_segment": 1},
            max_action_score=0.6,
            avg_confidence=0.6,
        ),
    )
    resolved_output.write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")
    return plan, resolved_output


class JobsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="softcut_jobs_route_")
        self.root = Path(self.temp_dir.name)
        self.artifacts_root = self.root / "artifacts"
        self.download_dir = self.root / "inbox"
        self.work_root = self.root / "work"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("apps.api.routes.jobs.submit_background", new=_sync_submit)
    @patch("apps.api.routes.jobs.build_edit_plan", side_effect=_fake_plan)
    @patch("apps.api.routes.jobs.build_analysis_timeline", side_effect=_fake_analysis)
    def test_url_pipeline_flow_and_results(self, _analysis, _plan) -> None:
        accepted = create_job_from_url(
            CreateUrlJobRequest(
                url="https://example.com/video.mp4",
                pipeline_mode="pipeline",
                job_id="job_url_001",
                artifacts_root=str(self.artifacts_root),
                work_root=str(self.work_root),
                download_dir=str(self.download_dir),
            )
        )
        self.assertEqual(accepted.job_id, "job_url_001")

        status = get_job_status("job_url_001", artifacts_root=str(self.artifacts_root))
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.stage, "done")

        results = get_job_results("job_url_001", artifacts_root=str(self.artifacts_root))
        self.assertIsNotNone(results.analysis_quality)
        self.assertIsNotNone(results.planner_summary)
        self.assertEqual(results.planner_summary.get("planned_actions"), 1)

    @patch("apps.api.routes.jobs.submit_background", new=_sync_submit)
    @patch("apps.api.routes.jobs.build_analysis_timeline", side_effect=_fake_analysis)
    def test_upload_analysis_only_flow(self, _analysis) -> None:
        accepted = _create_job_from_upload_payload(
            file_obj=BytesIO(b"fake-bytes"),
            file_name="clip.mp4",
            pipeline_mode="analysis",
            job_id="job_upload_001",
            artifacts_root=str(self.artifacts_root),
            work_root=str(self.work_root),
            download_dir=str(self.download_dir),
            analysis_config_path="configs/analysis.yaml",
            planner_config_path="configs/planner.yaml",
        )
        self.assertEqual(accepted.job_id, "job_upload_001")
        status = get_job_status("job_upload_001", artifacts_root=str(self.artifacts_root))
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.stage, "done")
        self.assertTrue((self.download_dir / "uploads").exists())

    @patch("apps.api.routes.jobs.submit_background", new=_sync_submit)
    @patch("apps.api.routes.jobs.build_edit_plan", side_effect=_fake_plan)
    def test_planner_only_route(self, _plan) -> None:
        artifact_dir = self.artifacts_root / "job_plan_001"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        timeline = AnalysisTimeline(
            job_id="job_plan_001",
            source_video="source.mp4",
            fps=25.0,
            duration_sec=10.0,
            metadata=AnalysisMetadata(run_profile="degraded"),
        )
        (artifact_dir / "analysis_timeline.json").write_text(
            json.dumps(timeline.model_dump(mode="json")),
            encoding="utf-8",
        )
        (artifact_dir / "analysis_quality_report.json").write_text(
            json.dumps({"planner_eligible": True, "passed": True}),
            encoding="utf-8",
        )

        accepted = queue_planner_only(
            "job_plan_001",
            QueuePlannerRequest(artifacts_root=str(self.artifacts_root)),
        )
        self.assertEqual(accepted.job_id, "job_plan_001")
        status = get_job_status("job_plan_001", artifacts_root=str(self.artifacts_root))
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.stage, "done")

    def test_missing_job_raises_404(self) -> None:
        with self.assertRaises(HTTPException) as status_error:
            get_job_status("does_not_exist", artifacts_root=str(self.artifacts_root))
        self.assertEqual(status_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as results_error:
            get_job_results("does_not_exist", artifacts_root=str(self.artifacts_root))
        self.assertEqual(results_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
