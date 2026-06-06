"""Schemas for planner artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PlannedAction(BaseModel):
    """Deterministic edit action derived from one evidence item/window."""

    action_id: str
    evidence_id: str
    window_id: str | None = None
    action: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: str
    rationale: str
    policy_tags: list[str] = Field(default_factory=list)
    references: dict[str, str] = Field(default_factory=dict)

    @field_validator("end_sec")
    @classmethod
    def _end_not_before_start(cls, value: float, info: Any) -> float:
        start = info.data.get("start_sec")
        if start is not None and value < start:
            raise ValueError("end_sec must be >= start_sec")
        return value


class PlannerSummary(BaseModel):
    """Planner output summary for quick status checks."""

    candidate_windows: int = Field(ge=0, default=0)
    planned_actions: int = Field(ge=0, default=0)
    dropped_low_score: int = Field(ge=0, default=0)
    dropped_missing_context: int = Field(ge=0, default=0)
    action_counts: dict[str, int] = Field(default_factory=dict)
    max_action_score: float = Field(ge=0.0, le=1.0, default=0.0)
    avg_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class EditPlanArtifact(BaseModel):
    """Top-level planner artifact for Step 2."""

    schema_version: str = "1.0"
    created_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    job_id: str
    source_video: str
    run_profile: str = "degraded"
    planner_config: dict[str, Any] = Field(default_factory=dict)
    analysis_inputs: dict[str, str] = Field(default_factory=dict)
    quality_gate: dict[str, Any] = Field(default_factory=dict)
    actions: list[PlannedAction] = Field(default_factory=list)
    summary: PlannerSummary = Field(default_factory=PlannerSummary)
    notes: list[str] = Field(default_factory=list)
