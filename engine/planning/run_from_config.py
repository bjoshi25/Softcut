"""Run planner pipeline from project-level YAML config."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from engine.planning.build_plan import build_edit_plan


def _load_yaml(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to load config files.") from exc

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return raw


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Softcut planner from configs/project.yaml."
    )
    parser.add_argument(
        "--config",
        default="configs/project.yaml",
        help="Project config YAML path.",
    )
    return parser


class _StepPrinter:
    def __init__(self) -> None:
        self.step = 0

    def __call__(self, message: str) -> None:
        self.step += 1
        print(f"[step {self.step:02d}] {message}", flush=True)


def _timeline_and_quality_paths(
    *,
    job_id: str,
    artifacts_root: str,
    settings_cfg: dict[str, Any],
) -> tuple[str, str]:
    explicit_timeline = str(settings_cfg.get("timeline_path") or "").strip()
    explicit_quality = str(settings_cfg.get("quality_report_path") or "").strip()
    if explicit_timeline and explicit_quality:
        return explicit_timeline, explicit_quality

    artifact_dir = Path(artifacts_root) / job_id
    timeline_path = (
        explicit_timeline if explicit_timeline else str(artifact_dir / "analysis_timeline.json")
    )
    quality_path = (
        explicit_quality
        if explicit_quality
        else str(artifact_dir / "analysis_quality_report.json")
    )
    return timeline_path, quality_path


def main() -> None:
    args = _build_cli().parse_args()
    root = _load_yaml(args.config)

    analysis_run = root.get("analysis_run") or {}
    planner_run = root.get("planner_run") or {}
    if not isinstance(analysis_run, dict) or not isinstance(planner_run, dict):
        raise ValueError("analysis_run and planner_run must be mappings")

    planner_paths = planner_run.get("paths") or {}
    planner_settings = planner_run.get("settings") or {}
    analysis_paths = analysis_run.get("paths") or {}
    if not isinstance(planner_paths, dict) or not isinstance(planner_settings, dict):
        raise ValueError("planner_run.paths/settings must be mappings")

    job_id = str(
        planner_run.get("job_id")
        or analysis_run.get("job_id")
        or ""
    ).strip()
    if not job_id:
        raise ValueError("planner_run.job_id (or analysis_run.job_id fallback) is required")

    artifacts_root = str(
        planner_paths.get("artifacts_root")
        or analysis_paths.get("artifacts_root")
        or "artifacts"
    )
    timeline_path, quality_report_path = _timeline_and_quality_paths(
        job_id=job_id,
        artifacts_root=artifacts_root,
        settings_cfg=planner_settings,
    )
    output_name = str(planner_settings.get("output_name") or "edit_plan.json").strip()
    output_path = str((Path(artifacts_root) / job_id / output_name))
    config_path = str(planner_settings.get("planner_config_path") or "configs/planner.yaml")

    step_printer = _StepPrinter()
    step_printer(f"Loaded config: {args.config}")
    step_printer("Starting planner pipeline.")
    plan, output = build_edit_plan(
        timeline_path=timeline_path,
        quality_report_path=quality_report_path,
        output_path=output_path,
        config_path=config_path,
        progress=step_printer,
    )
    step_printer("Planner completed.")
    print(f"edit_plan: {output}")
    print(f"job_id: {plan.job_id}")
    print(f"planned_actions: {len(plan.actions)}")
    print(f"candidate_windows: {plan.summary.candidate_windows}")


if __name__ == "__main__":
    main()
