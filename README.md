# Engineering Template

This repository is a lean engineering operating template for future repos. It is
not an application starter, framework scaffold, or product-code example. Use it
to carry durable engineering habits into a new project before the project has a
specific stack.

## What This Template Is

- A shared operating baseline for planning, implementation, review, follow-up
  action, and decision traceability.
- A set of stack-agnostic guidance documents for engineers and agents.
- A place to record architecture context, initiative plans, reviews, actions,
  and lightweight decisions.
- A small set of shell helpers that orient contributors and check that the
  template structure is present.

## What This Template Does Not Include

- No sample product code.
- No assumptions about Python, Node, backend services, frontend apps, data
  pipelines, infrastructure stacks, or package managers.
- No fixed stage or step workflow engine.
- No generated framework configuration.
- No prescribed release process, branching model, source-hosting platform,
  hosting model, or deployment target.

## Using It For A New Repo

1. Copy or generate a new repository from this template.
2. Read `AGENTS.md` and the files under `guidance/`.
3. Choose optional extension files only after the project has a real platform
   need. For GitHub, see `extensions/github/`.
4. Add project-specific documentation only after the project has a real shape.
5. Keep stack-specific tooling in later extension commits so the core operating
   template stays easy to review.

## Customizing For A Specific Stack

Add stack-specific files only when they are needed by the project. Examples:
package manager manifests, test runner config, formatter config, CI workflows,
deployment manifests, local development scripts, or generated client code.

When customizing:

- Record non-obvious technical choices in `docs/decisions/`.
- Update `docs/architecture.md` when system boundaries become clear.
- Add environment variables to `.env.example`, not to README prose alone.
- Extend the guidance rather than rewriting the core template.
- Keep project-specific workflows additive; the core template should remain
  useful to other project types.

## Recommended Operating Loop

Use this loop for meaningful changes:

1. **Plan** - create a decision-complete plan in `plans/`.
2. **Implement** - make the smallest scoped change that satisfies the plan.
3. **Review** - inspect actual behavior, artifacts, tests, and code.
4. **Action** - decide what must be fixed now and what can be carried forward.
5. **Decision record** - capture durable architecture or process decisions in
   `docs/decisions/`.

The loop is intentionally simple. It is a review discipline, not a workflow
engine.

## Repository Map

- `AGENTS.md` - agent and contributor operating rules.
- `guidance/` - reusable engineering practice guidance.
- `prompts/` - prompts for planning, implementation, reviews, and truth checks.
- `plans/` - initiative plans and planning records.
- `reviews/` - review records.
- `actions/` - follow-up action records.
- `docs/` - architecture notes and decision records.
- `examples/` - illustrative records kept out of active traceability folders.
- `extensions/` - optional platform or tooling starter files.
- `scripts/` - stack-neutral helper scripts.

## First Commands

```sh
sh scripts/bootstrap.sh
sh scripts/check-env.sh
```

Both scripts are non-destructive and avoid installing dependencies.

## Softcut MVP (Phase 1 Steps 1-2)

This repository now contains:
- Phase 1 Step 1: fused analysis engine for local videos.
- Phase 1 Step 2: deterministic planner that converts analysis artifacts into edit actions.

Core flow:

```text
data/inbox/input.mp4
-> artifacts/{job_id}/analysis_timeline.json
-> artifacts/{job_id}/edit_plan.json
-> apps/web results view
```

### Two-word run commands

1) Install Node workspace deps (uses `pnpm-lock.yaml` in frozen mode once lockfile exists):

```sh
./run install
```

Install optional free adapters for fuller analysis quality (OpenNSFW2 runtime + TransNetV2):

```sh
./run adapters
```

The runner now defaults Python extras to `analysis-ml,ingest`, so no export is required.

2) (Optional, one-time per shell) enable `run ...` without `./`:

```sh
export PATH="/Users/bhrigujoshi/Desktop/Projects/Softcut:$PATH"
```

