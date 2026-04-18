# Documentation Guidance

Documentation should make the project easier to change safely.

## Keep Docs Close To Decisions

- Use `README.md` for orientation.
- Use `AGENTS.md` for agent and contributor operating rules.
- Use `docs/architecture.md` for current system shape.
- Use `docs/decisions/` for durable decisions.
- Use plans, reviews, and actions for change-specific traceability.

## Write For The Next Change

Good documentation helps the next engineer answer:

- what exists
- why it exists
- how to verify it
- where the boundaries are
- what should not be changed casually

## Keep It Current

Update docs when behavior, setup, architecture, environment variables, review
policy, or public interfaces change. Remove stale claims rather than adding
contradictory notes.

## Be Honest About Scope

Do not imply production readiness, platform support, security guarantees, or
workflow maturity that the repo does not actually have.
