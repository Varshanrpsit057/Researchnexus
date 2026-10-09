# Authentication

ResearchNexus accounts are an email address and a password, and every sign-in
is confirmed with a six-digit code emailed to that address (email-based
two-factor authentication). There is no other way in: no sign-in without the
code, no development bypass on a deployed server.

Code: `backend/app/routers/auth.py` (the API), `backend/app/security/`
(`passwords.py`, `codes.py`, `sessions.py`, `rate_limit.py`),
`backend/app/services/mail.py` (email), `backend/app/deps.py` (who is signed in),
`frontend/src/app/{sign-in,sign-up,forgot-password}/`,
`frontend/src/components/auth/`, `frontend/src/lib/auth/`.

## The flows

| Flow | Page | Steps |
|---|---|---|
| Sign up | `/sign-up` | name, email, password, confirm password -> a code is emailed -> enter it -> the account is created, signed in |
| Sign in | `/sign-in` | email, password -> a code is emailed -> enter it -> signed in |
| Forgot password | `/forgot-password` | email -> a code is emailed -> enter it with a new password -> signed in, every other session ended |
| Change password | Settings > Account | current password, new password -> every other session ended, this one replaced |
| Sign out | header, Settings > Account | the session is revoked on the server and the cookies cleared |
| Other devices | Settings > Account | the signed-in devices, each revocable; "sign out all other devices" |

API (all under `/api/v1`):

| Endpoint | Purpose |
|---|---|
| `POST /auth/signup` `{name, email, password}` | starts sign-up; 202 with a challenge |
| `POST /auth/login` `{email, password}` | checks the password; 200 with a challenge (no session yet) |
| `POST /auth/verify` `{challenge_id, code}` | finishes sign-up or sign-in: the only place (with reset) a session is made |
| `POST /auth/resend` `{challenge_id}` | a new code for the same challenge (the old one stops working) |
| `POST /auth/password/forgot` `{email}` | starts a reset; 202 with a challenge |
| `POST /auth/password/reset` `{challenge_id, code, password}` | sets the password, ends every other session, signs this browser in |
| `POST /auth/password/change` | signed in: changes the password |
| `POST /auth/logout` | revokes the session, clears the cookies |
| `GET /auth/session` | who is signed in (`{"user": null}` when nobody; never a 401) |
| `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others` | signed-in devices |
| `GET /me`, `PATCH /me` | the account (name, default model provider) |

A challenge reply says where the code went (partly hidden), how long it lasts
(`expires_in`), when another can be sent (`resend_in`) and how many more
(`resends_left`). It never contains the code.

## Security properties

