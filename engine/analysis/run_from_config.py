"""Run analysis pipeline from a project-level YAML config."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from engine.analysis.build_timeline import build_analysis_timeline


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


def _read_url_from_file(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"url file not found: {path}")
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    raise ValueError(f"url file has no usable URL lines: {path}")


def _pick_source(source_cfg: dict[str, Any]) -> tuple[str | None, str | None]:
    mode = str(source_cfg.get("mode") or "url_file").strip()
    if mode == "input":
        input_video_path = str(source_cfg.get("input_video_path") or "").strip()
        if not input_video_path:
            raise ValueError("source.input_video_path is required when mode=input")
        return input_video_path, None

    if mode == "url":
        source_url = str(source_cfg.get("url") or "").strip()
        if not source_url:
            raise ValueError("source.url is required when mode=url")
        return None, source_url

    if mode == "url_file":
        url_file = str(source_cfg.get("url_file") or "").strip()
        if not url_file:
            raise ValueError("source.url_file is required when mode=url_file")
        return None, _read_url_from_file(url_file)

    raise ValueError("source.mode must be one of: input, url, url_file")


class _StepPrinter:
    def __init__(self) -> None:
        self.step = 0

    def __call__(self, message: str) -> None:
        self.step += 1
        print(f"[step {self.step:02d}] {message}", flush=True)


def _download_detail(message: str) -> None:
    print(f"  [download] {message}", flush=True)


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Softcut analysis from configs/project.yaml."
    )
    parser.add_argument(
        "--config",
        default="configs/project.yaml",
        help="Project config YAML path.",
    )
    return parser


def main() -> None:
    args = _build_cli().parse_args()
    root = _load_yaml(args.config)
    run_cfg = root.get("analysis_run") or {}
    if not isinstance(run_cfg, dict):
        raise ValueError("analysis_run must be a mapping")

    source_cfg = run_cfg.get("source") or {}
    paths_cfg = run_cfg.get("paths") or {}
    settings_cfg = run_cfg.get("settings") or {}
    if not isinstance(source_cfg, dict) or not isinstance(paths_cfg, dict) or not isinstance(settings_cfg, dict):
        raise ValueError("analysis_run.source/paths/settings must be mappings")

    input_video_path, source_url = _pick_source(source_cfg)
    job_id = str(run_cfg.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("analysis_run.job_id is required")

    step_printer = _StepPrinter()
    step_printer(f"Loaded config: {args.config}")
    step_printer("Starting analysis pipeline.")
    timeline, output_path = build_analysis_timeline(
        input_video_path=input_video_path,
        source_url=source_url,
        job_id=job_id,
        artifacts_root=str(paths_cfg.get("artifacts_root") or "artifacts"),
        work_root=str(paths_cfg.get("work_root") or "data/work"),
        download_dir=str(paths_cfg.get("download_dir") or "data/inbox"),
        sample_every_sec=(
            float(settings_cfg["sample_every_sec"])
            if settings_cfg.get("sample_every_sec") is not None
            else None
        ),
        max_visual_samples=(
            int(settings_cfg["max_visual_samples"])
            if settings_cfg.get("max_visual_samples") is not None
            else None
        ),
        diarize=(
            bool(settings_cfg["diarize"])
            if settings_cfg.get("diarize") is not None
            else None
        ),
        config_path=str(
            settings_cfg.get("analysis_config_path") or "configs/analysis.yaml"
        ),
        progress=step_printer,
        download_progress=_download_detail,
    )
    step_printer("Analysis completed.")
    print(f"analysis_timeline: {output_path}")
    print(f"duration_sec: {timeline.duration_sec}")
    print(f"fps: {timeline.fps}")
    print(f"scene_count: {len(timeline.scenes)}")


if __name__ == "__main__":
    main()
