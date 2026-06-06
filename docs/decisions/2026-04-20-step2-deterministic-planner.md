# Deterministic Step 2 Planner Artifact

## Status

Accepted.

## Context

Phase 1 Step 1 now produces planner-ready analysis artifacts:
- `analysis_timeline.json`
- `analysis_quality_report.json`

MVP needs a stable Step 2 output that downstream execution can consume without
re-running model inference. The planner must remain deterministic, explainable,
and lightweight on CPU-only environments.

## Decision

Add Phase 1 Step 2 as a deterministic planner that:

- reads `analysis_timeline.json` and `analysis_quality_report.json`
- enforces `planner_eligible` quality gate by default
- maps evidence types to explicit edit actions using config-driven rules
- selects cut windows from existing analysis context and cut anchors
- writes `artifacts/{job_id}/edit_plan.json`

Expose planner via:

- `./run planner` (config-driven)
- `./run planner-cli` (direct artifact paths)
- `POST /planner/jobs/local` API route

## Consequences

- Step 2 output is now explicit and reusable by future execution stage.
- Planner behavior is configurable (`configs/planner.yaml`) without code edits.
- Deterministic rules are faster and easier to audit than introducing a second
  model stage in MVP.
- Planner recall/precision tradeoffs remain policy-config decisions and need
  periodic review against adversarial fixtures.
