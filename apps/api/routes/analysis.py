"""Local analysis job routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.analysis.build_timeline import build_analysis_timeline

router = APIRouter(prefix="/analysis", tags=["analysis"])


class LocalAnalysisJobRequest(BaseModel):
    """Create a local analysis job from an existing video path."""

    input_video_path: str = Field(
        ...,
        description="Path to a local video file (e.g. data/inbox/input.mp4).",
    )
    job_id: str = Field(..., description="Job identifier.")
    artifacts_root: str = "artifacts"
    work_root: str = "data/work"
    diarize: bool | None = None
    overwrite_job_artifacts: bool | None = None
    prune_other_artifacts: bool | None = None
    keep_artifact_jobs: int | None = None
    config_path: str = "configs/analysis.yaml"


class LocalAnalysisJobResponse(BaseModel):
    """Response payload for local analysis job creation."""

    job_id: str
    artifact_path: str
    fps: float
    duration_sec: float
    scenes_count: int
    speech_segments_count: int
    word_segments_count: int
    visual_flags_count: int


@router.post("/jobs/local", response_model=LocalAnalysisJobResponse)
def create_local_analysis_job(payload: LocalAnalysisJobRequest) -> LocalAnalysisJobResponse:
    """Run analysis pipeline and write artifacts for a local file."""
    try:
        timeline, output_path = build_analysis_timeline(
            input_video_path=payload.input_video_path,
            job_id=payload.job_id,
            artifacts_root=payload.artifacts_root,
            work_root=payload.work_root,
            diarize=payload.diarize,
            overwrite_job_artifacts=payload.overwrite_job_artifacts,
            prune_other_artifacts=payload.prune_other_artifacts,
            keep_artifact_jobs=payload.keep_artifact_jobs,
            config_path=payload.config_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - API boundary
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}") from exc

    return LocalAnalysisJobResponse(
        job_id=timeline.job_id,
        artifact_path=str(output_path),
        fps=timeline.fps,
        duration_sec=timeline.duration_sec,
        scenes_count=len(timeline.scenes),
        speech_segments_count=len(timeline.speech_segments),
        word_segments_count=len(timeline.word_segments),
        visual_flags_count=len(timeline.visual_flags),
    )
