# Coding Practices

Use this guidance when a future project adds real code. It applies across
languages and frameworks.

## Make Code Clear

- Prefer clear code over clever code.
- Write code so the next engineer can safely modify it.
- Use names that explain domain meaning, not just implementation mechanics.
- Keep control flow readable and avoid surprising behavior.

## Preserve Local Patterns

- Follow existing project structure, naming, and error-handling patterns.
- Keep changes scoped to the request.
- Avoid drive-by refactors unless they are required for the change.

## Contracts And Boundaries

- Use typed contracts, schemas, or interface definitions when the stack supports
  them.
- Validate inputs at system boundaries.
- Fail loudly on invalid states instead of silently continuing with corrupt or
  ambiguous data.
- Make boundary behavior explicit in tests or documentation.

## State And Side Effects

- Avoid hidden global state.
- Isolate side effects such as I/O, network calls, persistence, randomness, and
  time.
- Keep pure logic separate where practical so it can be tested directly.
- Make behavior observable through logs, artifacts, tests, or docs as
  appropriate for the project.

## Abstraction Discipline

- Avoid premature abstraction.
- Add an abstraction only when it removes real duplication, clarifies a stable
  concept, or protects a meaningful boundary.
- Prefer boring, direct code until the project proves it needs more structure.

## Maintainability

- Choose changes that reduce future ambiguity.
- Leave comments for non-obvious decisions, not for obvious syntax.
- Update tests and docs when behavior changes.
- Remove dead paths when safe, but do not expand the task into a broad rewrite.
