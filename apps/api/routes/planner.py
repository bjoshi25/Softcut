"""Local planner job routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.planning.build_plan import build_edit_plan

router = APIRouter(prefix="/planner", tags=["planner"])


class LocalPlannerJobRequest(BaseModel):
    """Create a local planner job from existing analysis artifacts."""

    job_id: str = Field(..., description="Job identifier.")
    artifacts_root: str = Field(
        default="artifacts",
        description="Artifact root containing analysis outputs.",
    )
    timeline_path: str | None = Field(
        default=None,
        description="Optional explicit analysis timeline path.",
    )
    quality_report_path: str | None = Field(
        default=None,
        description="Optional explicit analysis quality report path.",
    )
    output_path: str | None = Field(
        default=None,
        description="Optional explicit edit plan output path.",
    )
    config_path: str = Field(
        default="configs/planner.yaml",
        description="Planner config path.",
    )


class LocalPlannerJobResponse(BaseModel):
    """Response payload for planner job creation."""

    job_id: str
    plan_path: str
    planned_actions_count: int
    candidate_windows_count: int


@router.post("/jobs/local", response_model=LocalPlannerJobResponse)
def create_local_planner_job(payload: LocalPlannerJobRequest) -> LocalPlannerJobResponse:
    """Run planner pipeline and write plan artifact for an existing analysis job."""
    artifact_dir = Path(payload.artifacts_root) / payload.job_id
    timeline_path = payload.timeline_path or str(artifact_dir / "analysis_timeline.json")
    quality_report_path = payload.quality_report_path or str(
        artifact_dir / "analysis_quality_report.json"
    )
    output_path = payload.output_path or str(artifact_dir / "edit_plan.json")

    try:
        plan, resolved_output = build_edit_plan(
            timeline_path=timeline_path,
            quality_report_path=quality_report_path,
            output_path=output_path,
            config_path=payload.config_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - API boundary
        raise HTTPException(status_code=500, detail=f"planner failed: {exc}") from exc

    return LocalPlannerJobResponse(
        job_id=plan.job_id,
        plan_path=str(resolved_output),
        planned_actions_count=len(plan.actions),
        candidate_windows_count=plan.summary.candidate_windows,
    )
