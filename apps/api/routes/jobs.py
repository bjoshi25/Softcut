"""Async job orchestration routes for analysis + planner pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.jobs_runtime import JobStore, safe_job_id, submit_background
from engine.analysis.build_timeline import build_analysis_timeline
from engine.planning.build_plan import build_edit_plan

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateUrlJobRequest(BaseModel):
    """Create an async job from URL source."""

    url: str = Field(..., description="Video URL to analyze.")
    pipeline_mode: str = Field(default="pipeline", description="pipeline | analysis")
    job_id: str | None = Field(default=None, description="Optional explicit job identifier.")
    artifacts_root: str = "artifacts"
    work_root: str = "data/work"
    download_dir: str = "data/inbox"
    analysis_config_path: str = "configs/analysis.yaml"
    planner_config_path: str = "configs/planner.yaml"


class QueuePlannerRequest(BaseModel):
    """Queue planner-only run for an existing analysis job."""

    artifacts_root: str = "artifacts"
    planner_config_path: str = "configs/planner.yaml"


class JobAcceptedResponse(BaseModel):
    """Accepted async job response."""

    job_id: str
    pipeline_mode: str
    status: str
    stage: str
    message: str
    artifacts: dict[str, str]


class JobStatusResponse(BaseModel):
    """Job status payload."""

    job_id: str
    pipeline_mode: str
    status: str
    stage: str
    message: str
    created_at_utc: str
    started_at_utc: str | None = None
    updated_at_utc: str
    completed_at_utc: str | None = None
    artifacts: dict[str, str]
    error: str | None = None


class JobResultsResponse(BaseModel):
    """Compact results payload for UI rendering."""

    job_id: str
    status: str
    stage: str
    artifacts: dict[str, str]
    analysis_quality: dict[str, Any] | None = None
    coverage_summary: dict[str, Any] | None = None
    planner_summary: dict[str, Any] | None = None
    planned_actions: list[dict[str, Any]] = Field(default_factory=list)


def _job_id_or_new(raw_job_id: str | None) -> str:
    if raw_job_id is None:
        return f"job_{uuid4().hex[:12]}"
    normalized = safe_job_id(raw_job_id)
    if not normalized:
        raise ValueError("job_id must contain at least one alphanumeric character")
    return normalized


def _artifact_paths(*, artifacts_root: str, job_id: str) -> dict[str, str]:
    base = Path(artifacts_root) / job_id
    return {
        "analysis_timeline": str(base / "analysis_timeline.json"),
        "analysis_quality_report": str(base / "analysis_quality_report.json"),
        "edit_plan": str(base / "edit_plan.json"),
    }


def _queue_job_or_conflict(store: JobStore, *, job_id: str, pipeline_mode: str, artifacts: dict[str, str]) -> dict[str, Any]:
    existing = store.read(job_id)
    if existing is not None and existing.get("status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail=f"job already running: {job_id}")
    return store.create_or_replace(job_id=job_id, pipeline_mode=pipeline_mode, artifacts=artifacts)


def _on_progress(store: JobStore, job_id: str, *, stage: str) -> Any:
    def _callback(message: str) -> None:
        store.patch(job_id, status="running", stage=stage, message=str(message))

    return _callback


def _run_analysis_and_maybe_planner(
    *,
    store: JobStore,
    job_id: str,
    pipeline_mode: str,
    source_url: str | None,
    input_video_path: str | None,
    artifacts_root: str,
    work_root: str,
    download_dir: str,
    analysis_config_path: str,
    planner_config_path: str,
) -> None:
    try:
        store.patch(job_id, status="running", stage="analysis", message="Starting analysis.")
        timeline, output_path = build_analysis_timeline(
            input_video_path=input_video_path,
            source_url=source_url,
            job_id=job_id,
            artifacts_root=artifacts_root,
            work_root=work_root,
            download_dir=download_dir,
            config_path=analysis_config_path,
            progress=_on_progress(store, job_id, stage="analysis"),
        )
        store.patch(
            job_id,
            status="running",
            stage="analysis",
            message=f"Analysis completed (scenes={len(timeline.scenes)}).",
            artifacts={
                **(store.read(job_id) or {}).get("artifacts", {}),
                "analysis_timeline": str(output_path),
                "analysis_quality_report": str(output_path.parent / "analysis_quality_report.json"),
            },
        )
        if pipeline_mode == "analysis":
            store.patch(job_id, status="completed", stage="done", message="Analysis job completed.")
            return

        store.patch(job_id, status="running", stage="planner", message="Starting planner.")
        plan, plan_path = build_edit_plan(
            timeline_path=str(output_path),
            quality_report_path=str(output_path.parent / "analysis_quality_report.json"),
            output_path=str(output_path.parent / "edit_plan.json"),
            config_path=planner_config_path,
            progress=_on_progress(store, job_id, stage="planner"),
        )
        store.patch(
            job_id,
            status="completed",
            stage="done",
            message=f"Pipeline completed (actions={len(plan.actions)}).",
            artifacts={
                **(store.read(job_id) or {}).get("artifacts", {}),
                "edit_plan": str(plan_path),
            },
        )
    except Exception as exc:  # pragma: no cover - async runtime boundary
        store.patch(job_id, status="failed", stage="failed", message="Job failed.", error=str(exc))


def _run_planner_only(
    *,
    store: JobStore,
    job_id: str,
    artifacts_root: str,
    planner_config_path: str,
) -> None:
    try:
        artifact_dir = Path(artifacts_root) / job_id
        timeline_path = artifact_dir / "analysis_timeline.json"
        quality_path = artifact_dir / "analysis_quality_report.json"
        store.patch(job_id, status="running", stage="planner", message="Starting planner.")
        plan, plan_path = build_edit_plan(
            timeline_path=str(timeline_path),
            quality_report_path=str(quality_path),
            output_path=str(artifact_dir / "edit_plan.json"),
            config_path=planner_config_path,
            progress=_on_progress(store, job_id, stage="planner"),
        )
        store.patch(
            job_id,
            status="completed",
            stage="done",
            message=f"Planner completed (actions={len(plan.actions)}).",
            artifacts={
                **(store.read(job_id) or {}).get("artifacts", {}),
                "edit_plan": str(plan_path),
            },
        )
    except Exception as exc:  # pragma: no cover - async runtime boundary
        store.patch(job_id, status="failed", stage="failed", message="Planner failed.", error=str(exc))


@router.post("/from-url", response_model=JobAcceptedResponse)
def create_job_from_url(payload: CreateUrlJobRequest) -> JobAcceptedResponse:
    pipeline_mode = str(payload.pipeline_mode or "pipeline").strip().lower()
    if pipeline_mode not in {"pipeline", "analysis"}:
        raise HTTPException(status_code=400, detail="pipeline_mode must be pipeline or analysis")
    url = str(payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    job_id = _job_id_or_new(payload.job_id)
    store = JobStore(artifacts_root=Path(payload.artifacts_root))
    artifacts = _artifact_paths(artifacts_root=payload.artifacts_root, job_id=job_id)
    job = _queue_job_or_conflict(store, job_id=job_id, pipeline_mode=pipeline_mode, artifacts=artifacts)

    submit_background(
        _run_analysis_and_maybe_planner,
        store=store,
        job_id=job_id,
        pipeline_mode=pipeline_mode,
        source_url=url,
        input_video_path=None,
        artifacts_root=payload.artifacts_root,
        work_root=payload.work_root,
        download_dir=payload.download_dir,
        analysis_config_path=payload.analysis_config_path,
        planner_config_path=payload.planner_config_path,
    )
    return JobAcceptedResponse(**job)


def _create_job_from_upload_payload(
    *,
    file_obj: Any,
    file_name: str,
    pipeline_mode: str,
    job_id: str | None,
    artifacts_root: str,
    work_root: str,
    download_dir: str,
    analysis_config_path: str,
    planner_config_path: str,
) -> JobAcceptedResponse:
    resolved_mode = str(pipeline_mode or "pipeline").strip().lower()
    if resolved_mode not in {"pipeline", "analysis"}:
        raise HTTPException(status_code=400, detail="pipeline_mode must be pipeline or analysis")
    resolved_job_id = _job_id_or_new(job_id)
    filename = Path(file_name or "upload.mp4").name
    upload_dir = Path(download_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{resolved_job_id}_{filename}"
    with upload_path.open("wb") as out:
        shutil.copyfileobj(file_obj, out)

    store = JobStore(artifacts_root=Path(artifacts_root))
    artifacts = {
        **_artifact_paths(artifacts_root=artifacts_root, job_id=resolved_job_id),
        "source_video": str(upload_path),
    }
    job = _queue_job_or_conflict(
        store,
        job_id=resolved_job_id,
        pipeline_mode=resolved_mode,
        artifacts=artifacts,
    )
    store.patch(
        resolved_job_id,
        status="queued",
        stage="ingest",
        message="Upload received; job queued for analysis.",
    )

    submit_background(
        _run_analysis_and_maybe_planner,
        store=store,
        job_id=resolved_job_id,
        pipeline_mode=resolved_mode,
        source_url=None,
        input_video_path=str(upload_path),
        artifacts_root=artifacts_root,
        work_root=work_root,
        download_dir=download_dir,
        analysis_config_path=analysis_config_path,
        planner_config_path=planner_config_path,
    )
    return JobAcceptedResponse(**(store.read(resolved_job_id) or job))


@router.post("/from-upload", response_model=JobAcceptedResponse)
async def create_job_from_upload(request: Request) -> JobAcceptedResponse:
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"multipart form parsing failed: {exc}",
        ) from exc
    file = form.get("file")
    if file is None:
        raise HTTPException(status_code=400, detail="file is required")
    file_obj = getattr(file, "file", None)
    if file_obj is None:
        raise HTTPException(status_code=400, detail="invalid file payload")

    return _create_job_from_upload_payload(
        file_obj=file_obj,
        file_name=str(getattr(file, "filename", "") or "upload.mp4"),
        pipeline_mode=str(form.get("pipeline_mode") or "pipeline"),
        job_id=(str(form.get("job_id")) if form.get("job_id") else None),
        artifacts_root=str(form.get("artifacts_root") or "artifacts"),
        work_root=str(form.get("work_root") or "data/work"),
        download_dir=str(form.get("download_dir") or "data/inbox"),
        analysis_config_path=str(form.get("analysis_config_path") or "configs/analysis.yaml"),
        planner_config_path=str(form.get("planner_config_path") or "configs/planner.yaml"),
    )


@router.post("/{job_id}/planner", response_model=JobAcceptedResponse)
def queue_planner_only(job_id: str, payload: QueuePlannerRequest) -> JobAcceptedResponse:
    resolved_job_id = _job_id_or_new(job_id)
    artifact_dir = Path(payload.artifacts_root) / resolved_job_id
    if not (artifact_dir / "analysis_timeline.json").exists():
        raise HTTPException(status_code=404, detail=f"analysis_timeline not found for {resolved_job_id}")
    if not (artifact_dir / "analysis_quality_report.json").exists():
        raise HTTPException(status_code=404, detail=f"analysis_quality_report not found for {resolved_job_id}")

    store = JobStore(artifacts_root=Path(payload.artifacts_root))
    artifacts = _artifact_paths(artifacts_root=payload.artifacts_root, job_id=resolved_job_id)
    job = _queue_job_or_conflict(store, job_id=resolved_job_id, pipeline_mode="planner", artifacts=artifacts)
    submit_background(
        _run_planner_only,
        store=store,
        job_id=resolved_job_id,
        artifacts_root=payload.artifacts_root,
        planner_config_path=payload.planner_config_path,
    )
    return JobAcceptedResponse(**job)


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, artifacts_root: str = "artifacts") -> JobStatusResponse:
    resolved_job_id = _job_id_or_new(job_id)
    store = JobStore(artifacts_root=Path(artifacts_root))
    manifest = store.read(resolved_job_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"job not found: {resolved_job_id}")
    return JobStatusResponse(**manifest)


@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: str, artifacts_root: str = "artifacts") -> JobResultsResponse:
    resolved_job_id = _job_id_or_new(job_id)
    store = JobStore(artifacts_root=Path(artifacts_root))
    manifest = store.read(resolved_job_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"job not found: {resolved_job_id}")

    artifacts = dict(manifest.get("artifacts") or {})
    analysis_quality = None
    coverage_summary = None
    planner_summary = None
    planned_actions: list[dict[str, Any]] = []

    quality_path = Path(artifacts.get("analysis_quality_report", ""))
    if quality_path.exists():
        quality_payload = json.loads(quality_path.read_text(encoding="utf-8"))
        analysis_quality = {
            "passed": bool(quality_payload.get("passed")),
            "planner_eligible": bool(quality_payload.get("planner_eligible")),
            "warnings": list(quality_payload.get("warnings") or []),
            "critical_findings": list(quality_payload.get("critical_findings") or []),
        }
        coverage_summary = quality_payload.get("coverage_summary")

    plan_path = Path(artifacts.get("edit_plan", ""))
    if plan_path.exists():
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
        planner_summary = dict(plan_payload.get("summary") or {})
        planned_actions = list(plan_payload.get("actions") or [])

    return JobResultsResponse(
        job_id=resolved_job_id,
        status=str(manifest.get("status") or "queued"),
        stage=str(manifest.get("stage") or "queued"),
        artifacts=artifacts,
        analysis_quality=analysis_quality,
        coverage_summary=coverage_summary,
        planner_summary=planner_summary,
        planned_actions=planned_actions,
    )
