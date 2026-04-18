# Implementation Guidance

Use this guide before and during scoped implementation work.

## Read Order Before Implementation

1. `README.md` for repo intent and operating loop.
2. `AGENTS.md` for scope boundaries and agent rules.
3. The relevant plan in `plans/`, if one exists.
4. Related guidance files.
5. Related reviews, actions, architecture notes, and ADRs.
6. The files that will likely change.

## Lock Scope Before Editing

Before editing, state or confirm:

- the user-visible or maintainer-visible outcome
- the files or areas expected to change
- the behaviors that must remain unchanged
- the checks that will prove the work is complete
- anything intentionally deferred

## Identify Contracts

For the area being changed, identify:

- inputs and where they enter the system
- outputs and who consumes them
- validation rules
- failure behavior
- persistence, network, filesystem, or external tool boundaries
- documented interfaces or schemas

If no formal contract exists, document the observed contract before changing it.

## Handle Unknowns

- Resolve discoverable unknowns by reading the repo.
- Ask only when the answer is a product, policy, or tradeoff decision.
- Record assumptions when moving forward without a definitive answer.
- Prefer a small reversible change when uncertainty is high.

## Add Tests When

- behavior is introduced or changed
- a bug is fixed
- a boundary contract changes
- failure behavior matters
- future regressions would be costly or hard to see manually

If automated tests are not practical, record manual verification steps and the
evidence inspected.

## Update Docs When

- setup, operation, or review expectations change
- public interfaces or contracts change
- architecture boundaries change
- an important decision would otherwise live only in memory

## Avoid

- sample product code in the core template
- stack assumptions without a project need
- hidden global state
- broad rewrites during narrow tasks
- adding dependencies without clear value
- changing workflow policy without updating the relevant guidance
