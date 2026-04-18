# Agent Operating Guide

## Repo Purpose

This repository is a project-agnostic engineering operating template. Its job is
to help future repositories start with clear engineering practice, review
discipline, agent guidance, and decision traceability.

## Scope Boundaries

- Do not add product code to the core template.
- Do not assume a language, runtime, framework, platform, package manager, or
  deployment target.
- Do not require a source-hosting platform in the core template.
- Do not create a fixed stage or step workflow engine.
- Do not add stack-specific tools until a real project extension needs them.
- Keep the core template readable in plain Markdown and portable shell.

Project-specific workflows may be added later as extension packs or repo-local
customizations without changing the core template.

## Read Before Editing

Before editing, agents should read:

1. `README.md` for template intent and operating loop.
2. This file for boundaries and working rules.
3. Relevant files in `guidance/` for the task type.
4. Existing plans, reviews, actions, and decisions that relate to the change.
5. Current repository status so unrelated user work is not overwritten.

Prefer searching the repo before assuming a convention is missing.

## Implementation Rules

- Lock the scope before editing: identify the requested outcome, files likely
  to change, and what is intentionally out of scope.
- Preserve local patterns and wording where they already exist.
- Keep changes small enough to review.
- Avoid broad rewrites unless the plan explicitly calls for them.
- Prefer explicit contracts, schemas, or documented interfaces when the future
  project stack supports them.
- Validate inputs at boundaries and fail clearly when states are invalid.
- Isolate side effects so behavior can be tested and reviewed.
- Update documentation when behavior, operating policy, or project assumptions
  change.

## Review And Action Loop

Use the core loop for meaningful changes:

`plan -> implement -> review -> action -> decision record`

Reviews should produce findings first, ordered by severity. Action records
should separate fixes required now from deferrals and carry-forward decisions.
Durable technical or process decisions should be captured in `docs/decisions/`.

## Environment And Secrets Policy

- Never commit secrets.
- Document environment variables only in `.env.example`.
- Do not place real credentials, tokens, private keys, or production endpoints
  in examples.
- Avoid printing secrets in logs, scripts, artifacts, reviews, or prompts.
- Treat generated logs and artifacts as possible secret surfaces.

## Dependency Policy

- Add dependencies only when they provide clear value.
- Prefer official documentation and primary sources when evaluating dependency
  behavior.
- Pin or constrain versions according to the project ecosystem once a stack
  exists.
- Avoid abandoned, unnecessary, or poorly maintained packages.
- Document non-obvious dependencies and why they exist.

## Testing Expectations

- Add tests when behavior is introduced or changed.
- Use unit tests for pure logic, integration tests for boundaries, smoke tests
  for runnable flows, and regression tests for bugs.
- Keep tests deterministic where possible.
- If automated tests are not practical, record the manual verification steps
  and evidence.

## Documentation Expectations

- Keep documentation close to the decision or behavior it explains.
- Update `docs/architecture.md` as system shape emerges.
- Record durable decisions with lightweight ADRs.
- Prefer concise, current docs over large stale narratives.
- Make it clear when something is a placeholder for a future project.
