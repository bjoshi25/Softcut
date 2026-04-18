"""OpenNSFW2 adapter for visual risk scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.schemas.timeline import AdapterState, AdapterStatus, VisualFlag


def _to_float(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        return _to_float(value[-1])
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return _to_float(converted)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _predict_image_score(module: Any, image_path: str, model: Any) -> float:
    if hasattr(module, "predict_image"):
        if model is not None:
            return _to_float(module.predict_image(image_path, model=model))
        return _to_float(module.predict_image(image_path))
    if hasattr(module, "predict"):
        if model is not None:
            return _to_float(module.predict(image_path, model=model))
        return _to_float(module.predict(image_path))
    raise AttributeError("OpenNSFW2 prediction API not found.")


def score_sampled_frames(
    sampled_frames: list[tuple[float, str]],
    *,
    fps: float,
    threshold: float = 0.65,
) -> tuple[list[VisualFlag], AdapterStatus]:
    """Score sampled frames and emit visual flags above threshold."""
    config = {
        "threshold": threshold,
        "sample_count": len(sampled_frames),
    }
    try:
        import opennsfw2
    except ModuleNotFoundError:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="OpenNSFW2 not installed.",
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive import boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 import failed: {exc}",
            config=config,
        )

    try:
        model = None
        if hasattr(opennsfw2, "make_open_nsfw_model"):
            model = opennsfw2.make_open_nsfw_model()

        flags: list[VisualFlag] = []
        for index, (time_sec, frame_path) in enumerate(sampled_frames):
            if not Path(frame_path).exists():
                continue
            score = _predict_image_score(opennsfw2, frame_path, model)
            if score < threshold:
                continue
            flags.append(
                VisualFlag(
                    flag_id=f"visual_{index:04d}",
                    sec=max(0.0, time_sec),
                    frame_index=max(0, int(round(time_sec * fps))),
                    label="nsfw_visual",
                    score=max(0.0, min(1.0, score)),
                    source="opennsfw2",
                )
            )
        version = getattr(opennsfw2, "__version__", None)
        return flags, AdapterStatus(
            state=AdapterState.available,
            version=str(version) if version else None,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - adapter runtime boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"OpenNSFW2 runtime failed: {exc}",
            config=config,
        )
