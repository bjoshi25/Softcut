# Architecture

## Current MVP Shape

Softcut is now a two-phase MVP in progress. This repo currently implements:
- Phase 1 Step 1: fused analysis engine
- Phase 1 Step 2: deterministic planner
- local API entrypoints for both stages

## Runtime Boundaries

- `engine/analysis/build_timeline.py` orchestrates analysis and artifact output.
- `engine/analysis/run_from_config.py` loads `configs/project.yaml` and runs
  analysis from project-level source/path settings.
- `engine/planning/build_plan.py` builds deterministic edit actions from
  analysis timeline + quality report artifacts.
- `engine/planning/run_from_config.py` runs planner from project-level
  config/path settings.
- `engine/adapters/` owns tool/model boundaries:
  - `ffmpeg_adapter.py` for probe and local frame delta checks.
  - `pyscenedetect_adapter.py` for deterministic scene cuts (+ FFmpeg fallback).
  - `transnetv2_adapter.py` for learned shot-boundary proposals.
  - `whisperx_adapter.py` for ASR/word timing (+ optional diarization).
  - `opennsfw2_adapter.py` for scene-aware sparse visual scoring with dense
    local fallback, threshold calibration, and event debouncing.
  - `yt_dlp_adapter.py` for URL-to-local video ingestion.
- `engine/fusion/boundary_fusion.py` owns confidence-weighted temporal fusion.
- `engine/schemas/timeline.py` defines typed artifact contracts (Pydantic).
- `apps/api/main.py` and `apps/api/routes/analysis.py` expose local FastAPI
  routes for analysis job creation.
- `apps/api/routes/planner.py` exposes local FastAPI routes for planner jobs.
- `apps/api/routes/jobs.py` exposes async orchestration routes for upload/url
  pipeline runs and polling-oriented job status/results.
- `apps/web/` contains the Next.js App Router frontend for upload, status,
  quality summary, planner summary, and planned action tables.

## Artifact Contract

```text
data/inbox/input.mp4
-> artifacts/{job_id}/analysis_timeline.json
-> artifacts/{job_id}/edit_plan.json
```

`analysis_timeline.json` includes:

- media metadata (`fps`, `duration_sec`)
- fused `boundaries` and derived `scenes`
- speech/word timing arrays when WhisperX is available
- debounced visual flags when OpenNSFW2 is available
- rating evidence seeds for policy/planning in Step 2
- detector configs and adapter availability/version status

`edit_plan.json` includes:
- deterministic actions derived from rating evidence and planner rules
- selected edit windows and cut anchors
- planner quality gate summary and dropped-item counts

## Fallback Policy

- Missing TransNetV2: continue with PySceneDetect path.
- Missing WhisperX: continue with empty speech/word arrays.
- Missing OpenNSFW2: continue with empty visual flags.
- Missing PySceneDetect: use FFmpeg scene filter fallback.

No single unavailable ML adapter should crash the whole analysis job.
Planner stage is gate-aware and, by default, requires
`analysis_quality_report.planner_eligible=true` before writing plan output.

Visual analysis defaults to scene-aware sparse scoring: coarse global stride
plus representative scene coverage, then dense rescans only around suspicious
windows. This keeps recall-focused behavior while reducing CPU cost on
non-GPU machines. Long-running scans emit periodic heartbeat progress messages.

Artifact output is job-scoped at `artifacts/{job_id}`. Runtime config can
overwrite the current job folder and prune older job folders to keep the
artifact tree compact.
Job manifests for async orchestration live under `artifacts/_jobs/{job_id}.json`.

## Local Execution

- `sh scripts/run-analysis.sh --input data/inbox/input.mp4 --job-id local_001`
- `SOFTCUT_INSTALL_EXTRAS=analysis-ml,ingest sh scripts/run-analysis.sh --url "<youtube_url>" --job-id local_yt_001`
- `pnpm nx run analysis:run` (reads `configs/project.yaml`)
- `sh scripts/run-plan-config.sh --config configs/project.yaml`
- `sh scripts/run-plan.sh --timeline artifacts/<job_id>/analysis_timeline.json --quality-report artifacts/<job_id>/analysis_quality_report.json`
- `sh scripts/run-api.sh`
- `pnpm --filter @softcut/web dev`

Tooling setup:
- `scripts/install-node.sh` runs `pnpm install` (or `pnpm install --frozen-lockfile`
  when lockfile exists).
- Python commands use `scripts/ensure-python-env.sh`, which reuses `.venv` and
  only re-installs dependencies when `pyproject.toml` changes.
