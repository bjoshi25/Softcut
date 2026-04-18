# Security And Secrets

Security discipline starts before a project has a stack.

## Secrets

- Never commit secrets.
- Document environment variables only in `.env.example`.
- Use safe placeholders, not real credentials or production endpoints.
- Rotate any credential that may have been exposed.

## Logging And Artifacts

- Avoid printing secrets.
- Redact tokens, passwords, private keys, session identifiers, and sensitive
  customer or operational data.
- Treat generated logs, screenshots, exports, reports, caches, and build
  artifacts as possible secret surfaces.

## Access

- Prefer least privilege.
- Avoid broad local credentials for narrow tasks.
- Separate development, test, and production access when the project defines
  those environments.

## Inputs

- Validate untrusted input at boundaries.
- Fail clearly when input is invalid.
- Avoid shell interpolation or unsafe command construction with untrusted data.
- Document security-relevant assumptions in plans or ADRs.
