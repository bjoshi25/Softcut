"""Build deterministic edit plans from analysis artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from engine.schemas.planner import EditPlanArtifact, PlannedAction, PlannerSummary
from engine.schemas.timeline import AnalysisQualityReport, AnalysisTimeline

ProgressCallback = Callable[[str], None]

DEFAULT_PLANNER_CONFIG: dict[str, Any] = {
    "planner": {
        "require_planner_eligible": True,
        "min_evidence_score": 0.3,
        "max_actions": 200,
        "allow_remove_scene": False,
        "action_by_evidence_type": {
            "strong_profanity": "beep_word",
            "moderate_profanity": "mute_word",
            "violent_dialogue": "trim_segment",
            "nsfw_visual": "trim_segment",
        },
        "action_fallback_order": [
            "trim_segment",
            "mute_word",
            "beep_word",
            "remove_scene",
        ],
        "profanity_beep_threshold": 0.85,
        "mute_padding_sec": 0.05,
        "beep_padding_sec": 0.03,
        "min_trim_duration_sec": 0.2,
    }
}


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_planner_config(config_path: str) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    path = Path(config_path)
    if not path.exists():
        notes.append(f"planner config missing at {config_path}; using defaults")
        return dict(DEFAULT_PLANNER_CONFIG), notes

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to load planner config files."
        ) from exc

    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"planner config root must be a mapping: {config_path}")
    notes.append(f"planner config loaded from {config_path}")
    return _deep_merge(DEFAULT_PLANNER_CONFIG, loaded), notes


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _risk_level(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _mean(values: list[float], default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _select_action(
    *,
    evidence_type: str,
    evidence_score: float,
    compatible_actions: list[str],
    planner_cfg: dict[str, Any],
) -> str:
    compatible = [str(item).strip() for item in compatible_actions if str(item).strip()]
    if not compatible:
        compatible = ["trim_segment", "mute_word", "beep_word", "remove_scene"]

    action_map = planner_cfg.get("action_by_evidence_type", {})
    mapped = str(action_map.get(evidence_type, "")).strip()
    beep_threshold = float(planner_cfg.get("profanity_beep_threshold", 0.85))
    if evidence_type in {"strong_profanity", "moderate_profanity"} and evidence_score >= beep_threshold:
        mapped = "beep_word"

    allow_remove_scene = bool(planner_cfg.get("allow_remove_scene", False))
    if mapped == "remove_scene" and not allow_remove_scene:
        mapped = "trim_segment"
    if mapped and mapped in compatible:
        return mapped

    for candidate in planner_cfg.get("action_fallback_order", []):
        action = str(candidate).strip()
        if not action:
            continue
        if action == "remove_scene" and not allow_remove_scene:
            continue
        if action in compatible:
            return action

    if mapped:
        return mapped
    return compatible[0]


def _group_by_evidence_id(items: list[Any], *, key_field: str) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for item in items:
        references = getattr(item, "references", None) or {}
        evidence_id = str(references.get(key_field, "")).strip()
        if not evidence_id:
            continue
        grouped.setdefault(evidence_id, []).append(item)
    return grouped


def _pick_cut_sec(points: list[Any], *, kind: str) -> float | None:
    matched = [point for point in points if str(getattr(point, "kind", "")).strip() == kind]
    if not matched:
        return None
    if kind == "pre":
        return max(float(point.sec) for point in matched)
    return min(float(point.sec) for point in matched)


def _resolve_action_window(
    *,
    action: str,
    evidence_start: float,
    evidence_end: float,
    window_start: float,
    window_end: float,
    pre_cut_sec: float | None,
    post_cut_sec: float | None,
    mute_padding_sec: float,
    beep_padding_sec: float,
    min_trim_duration_sec: float,
    duration_sec: float,
) -> tuple[float, float]:
    safe_duration = max(0.0, float(duration_sec))
    if action in {"trim_segment", "remove_scene"}:
        start = pre_cut_sec if pre_cut_sec is not None else window_start
        end = post_cut_sec if post_cut_sec is not None else window_end
        start = max(0.0, min(safe_duration, float(start)))
        end = max(start, min(safe_duration, float(end)))
        min_trim = max(0.0, float(min_trim_duration_sec))
        if end - start < min_trim:
            center = (start + end) / 2.0
            half = min_trim / 2.0
            start = max(0.0, center - half)
            end = min(safe_duration, center + half)
            if end - start < min_trim:
                end = min(safe_duration, start + min_trim)
        return round(start, 6), round(max(start, end), 6)

    pad = float(beep_padding_sec) if action == "beep_word" else float(mute_padding_sec)
    start = max(0.0, evidence_start - max(0.0, pad))
    end = min(safe_duration, max(evidence_end, evidence_start) + max(0.0, pad))
    if end <= start:
        end = min(safe_duration, start + 0.1)
    return round(start, 6), round(max(start, end), 6)


def _build_actions(
    *,
    timeline: AnalysisTimeline,
    planner_cfg: dict[str, Any],
) -> tuple[list[PlannedAction], dict[str, int], int, int]:
    windows_by_evidence_id = {
        window.evidence_id: window for window in timeline.edit_context_windows
    }
    cut_points_by_evidence_id = _group_by_evidence_id(
        timeline.safe_cut_points,
        key_field="evidence_id",
    )
    continuity_by_evidence_id = _group_by_evidence_id(
        timeline.continuity_features,
        key_field="evidence_id",
    )

    min_evidence_score = _clamp01(float(planner_cfg.get("min_evidence_score", 0.3)))
    max_actions = max(1, int(planner_cfg.get("max_actions", 200)))
    mute_padding_sec = max(0.0, float(planner_cfg.get("mute_padding_sec", 0.05)))
    beep_padding_sec = max(0.0, float(planner_cfg.get("beep_padding_sec", 0.03)))
    min_trim_duration_sec = max(0.0, float(planner_cfg.get("min_trim_duration_sec", 0.2)))

    dropped_low_score = 0
    dropped_missing_context = 0
    actions: list[PlannedAction] = []

    ordered_evidence = sorted(
        timeline.rating_evidence,
        key=lambda item: (float(item.start_sec), float(item.end_sec), item.evidence_id),
    )
    for evidence in ordered_evidence:
        if len(actions) >= max_actions:
            break
        if evidence.score < min_evidence_score:
            dropped_low_score += 1
            continue

        window = windows_by_evidence_id.get(evidence.evidence_id)
        if window is None:
            dropped_missing_context += 1
            continue
        compatible_actions = list(window.compatible_actions)
        selected_action = _select_action(
            evidence_type=evidence.evidence_type,
            evidence_score=float(evidence.score),
            compatible_actions=compatible_actions,
            planner_cfg=planner_cfg,
        )

        cut_points = cut_points_by_evidence_id.get(evidence.evidence_id, [])
        pre_cut = _pick_cut_sec(cut_points, kind="pre")
        post_cut = _pick_cut_sec(cut_points, kind="post")
        action_start, action_end = _resolve_action_window(
            action=selected_action,
            evidence_start=float(evidence.start_sec),
            evidence_end=float(evidence.end_sec),
            window_start=float(window.start_sec),
            window_end=float(window.end_sec),
            pre_cut_sec=pre_cut,
            post_cut_sec=post_cut,
            mute_padding_sec=mute_padding_sec,
            beep_padding_sec=beep_padding_sec,
            min_trim_duration_sec=min_trim_duration_sec,
            duration_sec=float(timeline.duration_sec),
        )

        continuity = continuity_by_evidence_id.get(evidence.evidence_id, [])
        boundary_mean = _mean(
            [float(item.boundary_confidence) for item in continuity],
            default=0.5,
        )
        confidence = _clamp01((0.75 * float(evidence.score)) + (0.25 * boundary_mean))
        risk = _risk_level(float(evidence.score))

        references = {
            "window_id": window.window_id,
        }
        if pre_cut is not None:
            references["pre_cut_sec"] = f"{pre_cut:.6f}"
        if post_cut is not None:
            references["post_cut_sec"] = f"{post_cut:.6f}"
        for key, value in evidence.references.items():
            references[str(key)] = str(value)

        actions.append(
            PlannedAction(
                action_id=f"action_{len(actions):04d}",
                evidence_id=evidence.evidence_id,
                window_id=window.window_id,
                action=selected_action,
                start_sec=action_start,
                end_sec=action_end,
                score=round(float(evidence.score), 6),
                confidence=round(float(confidence), 6),
                risk_level=risk,
                rationale=(
                    f"{evidence.evidence_type} ({evidence.dimension}) -> {selected_action}"
                ),
                policy_tags=[evidence.dimension, evidence.evidence_type, risk],
                references=references,
            )
        )

    action_counts: dict[str, int] = {}
    for action in actions:
        action_counts[action.action] = action_counts.get(action.action, 0) + 1
    return actions, action_counts, dropped_low_score, dropped_missing_context


def build_edit_plan(
    *,
    timeline_path: str,
    quality_report_path: str,
    output_path: str | None = None,
    config_path: str = "configs/planner.yaml",
    progress: ProgressCallback | None = None,
) -> tuple[EditPlanArtifact, Path]:
    _emit(progress, "Loading planner config.")
    merged_config, config_notes = _load_planner_config(config_path)
    planner_cfg = merged_config["planner"]

    timeline_file = Path(timeline_path)
    if not timeline_file.exists():
        raise FileNotFoundError(f"analysis timeline not found: {timeline_path}")
    _emit(progress, "Loading analysis timeline artifact.")
    timeline_raw = json.loads(timeline_file.read_text(encoding="utf-8"))
    timeline = AnalysisTimeline.model_validate(timeline_raw)

    quality_file = Path(quality_report_path)
    if not quality_file.exists():
        raise FileNotFoundError(f"analysis quality report not found: {quality_report_path}")
    _emit(progress, "Loading analysis quality report.")
    quality_raw = json.loads(quality_file.read_text(encoding="utf-8"))
    quality_report = AnalysisQualityReport.model_validate(quality_raw)

    require_gate = bool(planner_cfg.get("require_planner_eligible", True))
    if require_gate and not quality_report.planner_eligible:
        raise ValueError(
            "analysis quality report is not planner-eligible; "
            "set planner.require_planner_eligible=false to bypass."
        )

    _emit(progress, "Building deterministic action plan.")
    actions, action_counts, dropped_low_score, dropped_missing_context = _build_actions(
        timeline=timeline,
        planner_cfg=planner_cfg,
    )
    avg_conf = _mean([float(item.confidence) for item in actions], default=0.0)
    max_score = max([float(item.score) for item in actions], default=0.0)

    summary = PlannerSummary(
        candidate_windows=len(timeline.edit_context_windows),
        planned_actions=len(actions),
        dropped_low_score=dropped_low_score,
        dropped_missing_context=dropped_missing_context,
        action_counts=action_counts,
        max_action_score=round(max_score, 6),
        avg_confidence=round(avg_conf, 6),
    )

    gate_summary = {
        "planner_eligible": bool(quality_report.planner_eligible),
        "passed": bool(quality_report.passed),
        "run_profile": quality_report.run_profile,
        "critical_findings": list(quality_report.critical_findings),
        "warnings": list(quality_report.warnings),
    }
    notes = [*config_notes]
    if not quality_report.planner_eligible and not require_gate:
        notes.append("planner gate bypassed by config (require_planner_eligible=false)")

    plan = EditPlanArtifact(
        job_id=timeline.job_id,
        source_video=timeline.source_video,
        run_profile=str(timeline.metadata.run_profile or quality_report.run_profile),
        planner_config=planner_cfg,
        analysis_inputs={
            "analysis_timeline": str(timeline_file),
            "analysis_quality_report": str(quality_file),
        },
        quality_gate=gate_summary,
        actions=actions,
        summary=summary,
        notes=notes,
    )

    if output_path is None:
        resolved_output = timeline_file.parent / "edit_plan.json"
    else:
        resolved_output = Path(output_path)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    _emit(progress, f"Edit plan written ({len(actions)} actions).")
    return plan, resolved_output


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build edit plan from analysis artifacts.")
    parser.add_argument(
        "--timeline",
        required=True,
        help="Path to analysis_timeline.json artifact.",
    )
    parser.add_argument(
        "--quality-report",
        required=True,
        help="Path to analysis_quality_report.json artifact.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for edit plan JSON. Defaults to sibling edit_plan.json.",
    )
    parser.add_argument(
        "--config",
        default="configs/planner.yaml",
        help="Planner YAML config path.",
    )
    return parser


def main() -> None:
    class _StepPrinter:
        def __init__(self) -> None:
            self.step = 0

        def __call__(self, message: str) -> None:
            self.step += 1
            print(f"[step {self.step:02d}] {message}", flush=True)

    args = _build_cli().parse_args()
    step_printer = _StepPrinter()
    step_printer("Starting planner pipeline.")
    plan, output_path = build_edit_plan(
        timeline_path=args.timeline,
        quality_report_path=args.quality_report,
        output_path=args.output,
        config_path=args.config,
        progress=step_printer,
    )
    step_printer("Planner completed.")
    print(f"edit_plan: {output_path}")
    print(f"job_id: {plan.job_id}")
    print(f"planned_actions: {len(plan.actions)}")
    print(f"candidate_windows: {plan.summary.candidate_windows}")


if __name__ == "__main__":
    main()
