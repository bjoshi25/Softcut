# Review Guidance

Reviews protect correctness, maintainability, usefulness, and trust. A review is
not just a style pass; it should inspect actual behavior and artifacts wherever
possible.

## Review Mindset

- Start from the intended outcome and compare it to what changed.
- Look for bugs, regressions, unclear contracts, missing evidence, and hidden
  rework risk.
- Review generated artifacts, docs, tests, logs, screenshots, or runnable
  behavior when applicable.
- Keep findings specific and actionable.

## Severity Levels

- **Critical** - likely data loss, security exposure, broken core behavior,
  irreversible migration risk, or a change that cannot safely advance.
- **Medium** - meaningful correctness, maintainability, dependency, testing, or
  user- or maintainer-usefulness issue that should be addressed before or soon
  after shipping.
- **Low** - minor issue, clarity improvement, small cleanup, or non-blocking
  documentation gap.

## Verdicts

- **Ship** - no blocking findings; remaining notes are minor or already
  tracked.
- **Ship with notes** - acceptable to advance with explicit follow-up.
- **Do not advance** - critical issue or unresolved uncertainty makes the change
  unsafe.

## Required Finding Format

Each finding should include:

- severity
- location or artifact
- issue
- impact
- recommended action
- evidence checked

## Review Checks

- Correctness: Does the change satisfy the intended behavior and failure modes?
- Maintainability: Is the change readable, scoped, and consistent with local
  patterns?
- User or maintainer usefulness: Does it make the project more useful without
  overstating scope?
- Security: Could secrets, permissions, unsafe inputs, or sensitive artifacts be
  exposed?
- Dependencies: Are new dependencies necessary, maintained, and documented?
- Test coverage: Are important behaviors covered by automated or documented
  manual checks?

## Evidence

Inspect actual behavior and artifacts, not just code shape. Good evidence can
include test output, rendered docs, generated files, command output, logs with
secrets redacted, screenshots, or manual verification notes.