3) Put your URL in file:

```sh
printf '%s\n' 'https://www.youtube.com/watch?v=7cLTW934VR8' > data/inbox/url.txt
```

4) Edit [configs/project.yaml](/Users/bhrigujoshi/Desktop/Projects/Softcut/configs/project.yaml):
- `analysis_run.source.mode`: `input` | `url` | `url_file`
- `analysis_run.source.url_file`: path to your saved URL file (e.g. `data/inbox/url.txt`)
- `analysis_run.job_id`: output job id
- Optional speedup: set `adapters.whisperx.language` in `configs/analysis.yaml` (e.g. `"en"`) to skip language auto-detect.

5) Run analysis:

```sh
./run analysis
```

This now writes two artifacts:
- `artifacts/<job_id>/analysis_timeline.json`
- `artifacts/<job_id>/analysis_quality_report.json`

6) Run planner:

```sh
./run planner
```

This writes:
- `artifacts/<job_id>/edit_plan.json`

Planner defaults:
- requires `analysis_quality_report.planner_eligible=true`
- maps evidence types to deterministic actions (`beep_word`, `mute_word`, `trim_segment`)
- uses safe cut anchors when generating trim windows

Visual analysis defaults to a scene-aware sparse strategy: coarse global
sampling plus representative scene frames, then dense local rescans only around
suspicious windows. The resulting hits are calibrated from score distribution
and merged into smoother edit events.

Runtime notes:
- Step 12 now emits heartbeat progress while visual scan runs.
- `runtime.overwrite_job_artifacts: true` rewrites the current job folder.
- `runtime.prune_other_artifacts: true` with `runtime.keep_artifact_jobs: 1`
  keeps artifacts compact by removing older job folders after a successful run.
- Speed knobs live in `configs/analysis.yaml`:
  `adapters.opennsfw2.batch_size`,
  `runtime.visual_omp_threads`,
  `runtime.visual_tf_interop_threads`,
  `runtime.visual_tf_intraop_threads`.

For production-grade planning inputs, set `run_profile: strict` in `configs/analysis.yaml`.

API:

```sh
./run api
```

Web UI:

```sh
./run web
```

Default UI URL: `http://localhost:3000`  
Default API target: `NEXT_PUBLIC_API_BASE=http://localhost:8000`

Create a local planner job:

```sh
curl -X POST http://localhost:8000/planner/jobs/local \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "local_001"
  }'
```

Async orchestration endpoints for UI:
- `POST /jobs/from-upload`
- `POST /jobs/from-url`
- `POST /jobs/{job_id}/planner`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/results`

Status (second two-word command):

```sh
./show status
```

### Direct script options (still supported)

Local file:

```sh
./run analysis-cli --input data/inbox/input.mp4 --job-id local_001
```

URL:

```sh
./run analysis-cli \
  --url "https://www.youtube.com/watch?v=7cLTW934VR8" \
  --job-id local_yt_001
```

URL from file:

```sh
./run analysis-cli \
  --url-file data/inbox/url.txt \
  --job-id local_yt_file_001 \
  --overwrite-job-artifacts \
  --prune-other-artifacts \
  --keep-artifact-jobs 1
```

Then create a local analysis job:

```sh
curl -X POST http://localhost:8000/analysis/jobs/local \
  -H "Content-Type: application/json" \
  -d '{
    "input_video_path": "data/inbox/input.mp4",
    "job_id": "local_001"
  }'
```

Direct planner CLI:

```sh
./run planner-cli \
  --timeline artifacts/local_from_config_001/analysis_timeline.json \
  --quality-report artifacts/local_from_config_001/analysis_quality_report.json \
  --output artifacts/local_from_config_001/edit_plan.json
```
## Supabase Job Persistence

The async `/jobs/*` API supports Supabase-backed persistence when these backend env vars are set:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Create the required table by running SQL from:

- `supabase/sql/jobs_table.sql`

Frontend Supabase client env vars (Next.js):

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
