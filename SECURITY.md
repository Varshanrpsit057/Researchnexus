# Security

How ResearchNexus protects accounts and data, what the production-readiness
audit (2026-10-09) found and changed, and what remains. Sign-in in detail:
[AUTHENTICATION.md](AUTHENTICATION.md).

## Reporting a problem

Email the maintainer (the repository owner) privately rather than opening a
public issue. Include what you found and how to reproduce it.

## Audit: what was found and what changed

| Area | Found | Now |
|---|---|---|
| Authentication | Development sign-in: **any password** opened **any email's** account, and an unknown email made a new one. A JWT sat in `localStorage` (readable by any script on the page). The JWT library (`python-jose`) has published CVEs. | Email + password (Argon2id) with an emailed one-time code on every sign-in; separate sign-up with email verification; password reset; server-side sessions in `HttpOnly`, `Secure`, `__Host-` cookies (hash stored); session rotation, expiry, revocation; `python-jose` removed. |
| Authorization | Paper uploads were allowed **without signing in**; jobs, papers and paper profiles could be read without signing in; any signed-in user could read or re-rank **another user's discovery run** and edit **the shared profile of any paper**. | Every API route except health, `/auth/*` entry points and the publisher list needs a session. Jobs and discovery runs are visible only to their owner (404 otherwise); a paper's shared profile is editable only by the person who produced it (403). Workspaces, chat, comparisons, gaps, directions, citations, usage and model keys were already owner-scoped; tests check isolation. |
| CSRF | n/a with bearer tokens -- but needed with cookies. | Foreign `Origin` refused on every state-changing request; a session-bound HMAC CSRF token required with cookie sessions. |
| Rate limiting | None. | Sign-in, sign-up, code checks, code sends (email bombing) and password changes limited in the database (shared by all servers); the live source check is limited per user. |
| Request size | Uploads were read into memory **before** the size check. | Bodies capped before they're read: 413 on `Content-Length`, and counted as they arrive when there is none (PDF uploads at `MAX_PDF_MB`, everything else at 1 MB). |
| Security headers | None. | API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `default-src 'none'` CSP, `no-store` on auth responses, HSTS outside development. Frontend (production build): a Content-Security-Policy (`default-src 'self'`, no plugins, no framing, API origin allowlisted), `nosniff`, `DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS; `X-Powered-By` off. |
| Debug surfaces | Interactive API docs (`/docs`, `/openapi.json`) always on. | Off outside development/test. The development mailbox exists only in development with the console mailer, answers only loopback. Production refuses the console mailer, dev rate-limit scaling and insecure cookies at start. |
| Errors and logs | Unhandled errors returned Starlette's plain 500; no request ids. | JSON 500 with a request id (no internals); every log line carries the request id; secret-shaped fields (`password`, `token`, `code`, `otp`, `cookie`, `secret`, ...) and `Bearer ...` values are redacted by the logger itself, tested. |
| Configuration | Missing secrets surfaced only when a route used them. Unset environment meant "development behaviour". | Unset environment = production, which refuses to start without its secrets, PostgreSQL, SMTP, https addresses and Secure cookies, naming each missing setting (never its value). |
| Dependencies | `pypdf` 6.17.0 (7 advisories; it parses uploaded PDFs), `next` 16.3.5 (a critical RCE advisory in `next/og` and several cache-poisoning/SSRF advisories), `sharp` and `source-map-js` advisories. | `pypdf` 6.19, `next` 16.4.0, `sharp`/`source-map-js` patched. `pip-audit`: no known vulnerabilities; `npm audit --omit=dev`: 0. CI fails on new high/critical advisories in shipped dependencies. |
| Containers | None existed. | Multi-stage images, non-root users (uid 10001), no secrets or `.env` in the build context (`.dockerignore`), health checks, `exec` entrypoints (signals reach the server), no compilers in the runtime image, model baked in (no runtime downloads). |
| Infrastructure | n/a | Database and file system in private subnets reachable only from the backend's security group; containers reachable only from the load balancer; encryption at rest (RDS, EFS) and in transit (TLS 1.2+ at the load balancer, EFS TLS); secrets only from Secrets Manager; least-privilege IAM; deploys by short-lived OIDC credentials. |

### Checked and found sound (unchanged)

- **SQL injection**: every query goes through SQLAlchemy expressions or bound parameters; no string-built SQL from input.
- **XSS**: React escapes all text; no `dangerouslySetInnerHTML` with user or document content; the CSP blocks third-party scripts.
- **SSRF**: scholarly APIs only on a fixed HTTPS host allowlist; open-access PDF downloads only from public HTTPS hosts that a scholarly API names, refusing private, loopback, link-local (including cloud metadata `169.254.169.254`) and reserved addresses, re-checked on every redirect; size-capped; must really be a PDF. LLM calls only to the fixed provider allowlist. No endpoint fetches a URL a user types.
- **Uploads**: PDF magic bytes, page count, encryption, per-page text volume (decompression bombs) and size are validated; files are stored under generated ids (no user-controlled paths, so no path traversal); PDFs are never served back.
- **Saved model keys**: Fernet-encrypted with `KEY_VAULT_SECRET`; only the last four characters are ever returned.
- **Paywalls**: full text is fetched only from copies a scholarly source lists as open access; nothing bypasses a paywall.

## Known limitations

- **Uploaded full text is attached to the shared paper record.** Papers are
  one shared catalogue (deduplicated by DOI/arXiv id/title). When someone
  uploads a PDF for a paper, its text becomes that paper's full text for
  every signed-in user whose workspace holds the same paper. The PDF file
  itself is never served, only passages in answers and comparisons. For a
  class or lab that may share documents this is a feature; for an open public
  deployment, restrict who may sign up
  (`RESEARCHNEXUS_SIGNUP_ALLOWED_DOMAINS`) or implement per-user visibility
  of uploaded text (record the uploader on the text and filter retrieval by
  it) before opening it to strangers.
- **Content-Security-Policy allows inline scripts** (`'unsafe-inline'`): Next.js
  bootstraps with inline scripts and per-request nonces would make every page
  dynamic. Third-party script sources are still blocked.
- **Development-only test tooling** has advisories (the `vitest` chain in
  `devDependencies`); it is never in an image or the browser bundle.
  Fixing it needs a major `vitest` upgrade.
- **No WAF**: application rate limits and the load balancer's header checks
  are the front line. Add AWS WAF (managed rule groups, IP rate rules) for a
  public launch.
- **Email codes** are as safe as the mailbox they go to. Authenticator-app
  (TOTP) or passkey second factors would be stronger; the session and
  challenge model leaves room for them.

## For developers

- Never commit `backend/.env`, `.env`, or `frontend/.auth/` (the e2e session
  file); all are git-ignored.
- Don't log request bodies, headers or cookies. Log ids and outcomes.
- New routes take `CurrentUser` (or `Auth`) and scope every query to
  `current_user.id`; a resource someone else owns answers 404.
- New state-changing routes need nothing extra for CSRF: the dependency checks
  it for cookie sessions.
- `python -m pip_audit` / `npm audit --omit=dev` before adding a dependency.
