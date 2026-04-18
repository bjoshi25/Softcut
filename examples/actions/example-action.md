# Action: Example Repository Setup Review

## Fix Now

- Finding: `.env.example` lists a future integration variable.
  Action: Remove the variable until the integration is implemented or accepted
  through an ADR.
  Done when:
  - [ ] `.env.example` contains only variables needed by current repo behavior.
  - [ ] Any future integration need is captured in a plan or ADR.
  - [ ] `sh scripts/check-env.sh` passes.

## Defer

- Finding: Architecture doc has limited detail.
  Reason to defer: The project has not chosen a stack or runtime boundary yet.
  Trigger to revisit: First project-specific extension or first real runtime
  component.
  Tracking: Update `docs/architecture.md` in the extension plan.

## Carry Forward

- Decision: Keep the core template stack-agnostic.
  Risk: Future contributors may try to add framework defaults too early.
  Owner: Repository maintainers.
