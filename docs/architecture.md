# Architecture

## Current MVP Shape

Softcut is now a two-phase MVP in progress. This repo currently implements
Phase 1 Step 1 (fused analysis engine) and local API entrypoints.

## Runtime Boundaries

- `engine/analysis/build_timeline.py` orchestrates analysis and artifact output.
- `engine/analysis/run_from_config.py` loads `configs/project.yaml` and runs
  analysis from project-level source/path settings.
- `engine/adapters/` owns tool/model boundaries:
  - `ffmpeg_adapter.py` for probe/frame extraction/local frame delta checks.
  - `pyscenedetect_adapter.py` for deterministic scene cuts (+ FFmpeg fallback).
  - `transnetv2_adapter.py` for learned shot-boundary proposals.
  - `whisperx_adapter.py` for ASR/word timing (+ optional diarization).
  - `opennsfw2_adapter.py` for sampled visual risk scoring.
  - `yt_dlp_adapter.py` for URL-to-local video ingestion.
- `engine/fusion/boundary_fusion.py` owns confidence-weighted temporal fusion.
- `engine/schemas/timeline.py` defines typed artifact contracts (Pydantic).
- `apps/api/main.py` and `apps/api/routes/analysis.py` expose local FastAPI
  routes for analysis job creation.

## Artifact Contract

```text
data/inbox/input.mp4
-> artifacts/{job_id}/analysis_timeline.json
```

`analysis_timeline.json` includes:

- media metadata (`fps`, `duration_sec`)
- fused `boundaries` and derived `scenes`
- speech/word timing arrays when WhisperX is available
- visual flags when OpenNSFW2 is available
- rating evidence seeds for policy/planning in Step 2
- detector configs and adapter availability/version status

## Fallback Policy

- Missing TransNetV2: continue with PySceneDetect path.
- Missing WhisperX: continue with empty speech/word arrays.
- Missing OpenNSFW2: continue with empty visual flags.
- Missing PySceneDetect: use FFmpeg scene filter fallback.

No single unavailable ML adapter should crash the whole analysis job.

## Local Execution

- `sh scripts/run-analysis.sh --input data/inbox/input.mp4 --job-id local_001`
- `SOFTCUT_INSTALL_EXTRAS=analysis-ml,ingest sh scripts/run-analysis.sh --url "<youtube_url>" --job-id local_yt_001`
- `pnpm nx run analysis:run` (reads `configs/project.yaml`)
- `sh scripts/run-api.sh`

Tooling setup:
- `scripts/install-node.sh` runs `pnpm install` (or `pnpm install --frozen-lockfile`
  when lockfile exists).
- Python commands use `scripts/ensure-python-env.sh`, which reuses `.venv` and
  only re-installs dependencies when `pyproject.toml` changes.
