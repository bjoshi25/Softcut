# Milestone Review Prompt

Review a larger initiative or milestone without assuming a fixed stage workflow.

## Instructions

1. Read the initiative plan, related reviews, actions, ADRs, and current docs.
2. Compare intended outcomes with actual artifacts and behavior.
3. Identify what is complete, what is risky, and what has drifted.
4. Check whether scope, contracts, testing, docs, and decisions still match
   reality.
5. Produce findings first, ordered by severity.
6. Recommend whether the initiative should advance, pause for fixes, or be
   reframed.

## Checks

- Does the delivered work satisfy the stated goal?
- Are user-facing or maintainer-facing claims honest?
- Are contracts and boundaries documented enough to support future work?
- Are known risks tracked with owners or triggers?
- Are tests and manual verification proportionate to the risk?

## Verdicts

Use one:

- `Advance`
- `Advance with notes`
- `Pause for action`
- `Reframe scope`
