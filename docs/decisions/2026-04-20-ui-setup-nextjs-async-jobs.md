# UI Setup: Next.js + Async Job Orchestration

## Status

Accepted.

## Context

Phase 1 analysis and planner are complete, but UX remained CLI/API-first.
Long-running analysis/planning needs a non-blocking frontend model with status
polling and compact result summaries.

## Decision

- Add `apps/web` using Next.js App Router + TypeScript.
- Use `@tanstack/react-query` for polling `/jobs/{job_id}` and `/jobs/{job_id}/results`.
- Add filesystem-backed async orchestration endpoints:
  - `POST /jobs/from-upload`
  - `POST /jobs/from-url`
  - `POST /jobs/{job_id}/planner`
  - `GET /jobs/{job_id}`
  - `GET /jobs/{job_id}/results`
- Persist job manifests in `artifacts/_jobs/{job_id}.json`.
- Keep database out of scope for this phase.

## Consequences

- Users can run one-click pipeline flows without blocking request/response cycles.
- Frontend can survive refresh/navigation via job-id routes and polling.
- Runtime stays local-MVP simple, but cross-process job coordination remains
  limited until a durable queue/DB is introduced.
