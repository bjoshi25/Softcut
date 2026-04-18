# Review Prompt

Review the change for engineering risk. Findings must come first and be ordered
by severity.

## Instructions

1. Read the plan or request that motivated the change.
2. Inspect the diff and the surrounding implementation.
3. Inspect actual behavior or artifacts where applicable, not just code shape.
4. Check correctness, maintainability, user or maintainer usefulness, security,
   dependencies, and test coverage.
5. Avoid style-only comments unless they affect clarity or maintainability.

## Finding Format

```md
- Severity: critical | medium | low
  Location or artifact: <file, line, command output, rendered artifact, etc.>
  Issue: <what is wrong>
  Impact: <why it matters>
  Recommended action: <specific fix or decision>
  Evidence checked: <what was inspected>
```

## Verdicts

End with one verdict:

- `Ship`
- `Ship with notes`
- `Do not advance`

Keep summaries brief and place them after findings.
