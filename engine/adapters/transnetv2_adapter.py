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
    try:
        module = importlib.import_module("transnetv2")
        version = getattr(module, "__version__", None)
        model_class = getattr(module, "TransNetV2", None)
        if model_class is not None:
            return model_class, str(version) if version else None

        nested_module = importlib.import_module("transnetv2.transnetv2")
        nested_version = getattr(nested_module, "__version__", None) or version
        nested_class = getattr(nested_module, "TransNetV2", None)
        if nested_class is not None:
            return nested_class, str(nested_version) if nested_version else None
    except ModuleNotFoundError:
        pass

    # Fallback to the PyPI implementation when official module is not installed.
    alt_module = importlib.import_module("transnetv2_pytorch")
    alt_version = getattr(alt_module, "__version__", None)
    alt_class = getattr(alt_module, "TransNetV2", None)
    return alt_class, str(alt_version) if alt_version else None


def _is_git_lfs_pointer(path: str | Path) -> bool:
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size > 1024:
        return False
    try:
        head = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "git-lfs.github.com/spec/v1" in head


def _extract_prediction_track(prediction_output: Any) -> list[float]:
    if prediction_output is None:
        return []
    if isinstance(prediction_output, tuple):
        if len(prediction_output) >= 2:
            return _flatten_predictions(prediction_output[1])
        return _flatten_predictions(prediction_output[0])
    return _flatten_predictions(prediction_output)


def _extract_boundaries_from_detect_scenes(
    scenes_output: Any,
) -> list[BoundaryCandidate]:
    if not isinstance(scenes_output, list):
        return []

    boundaries: list[BoundaryCandidate] = []
    for index, scene in enumerate(scenes_output):
        start_frame = None
        score = 0.8
        if isinstance(scene, dict):
            for key in ("start_frame", "start", "frame_start", "start_idx"):
                value = scene.get(key)
                if isinstance(value, (int, float)):
                    start_frame = int(value)
                    break
            confidence = scene.get("confidence")
            if isinstance(confidence, (int, float)):
                score = float(confidence)
        elif isinstance(scene, (tuple, list)) and scene:
            first = scene[0]
            if isinstance(first, (int, float)):
                start_frame = int(first)
        if start_frame is None:
            continue
        if index == 0 and start_frame <= 0:
            continue
        boundaries.append(
            BoundaryCandidate(
                frame_index=max(0, start_frame),
                score=max(0.0, min(1.0, score)),
                source="transnetv2",
            )
        )
    return boundaries


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
    model_dir: str | None = None,
) -> tuple[list[BoundaryCandidate], AdapterStatus]:
    """Detect shot boundaries with TransNetV2 if installed."""
    config = {
        "threshold": threshold,
        "min_gap_frames": min_gap_frames,
        "model_dir": model_dir,
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
        model_kwargs: dict[str, Any] = {}
        if model_dir:
            model_kwargs["model_dir"] = model_dir
        elif model_class.__module__.startswith("transnetv2"):
            default_saved_model = (
                Path(importlib.import_module("transnetv2").__file__).parent
                / "transnetv2-weights"
                / "saved_model.pb"
            )
            if _is_git_lfs_pointer(default_saved_model):
                # Prefer a usable fallback implementation when official package weights are pointers.
                try:
                    alt_module = importlib.import_module("transnetv2_pytorch")
                    alt_class = getattr(alt_module, "TransNetV2", None)
                    if alt_class is not None:
                        model_class = alt_class
                        version = str(getattr(alt_module, "__version__", None) or version)
                except ModuleNotFoundError:
                    return [], AdapterStatus(
                        state=AdapterState.unavailable,
                        detail=(
                            "TransNetV2 weights are Git LFS pointer files, not real model weights. "
                            "Install with Git LFS or set adapters.transnetv2.model_dir to a valid "
                            "weights directory containing saved_model.pb and variables/."
                        ),
                        version=version,
                        config=config,
                    )

        model = model_class(**model_kwargs)
        boundaries: list[BoundaryCandidate] = []
        if hasattr(model, "predict_video"):
            prediction_output = model.predict_video(str(video_path))
            prediction_track = _extract_prediction_track(prediction_output)
            boundaries = _predictions_to_boundaries(
                prediction_track,
                threshold=threshold,
                min_gap_frames=min_gap_frames,
            )
        elif hasattr(model, "detect_scenes"):
            scenes_output = model.detect_scenes(str(video_path), threshold=threshold)
            boundaries = _extract_boundaries_from_detect_scenes(scenes_output)
        else:
            return [], AdapterStatus(
                state=AdapterState.unavailable,
                detail="TransNetV2 runtime does not expose predict_video or detect_scenes.",
                version=version,
                config=config,
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
