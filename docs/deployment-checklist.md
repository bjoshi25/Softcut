# Deployment Checklist

This checklist defines release gates for Softcut environments.

## Hard Gates (Must Pass)

- [ ] Authentication and authorization are enabled for all non-local deployments.
- [ ] OAuth login is implemented and verified end-to-end for intended identity provider(s).
- [ ] Backend authorization enforcement is active for job and artifact access.
- [ ] Secrets are configured via environment variables and not embedded in source code.
- [ ] Security-sensitive keys (for example service-role keys) are never exposed to the client.

## Auth Gate Policy

Production deployment is blocked until authentication and authorization are implemented and validated.
At minimum, this includes:

- authenticated user identity for app access
- server-side access checks for job ownership and results
- documented incident rollback procedure for auth failures

## Verification Evidence

Record links or notes for:

- auth flow test evidence
- authorization access-control tests
- deployment sign-off approver
