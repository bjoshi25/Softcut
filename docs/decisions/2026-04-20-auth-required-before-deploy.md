# ADR: Authentication Required Before Deployment

- Status: Accepted
- Date: 2026-04-20

## Context

Softcut is currently in MVP buildout with local-first workflows and rapid iteration on analysis and planning pipelines.
While this enables speed, deployment without authentication and authorization would create unacceptable access and data exposure risk.

## Decision

Authentication and authorization are mandatory preconditions for production deployment.

No production release may proceed until:

1. OAuth-based authentication is implemented for end users.
2. Backend authorization checks enforce access boundaries for jobs and results.
3. Security validation evidence is captured in deployment sign-off artifacts.

## Consequences

- Short-term: minor delay before production launch while auth is implemented.
- Long-term: lower security risk, clearer ownership boundaries, and safer multi-user operation.
- Process: deployment approvals must verify auth/authz gates in `docs/deployment-checklist.md`.

## Notes

This ADR does not require authentication for purely local development loops.
It explicitly blocks non-local production deployment without auth/authz controls.
