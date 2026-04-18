"""Pluggable secondary visual scorer interface (stub for MVP hardening)."""

from __future__ import annotations

from engine.schemas.timeline import AdapterState, AdapterStatus, VisualFlag


def score_sampled_frames(
    sampled_frames: list[tuple[float, str]],
    *,
    fps: float,
) -> tuple[list[VisualFlag], AdapterStatus]:
    """Secondary scorer placeholder to keep adapter contract stable."""
    _ = sampled_frames
    _ = fps
    return [], AdapterStatus(
        state=AdapterState.unavailable,
        detail="Secondary visual scorer not configured.",
        config={"mode": "stub"},
    )
