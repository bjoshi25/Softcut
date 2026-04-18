# Planning Prompt

Create a decision-complete implementation plan for the requested change.

## Instructions

1. Read the repository guidance before planning:
   - `README.md`
   - `AGENTS.md`
   - relevant files in `guidance/`
   - related plans, reviews, actions, architecture notes, and ADRs
2. State the goal and success criteria.
3. Identify what is in scope and out of scope.
4. Describe the implementation approach at the behavior and interface level.
5. Identify input/output contracts, data boundaries, failure modes, and docs
   that must change.
6. Define the verification plan, including automated tests, manual checks, and
   artifact inspection where appropriate.
7. Record assumptions and defaults.

## Output Format

Use this structure:

```md
# Plan: <name>

## Summary
<brief goal and intended outcome>

## Key Changes
<decision-complete implementation bullets>

## Interfaces And Contracts
<inputs, outputs, boundaries, and compatibility notes>

## Test Plan
<checks that prove the work is complete>

## Assumptions
<defaults chosen and unresolved but acceptable uncertainty>
```

Do not include sample product code unless the repository already contains real
project code that must be changed.
