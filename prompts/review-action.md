# Review Action Prompt

Convert review findings into concrete follow-up work.

## Instructions

1. Read the review findings and the original plan.
2. Separate required fixes from deferrable work.
3. For each item, identify the smallest useful action.
4. Record carry-forward decisions honestly.
5. Avoid turning focused findings into broad rewrites.

## Output Format

```md
# Review Action: <name>

## Fix Now
- Finding: <reference>
  Action: <specific change>
  Done when: <observable condition>

## Defer
- Finding: <reference>
  Reason to defer: <why acceptable>
  Trigger to revisit: <event or condition>
  Tracking: <issue, plan, ADR, or owner>

## Carry Forward
- Decision: <what remains true>
  Risk: <remaining risk>
  Owner: <person/team if known>
```
