# Testing Guidance

Testing should match the risk and shape of the project. This template does not
prescribe a framework.

## Unit Tests

Use unit tests for pure logic, deterministic transformations, validation rules,
formatting rules, and small decision functions. Keep them fast and focused.

## Integration Tests

Use integration tests for boundaries: filesystem, database, network, process
execution, API calls, message queues, CLIs, generated artifacts, or framework
integration points.

## Smoke Tests

Use smoke tests for runnable flows. A smoke test should prove the main path can
start, execute a representative action, and produce the expected visible result
or artifact.

## Regression Tests

When fixing a bug, add a regression test that fails for the old behavior and
passes for the fix whenever practical.

## Fixture Discipline

- Keep fixtures small and readable.
- Name what each fixture represents.
- Avoid fixtures that hide important behavior behind excessive data.
- Update fixtures deliberately when contracts change.

## Determinism

Prefer deterministic tests. Control time, randomness, ordering, network access,
and external services when possible. If determinism is not practical, explain
the remaining nondeterminism in the test or review notes.

## Manual Verification

Manual verification is acceptable when automation would be disproportionate,
the behavior is visual or exploratory, or the project does not yet have a test
harness. Record the exact steps, environment, and evidence inspected.
