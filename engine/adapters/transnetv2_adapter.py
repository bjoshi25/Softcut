"""TransNetV2 adapter for shot-boundary proposals."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from engine.fusion.boundary_fusion import BoundaryCandidate
from engine.schemas.timeline import AdapterState, AdapterStatus


def _flatten_predictions(values: Any) -> list[float]:
    if values is None:
        return []
    if hasattr(values, "flatten"):
        flattened = values.flatten()
        if hasattr(flattened, "tolist"):
            return [float(item) for item in flattened.tolist()]
    if isinstance(values, (list, tuple)):
        if values and isinstance(values[0], (list, tuple)):
            output: list[float] = []
            for row in values:
                output.extend(float(item) for item in row)
            return output
        return [float(item) for item in values]
    return []


def _resolve_transnet_class() -> tuple[type[Any] | None, str | None]:
    module = importlib.import_module("transnetv2")
    version = getattr(module, "__version__", None)
    model_class = getattr(module, "TransNetV2", None)
    if model_class is not None:
        return model_class, str(version) if version else None

    nested_module = importlib.import_module("transnetv2.transnetv2")
    nested_version = getattr(nested_module, "__version__", None) or version
    nested_class = getattr(nested_module, "TransNetV2", None)
    return nested_class, str(nested_version) if nested_version else None


def _extract_prediction_track(prediction_output: Any) -> list[float]:
    if prediction_output is None:
        return []
    if isinstance(prediction_output, tuple):
        if len(prediction_output) >= 2:
            return _flatten_predictions(prediction_output[1])
        return _flatten_predictions(prediction_output[0])
    return _flatten_predictions(prediction_output)


def _predictions_to_boundaries(
    predictions: list[float],
    *,
    threshold: float,
    min_gap_frames: int,
) -> list[BoundaryCandidate]:
    if not predictions:
        return []
    candidates: list[BoundaryCandidate] = []
    previous_kept = -10_000_000
    for index, score in enumerate(predictions):
        left = predictions[index - 1] if index > 0 else score
        right = predictions[index + 1] if index < len(predictions) - 1 else score
        if score < threshold:
            continue
        if score < left or score < right:
            continue
        if index - previous_kept < min_gap_frames:
            if candidates and score > candidates[-1].score:
                candidates[-1] = BoundaryCandidate(
                    frame_index=index,
                    score=max(0.0, min(1.0, score)),
                    source="transnetv2",
                )
                previous_kept = index
            continue
        candidates.append(
            BoundaryCandidate(
                frame_index=index,
                score=max(0.0, min(1.0, score)),
                source="transnetv2",
            )
        )
        previous_kept = index
    return candidates


def detect_boundaries(
    video_path: str | Path,
    *,
    threshold: float = 0.5,
    min_gap_frames: int = 4,
) -> tuple[list[BoundaryCandidate], AdapterStatus]:
    """Detect shot boundaries with TransNetV2 if installed."""
    config = {
        "threshold": threshold,
        "min_gap_frames": min_gap_frames,
    }
    try:
        model_class, version = _resolve_transnet_class()
    except ModuleNotFoundError:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="TransNetV2 not installed.",
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"TransNetV2 import failed: {exc}",
            config=config,
        )

    if model_class is None:
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail="TransNetV2 class not found.",
            config=config,
        )

    try:
        model = model_class()
        prediction_output = model.predict_video(str(video_path))
        prediction_track = _extract_prediction_track(prediction_output)
        boundaries = _predictions_to_boundaries(
            prediction_track,
            threshold=threshold,
            min_gap_frames=min_gap_frames,
        )
        return boundaries, AdapterStatus(
            state=AdapterState.available,
            version=version,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - adapter runtime boundary
        return [], AdapterStatus(
            state=AdapterState.unavailable,
            detail=f"TransNetV2 runtime failed: {exc}",
            config=config,
        )
