# Engineering Principles

These principles are intentionally stack-agnostic. They describe how this
template expects engineering work to be shaped.

## Useful First

Build the smallest thing that makes the project more understandable, safer to
change, or easier to operate. Avoid ceremony that does not improve decisions,
reviews, or delivery.

## Trace Decisions

Important choices should leave a record. Use plans for intended work, reviews
for current risk, actions for follow-up decisions, and ADRs for durable
architecture choices.

## Prefer Clarity Over Cleverness

Code, scripts, and documentation should be easy for the next engineer to modify
safely. If a solution requires special context to understand, capture that
context or simplify the solution.

## Respect Scope

Make changes that match the stated goal. Leave unrelated cleanup for a separate
plan unless it is required to complete the current work safely.

## Inspect Reality

Review real behavior, generated artifacts, test output, logs, and user-facing
results where applicable. Do not rely only on code shape or intent.

## Keep The Core Portable

The core template should not depend on any one ecosystem. Add project-specific
tools later, and document why they belong in that project.