**Passwords.** Argon2id (argon2-cffi defaults: 64 MiB, 3 passes, 4 lanes;
OWASP's first recommendation), upgraded on sign-in when the parameters
change. Policy (checked on the server, mirrored as a live checklist on the
pages): 10-128 characters, a letter and a number or symbol, not a common
password, not built from the email address. A wrong email and a wrong
password get the same answer in the same time (a dummy hash is checked when
there is no account).

**Codes.** Six digits from the OS's CSPRNG (`secrets`). Stored only as an
HMAC-SHA256 keyed with `RESEARCHNEXUS_SECRET_KEY` (a copy of the database
can't be turned back into live codes). Valid 5 minutes, 5 tries per code (the
fifth wrong one closes the challenge, even to the right code), single use
(an atomic update: two requests with the same code can't both succeed),
bound to one purpose (a reset code can't finish a sign-in and vice versa).
A new code needs a 60-second wait and is allowed 3 times per challenge;
every new code replaces the previous one.

**No account enumeration.** Signing up with an email that already has an
account answers exactly like a new sign-up; the owner of that address gets
an email saying someone tried (with no code), and no code can finish the
decoy challenge. A reset for an unknown email also answers normally, and its
email (when there is an account) is sent after the reply, so the timing
doesn't differ. Sign-in failures are one message for both cases.

**Sessions.** A random 256-bit token in an `HttpOnly`, `SameSite=Lax`
cookie, `Secure` and `__Host-`-prefixed outside development (so only this
exact host, over HTTPS, can set or read it). The database keeps only its
SHA-256. A session ends after 14 days, after 3 days unused, on sign-out, or
when revoked (password change or reset, "sign out other devices"). Every
successful sign-in makes a new session and revokes any the browser already
had (session fixation). Page scripts never see the token: the frontend has
no token in storage at all.

**CSRF.** Two layers. (1) Every state-changing request from a browser page
on another origin is refused (`Origin` checked against the app's origins).
(2) A state-changing request authenticated by the cookie must carry
`X-CSRF-Token`: an HMAC of the session token, given to the page in a
readable companion cookie (`rn_csrf`) that another site can't read.
Requests authenticated with `Authorization: Bearer <session token>` (scripts,
tests) need no CSRF token, since a browser never adds that header itself.

**Rate limits** (counted in the database, so shared by every server):

| Limit | Allowance |
|---|---|
| sign-in attempts per IP | 30 / 15 min |
| failed passwords per account | 10 / 15 min |
| codes sent per email address (sign-up, sign-in, reset, resend) | 8 / hour |
| codes sent per IP | 30 / hour |
| code checks per IP | 40 / 15 min |
| sign-ups per IP | 10 / hour |
| password changes per account | 10 / hour |

Over a limit the API answers 429 with `Retry-After`, and the page says how
long to wait. (A development server started by `start.py` multiplies these by
10 so repeated test runs fit; any other environment refuses that setting.)

**Who may sign up.** Anyone, unless `RESEARCHNEXUS_SIGNUP_ALLOWED_DOMAINS` is
set (e.g. `["university.edu"]`; subdomains included). Existing accounts are
unaffected.

**Logging.** Auth events are logged (`auth_login_failed`, `auth_code_rejected`,
`auth_rate_limited`, `auth_signup_completed`, ...) with the client IP and a
hashed account reference -- never a password, code, cookie or token: the log
processor strips any field named like one (`backend/app/telemetry/logging.py`),
and a test (`test_codes_and_passwords_never_reach_the_log`) checks it.

## Accounts made before passwords

Until this change any password signed in to any email. Those accounts keep
everything (same id, workspaces, keys); they have no password, so signing in
fails until the owner chooses **Forgot password**: the emailed code proves
the address, the new password is set, and the email is marked verified.
Migration `0021` adds the new columns and tables without touching existing
rows.

## Email delivery

| Environment | `RESEARCHNEXUS_EMAIL_BACKEND` | What happens |
|---|---|---|
| development (`start.py`) | `console` | printed in the backend's terminal; readable at `GET /api/v1/dev/mailbox?email=...` from this machine only; never delivered |
| test | `memory` | kept in the process for the tests |
| staging / production | `smtp` (required) | sent through Amazon SES's SMTP interface (STARTTLS, port 587) |

A staging or production server refuses to start with `console` or `memory`.
The development mailbox exists only in development with the console backend,
and answers only loopback requests.

Delivery failures: a temporary SMTP failure (dropped connection, 4xx) is
retried twice (1 s, 3 s). If a sign-up, sign-in or resend email still can't be
sent, the API answers 503 `email_unavailable` and the page asks to try again
in a minute; the failure is logged as `email_undeliverable` (purpose and
recipient domain only) and counted by a CloudWatch alarm. Reset emails are
sent after the reply (so the reply can't reveal whether an account exists);
their failures are logged the same way.

### Setting up Amazon SES (one-time, needs AWS and DNS access)

1. **Verify the sending domain** (SES console > Identities > Create identity >
   Domain). Publish the three DKIM CNAME records it gives in your DNS. Add an
   SPF record that includes `amazonses.com` (or use a custom MAIL FROM
   domain) and a DMARC record (`_dmarc.<domain>  TXT  "v=DMARC1; p=quarantine; rua=mailto:..."`).
2. **Leave the sandbox.** New SES accounts can only send to verified
   addresses (and 200 emails/day). Request production access (SES console >
   Account dashboard > Request production access): use case "transactional:
   sign-in codes and password resets", expected volume, how bounces are
   handled. Until it is granted, verify each test recipient's address in SES,
   or sign-up emails to other addresses fail (and the alarm fires).
3. **Create SMTP credentials** (SES console > SMTP settings > Create SMTP
   credentials). This makes an IAM user allowed only `ses:SendRawEmail`;
   the generated SMTP username and password go into the app secret as
   `SMTP_USERNAME` and `SMTP_PASSWORD` (DEPLOYMENT.md). They are not the IAM
   user's access keys.
4. **Set** `RESEARCHNEXUS_EMAIL_FROM` to an address on the verified domain,
   e.g. `ResearchNexus <no-reply@your-domain>`. The SMTP host is
   `email-smtp.<region>.amazonaws.com` (the CloudFormation stack sets it).
5. **Check**: sign up with a real inbox; the code should arrive within
   seconds. If not, the backend log has `email_undeliverable` with the SMTP
   reply code (554 "Email address is not verified" = still in the sandbox).

## Tests

Backend (`backend/tests/integration/test_auth_api.py`,
`tests/unit/test_mail_and_passwords.py`, `tests/unit/test_startup_checks.py`,
`tests/integration/test_health_and_middleware.py`): sign-up, duplicate
registration, email verification, right and wrong passwords, code generation
and storage, expiry, reuse, too many attempts, resend cooldown and limit,
rate limiting (passwords and email bombing), purpose binding, sessions only
after the code, session fixation, idle and absolute expiry, logout, CSRF,
foreign origins, device revocation, password reset and change, the legacy
account claim, protected endpoints refusing anonymous requests, per-user
isolation, the production configuration, SMTP retry and failure, and that
codes and passwords never reach the log.

Browser (`frontend/tests/auth/sign-in-and-out.spec.ts`): the separate sign-in
and sign-up pages, form validation, the password checklist and show/hide, the
code step (wrong code, then the real one from the development mailbox),
redirect back after sign-in, the session surviving a reload, the cookie being
invisible to page scripts, sign-out, the forgotten-password flow, and that
`?next=` can never send the reader to another site.

Every other browser spec signs in once per worker through the same real flow
(`frontend/tests/fixtures.ts`, `tests/auth-helpers.ts`).
