# ADR: Keep The Core Template Stack-Agnostic

## Status

Accepted

## Context

This repository is meant to seed many different project types. Adding a default
language, framework, package manager, or application structure would make it
less useful for projects outside that ecosystem.

## Decision

Keep the core template stack-agnostic. Add stack-specific tools only through
project-specific customization or optional extension packs.

## Consequences

- New projects start with engineering practice instead of product scaffolding.
- Teams must intentionally add their runtime, test runner, formatter, and CI
  choices later.
- The template remains lightweight and easier to review.

## Revisit When

- A specific project forks this template and needs a real stack.
- An extension pack is proposed for a common project type.
- The core template begins carrying hidden stack assumptions.
