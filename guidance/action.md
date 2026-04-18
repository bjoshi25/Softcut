# Action Guidance

Use action records to convert review findings into clear follow-up work.

## Convert Findings Into Work

For each review finding:

- restate the risk in concrete terms
- decide whether it must be fixed now or can be deferred
- identify the smallest useful fix
- name the owner if the project has owners
- record the done condition

## Now Vs Defer

Fix now when the issue:

- blocks correctness, security, trust, or core usability
- makes the change hard to review or rollback
- will become more expensive if postponed
- invalidates the plan or decision record

Defer when the issue:

- is low risk
- is outside the current scope
- has a clear owner and trigger
- can be tracked without hiding risk

## Avoid Broad Rewrites

Actions should not become vague cleanup projects. Prefer the smallest change
that resolves the finding. If a broad rewrite is truly required, create a plan
that explains why the larger scope is necessary.

## Carry-Forward Decisions

When deferring work, record:

- what is being deferred
- why it is acceptable to defer
- what risk remains
- what should trigger revisiting it
- where the follow-up will be tracked

## Done Condition Format

Use this format:

```md
Done when:
- [ ] The specific behavior, doc, or artifact has changed.
- [ ] Verification evidence is attached or described.
- [ ] Any follow-up decision is recorded or linked.
```
