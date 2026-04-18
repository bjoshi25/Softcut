# Initiative Plan: Example Repository Setup

## Summary

Create a project-specific operating baseline by adapting the core template
without adding stack-specific tooling before the project needs it.

## Goals

- Establish ownership, contribution expectations, and review discipline.
- Document the first known architecture assumptions.
- Create a decision trail for future changes.

## Out Of Scope

- Product implementation.
- Framework selection.
- Deployment automation.
- Package manager configuration.

## Key Changes

- If the project uses GitHub, copy `extensions/github/` starter files into the
  repo root and replace placeholder owners before enabling `CODEOWNERS`.
- Update `.env.example` only with environment variables that are already known
  to be required.
- Add initial architecture context to `docs/architecture.md`.
- Create ADRs for any durable technology or process choices.

## Interfaces And Contracts

- Contributor workflow is documented through `README.md`, `AGENTS.md`, and
  `CONTRIBUTING.md`.
- Environment variables are documented through `.env.example`.
- Durable decisions are recorded in `docs/decisions/`.

## Verification

- Run `sh scripts/check-env.sh`.
- Review the final tree for unintended stack-specific files.
- Confirm placeholders are either intentionally retained or replaced.

## Assumptions

- The project stack is not chosen yet.
- The core template should remain reusable for other repositories.
