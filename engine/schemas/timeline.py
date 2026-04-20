"""Schemas for analysis timeline artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AdapterState(str, Enum):
    """Known availability states for analysis adapters."""

    available = "available"
    unavailable = "unavailable"
    failed = "failed"
    fallback = "fallback"


class AdapterStatus(BaseModel):
    """Runtime status information for one adapter."""

    state: AdapterState
    version: str | None = None
    detail: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SceneBoundary(BaseModel):
    """Canonical fused scene boundary."""

    frame_index: int = Field(ge=0)
    sec: float = Field(ge=0.0)
    fused_score: float = Field(ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)
    component_scores: dict[str, float] = Field(default_factory=dict)


class SceneSegment(BaseModel):
    """Timeline scene segment."""

    scene_id: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    boundary_score: float = Field(ge=0.0, le=1.0, default=0.0)

    @field_validator("end_frame")
    @classmethod
    def _end_frame_not_before_start(cls, value: int, info: Any) -> int:
        start_frame = info.data.get("start_frame")
        if start_frame is not None and value < start_frame:
            raise ValueError("end_frame must be >= start_frame")
        return value

    @field_validator("end_sec")
    @classmethod
    def _end_sec_not_before_start(cls, value: float, info: Any) -> float:
        start_sec = info.data.get("start_sec")
        if start_sec is not None and value < start_sec:
            raise ValueError("end_sec must be >= start_sec")
        return value


class SpeechSegment(BaseModel):
    """Sentence/utterance segment from ASR."""

    segment_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    text: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    speaker: str | None = None


class WordSegment(BaseModel):
    """Word-level segment from ASR alignment."""

    word_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    word: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    speaker: str | None = None


class VisualFlag(BaseModel):
    """Visual safety signal from video-frame analysis."""

    flag_id: str
    sec: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    label: str
    score: float = Field(ge=0.0, le=1.0)
    source: str = "opennsfw2"


class RatingEvidence(BaseModel):
    """Evidence item feeding policy scoring in later pipeline stages."""

    evidence_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    dimension: str
    evidence_type: str
    score: float = Field(ge=0.0, le=1.0)
    references: dict[str, str] = Field(default_factory=dict)


class SafeCutPoint(BaseModel):
    """Candidate low-risk cut anchor around flagged evidence."""

    point_id: str
    sec: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    kind: str
    motion_score: float = Field(ge=0.0, le=1.0, default=0.0)
    speech_density: float = Field(ge=0.0, le=1.0, default=0.0)
    boundary_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    references: dict[str, str] = Field(default_factory=dict)


class EditContextWindow(BaseModel):
    """Edit window with compatibility hints for planner."""

    window_id: str
    evidence_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    pre_pad_sec: float = Field(ge=0.0, default=0.0)
    post_pad_sec: float = Field(ge=0.0, default=0.0)
    overlap_tag: str
    compatible_actions: list[str] = Field(default_factory=list)


class ContinuityFeature(BaseModel):
    """Continuity features around a candidate edit region."""

    feature_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)
    motion_score: float = Field(ge=0.0, le=1.0, default=0.0)
    speech_density: float = Field(ge=0.0, le=1.0, default=0.0)
    scene_proximity_sec: float = Field(ge=0.0, default=0.0)
    boundary_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    references: dict[str, str] = Field(default_factory=dict)


class AnalysisMetadata(BaseModel):
    """Metadata for reproducibility and auditability."""

    schema_version: str = "1.0"
    created_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    detector_configs: dict[str, Any] = Field(default_factory=dict)
    adapter_status: dict[str, AdapterStatus] = Field(default_factory=dict)
    fusion: dict[str, Any] = Field(default_factory=dict)
    run_profile: str = "degraded"
    asr_mode: str = "failed"
    visual_mode: str = "disabled"
    quality_flags: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    step_timings: dict[str, float] = Field(default_factory=dict)
    boundary_quality: dict[str, Any] = Field(default_factory=dict)
    capability_matrix: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class AnalysisTimeline(BaseModel):
    """Top-level timeline artifact."""

    job_id: str
    source_video: str
    fps: float = Field(gt=0.0)
    duration_sec: float = Field(gt=0.0)
    scenes: list[SceneSegment] = Field(default_factory=list)
    speech_segments: list[SpeechSegment] = Field(default_factory=list)
    word_segments: list[WordSegment] = Field(default_factory=list)
    visual_flags: list[VisualFlag] = Field(default_factory=list)
    rating_evidence: list[RatingEvidence] = Field(default_factory=list)
    safe_cut_points: list[SafeCutPoint] = Field(default_factory=list)
    edit_context_windows: list[EditContextWindow] = Field(default_factory=list)
    continuity_features: list[ContinuityFeature] = Field(default_factory=list)
    boundaries: list[SceneBoundary] = Field(default_factory=list)
    metadata: AnalysisMetadata = Field(default_factory=AnalysisMetadata)


class AnalysisQualityReport(BaseModel):
    """Quality verdict for whether Step 1 output is planner-ready."""

    job_id: str
    run_profile: str
    passed: bool
    critical_findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    planner_eligible: bool = False


def frame_to_seconds(frame_index: int, fps: float) -> float:
    """Convert frame index to seconds."""
    if fps <= 0:
        raise ValueError("fps must be > 0")
    return frame_index / fps


def seconds_to_frame(seconds: float, fps: float) -> int:
    """Convert seconds to nearest frame index."""
    if fps <= 0:
        raise ValueError("fps must be > 0")
    return max(0, int(round(seconds * fps)))
