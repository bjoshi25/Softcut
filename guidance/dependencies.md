# Dependency Guidance

Dependencies should earn their place.

## Evaluate First

- Prefer official docs, primary sources, and project-maintainer guidance.
- Check whether the dependency solves a real project problem.
- Consider whether the standard library, platform, or existing project tools
  already cover the need.

## Add Carefully

- Add dependencies only with clear value.
- Prefer maintained packages with active releases, clear licenses, and credible
  documentation.
- Avoid abandoned or unnecessary packages.
- Avoid adding a large framework for a small helper problem.

## Versions

Pin or constrain versions according to the project ecosystem once a stack
exists. Record the version policy in the project docs or dependency manifest
when it is not obvious.

## Document Non-Obvious Choices

For non-obvious dependencies, document:

- why it exists
- what alternatives were considered
- what boundary it owns
- any operational or security concerns
- when it should be revisited
