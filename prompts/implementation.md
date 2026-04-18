# Implementation Prompt

Implement the approved plan with the smallest scoped change that satisfies it.

## Instructions

1. Read `AGENTS.md`, the approved plan, and related guidance.
2. Check the current worktree and avoid overwriting unrelated changes.
3. Reconfirm the scope, expected files, contracts, and verification steps.
4. Edit only the files needed for the approved outcome.
5. Preserve local patterns and avoid opportunistic rewrites.
6. Add or update tests when behavior changes.
7. Update documentation and decision records when the change affects operation,
   architecture, policy, or public interfaces.
8. Run the planned checks and inspect relevant artifacts.

## Output Format

Report:

- what changed
- verification performed
- any deviations from the plan
- residual risks or follow-up actions

Do not invent stack-specific workflow steps that are not present in the repo.
