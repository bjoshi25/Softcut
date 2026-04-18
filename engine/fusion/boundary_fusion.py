"""Confidence-weighted temporal boundary fusion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BoundaryCandidate:
    """One detector-proposed boundary."""

    frame_index: int
    score: float
    source: str


@dataclass(slots=True)
class CanonicalBoundary:
    """Fused canonical boundary."""

    frame_index: int
    fused_score: float
    sources: list[str]
    component_scores: dict[str, float]


@dataclass(slots=True)
class BoundaryFusionConfig:
    """Fusion hyperparameters for Step 1."""

    cluster_tolerance_frames: int = 8
    nms_window_frames: int = 8


def _cluster_candidates(
    candidates: list[BoundaryCandidate],
    *,
    tolerance_frames: int,
) -> list[list[BoundaryCandidate]]:
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda item: item.frame_index)
    clusters: list[list[BoundaryCandidate]] = [[ordered[0]]]
    for candidate in ordered[1:]:
        cluster = clusters[-1]
        if abs(candidate.frame_index - cluster[-1].frame_index) <= tolerance_frames:
            cluster.append(candidate)
        else:
            clusters.append([candidate])
    return clusters


def _agreement_bonus(cluster: list[BoundaryCandidate]) -> float:
    sources = {item.source for item in cluster}
    return 1.0 if {"transnetv2", "pyscenedetect"}.issubset(sources) else 0.0


def _cluster_representative_frame(cluster: list[BoundaryCandidate]) -> int:
    weighted_sum = 0.0
    total_weight = 0.0
    for item in cluster:
        weight = max(0.01, item.score)
        weighted_sum += item.frame_index * weight
        total_weight += weight
    if total_weight <= 0:
        return cluster[len(cluster) // 2].frame_index
    return int(round(weighted_sum / total_weight))


def _to_canonical_boundary(
    cluster: list[BoundaryCandidate],
    *,
    local_delta_score: float,
) -> CanonicalBoundary:
    transnet_score = max(
        (item.score for item in cluster if item.source == "transnetv2"),
        default=0.0,
    )
    pyscene_score = max(
        (item.score for item in cluster if item.source == "pyscenedetect"),
        default=0.0,
    )
    agreement = _agreement_bonus(cluster)
    fused_score = (
        0.45 * transnet_score
        + 0.25 * pyscene_score
        + 0.20 * agreement
        + 0.10 * local_delta_score
    )
    frame_index = _cluster_representative_frame(cluster)
    sources = sorted({item.source for item in cluster})
    return CanonicalBoundary(
        frame_index=frame_index,
        fused_score=max(0.0, min(1.0, fused_score)),
        sources=sources,
        component_scores={
            "transnet_score": round(transnet_score, 6),
            "pyscene_score": round(pyscene_score, 6),
            "agreement_bonus": round(agreement, 6),
            "local_frame_delta_score": round(local_delta_score, 6),
        },
    )


def _temporal_nms(
    boundaries: list[CanonicalBoundary],
    *,
    nms_window_frames: int,
) -> list[CanonicalBoundary]:
    if not boundaries:
        return []

    selected: list[CanonicalBoundary] = []
    for boundary in sorted(boundaries, key=lambda item: item.fused_score, reverse=True):
        keep = True
        for already_selected in selected:
            if abs(boundary.frame_index - already_selected.frame_index) <= nms_window_frames:
                keep = False
                break
        if keep:
            selected.append(boundary)
    return sorted(selected, key=lambda item: item.frame_index)


def fuse_boundaries(
    *,
    transnet_boundaries: list[BoundaryCandidate],
    pyscene_boundaries: list[BoundaryCandidate],
    local_frame_delta_scores_by_frame: dict[int, float],
    config: BoundaryFusionConfig | None = None,
) -> list[CanonicalBoundary]:
    """Fuse boundary candidates into one canonical set."""
    cfg = config or BoundaryFusionConfig()
    all_candidates = [*transnet_boundaries, *pyscene_boundaries]
    if not all_candidates:
        return []

    clusters = _cluster_candidates(
        all_candidates, tolerance_frames=cfg.cluster_tolerance_frames
    )
    canonical_candidates: list[CanonicalBoundary] = []
    for cluster in clusters:
        representative_frame = _cluster_representative_frame(cluster)
        local_delta = local_frame_delta_scores_by_frame.get(representative_frame)
        if local_delta is None:
            cluster_scores = [
                local_frame_delta_scores_by_frame[item.frame_index]
                for item in cluster
                if item.frame_index in local_frame_delta_scores_by_frame
            ]
            if cluster_scores:
                local_delta = sum(cluster_scores) / len(cluster_scores)
            elif local_frame_delta_scores_by_frame:
                nearest_frame = min(
                    local_frame_delta_scores_by_frame.keys(),
                    key=lambda frame: abs(frame - representative_frame),
                )
                local_delta = local_frame_delta_scores_by_frame[nearest_frame]
            else:
                local_delta = 0.0
        canonical = _to_canonical_boundary(cluster, local_delta_score=local_delta)
        canonical_candidates.append(canonical)
    return _temporal_nms(canonical_candidates, nms_window_frames=cfg.nms_window_frames)
