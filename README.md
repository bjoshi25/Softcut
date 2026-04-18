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
