# Architecture

This repository is an engineering operating template, not an application or
system implementation.

## Current Shape

- Root documents define purpose, contribution expectations, agent rules, and
  environment conventions.
- `guidance/` contains durable engineering practice guidance.
- `prompts/` contains reusable agent prompts.
- `plans/`, `reviews/`, and `actions/` capture change traceability.
- `docs/decisions/` contains lightweight architecture decision records.
- `scripts/` contains non-destructive helper scripts.

## Boundaries

- The core template does not own product behavior.
- The core template does not choose a language, runtime, framework, package
  manager, source-hosting platform, deployment target, database, queue, model
  provider, or hosting platform.
- Project-specific extension packs may add those choices later.

## Extension Guidance

When a future project adds a real stack, update this file with:

- runtime boundaries
- external systems
- data ownership
- build and test entry points
- deployment or release assumptions
- security-relevant trust boundaries

Record durable choices in `docs/decisions/`.
