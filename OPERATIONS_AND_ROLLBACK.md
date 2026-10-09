# Operations and rollback

Running ResearchNexus once it is deployed ([DEPLOYMENT.md](DEPLOYMENT.md)):
health, logs, alarms, backups, restores, rollbacks, moving data, and fixing
what usually goes wrong.

## Health

| Endpoint | Answers | Used by |
|---|---|---|
| `GET /health/live` | 200 while the process serves | the container health check (a database outage must not restart healthy containers in a loop) |
| `GET /health/ready` | 200 when the database answers, its schema is the one this release expects, and the file store is writable; **503** otherwise, naming which | the load balancer (no traffic to a container that isn't ready) and the deploy's smoke test |
| `GET /health/providers` | always 200: email set up or not, which scholarly sources have keys, and the result of a check of all of them run at most every 10 minutes | people, dashboards. An unavailable research API degrades a feature, never readiness |
| `GET /health` | the original summary (status + database) | older clients |

`schema: migration_pending` means the code is newer than the database: run
the migration task (DEPLOYMENT.md step 7).

## Logs

Every backend line is one JSON object on stdout, shipped to CloudWatch Logs
(`/researchnexus/<env>/backend`, 30-day retention). Each request writes one
`http_request` line (method, route template, status, milliseconds, user id)
and every line it causes carries its `request_id` -- also returned to the
browser as `X-Request-ID`, and shown in the body of an unexpected 500. Ask a
user for that id, then:

```
fields @timestamp, event, level, @message
| filter request_id = "6f1c..."
| sort @timestamp asc
```

Useful CloudWatch Logs Insights queries:

```
# slowest routes, last hour
filter event = "http_request" | stats avg(ms), pct(ms, 95), count() by route | sort pct(ms, 95) desc

# errors by route
filter event = "http_request" and status >= 500 | stats count() by route

# failed sign-ins by address (guessing?)
filter event in ["auth_login_failed", "auth_code_rejected", "auth_rate_limited"] | stats count() by ip | sort count() desc

# a scholarly source failing
filter event = "upstream_failed" | stats count() by host, outcome

# background jobs that failed, and jobs cut off by a restart
filter event like /_job_failed$/ or event = "interrupted_jobs_failed"

# email that couldn't be sent
filter event = "email_undeliverable"
```

Never in the logs, by construction: passwords, codes, session or CSRF tokens,
cookies, model keys, the secret key (the log processor redacts such fields,
and a test checks the sign-in flow).

## Alarms

Sent to the SNS topic `researchnexus-<env>-alarms` (email subscription):

| Alarm | Means | First look |
|---|---|---|
| `ServerErrorsAlarm` | ≥10 backend 5xx in 5 min | logs: `level = "error"`, then the request ids |
| `BackendUnhealthyAlarm` | no ready backend container for 3 min | `/health/ready` checks; ECS service events; the database |
| `SlowResponsesAlarm` | p90 latency > 5 s for 10 min | the slowest-routes query; CPU alarm; database CPU |
| `BackendCpuAlarm` / `BackendMemoryAlarm` | > 85% for 15 min | discovery/gap runs in progress? Raise the task size or count |
| `DatabaseCpuAlarm` / `DatabaseStorageAlarm` | > 80% CPU / < 2 GB free | slow queries (Performance Insights can be switched on), storage autoscaling's cap |
| `UnhandledErrorsAlarm` | ≥5 unexpected errors in 5 min | logs: `event = "unhandled_error"` (with tracebacks) |
| `EmailFailuresAlarm` | sign-in email failing | SES sandbox, sending quota, SMTP credentials (see Troubleshooting) |
| `FailedSignInsAlarm` | ≥50 failed or rate-limited sign-ins in 5 min | the failed-sign-ins query; consider WAF rate rules |

Job failures (`JobFailures`) and provider failures (`ProviderFailures`) are
metrics without alarms (sources fail now and then by nature); graph them on a
dashboard.

## Backups and restore

**Database.** RDS takes automated daily snapshots and keeps transaction logs:
point-in-time restore to any second within the retention period (7 days in
staging, 14 in production as recommended). Manual snapshots before risky
changes: `aws rds create-db-snapshot --db-instance-identifier researchnexus-<env> --db-snapshot-identifier pre-<change>-$(date +%Y%m%d)`.
Deleting the stack keeps a final snapshot (and deletion protection must be
switched off first).

To restore (into a **new** instance -- never over the running one):

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier researchnexus-production \
  --target-db-instance-identifier researchnexus-production-restored \
  --restore-time 2026-10-09T08:00:00Z \
  --db-subnet-group-name <the stack's DatabaseSubnetGroup> \
  --vpc-security-group-ids <the stack's DatabaseSecurityGroup> \
  --no-publicly-accessible
```

Then check the restored data (a one-off task with `RESEARCHNEXUS_DB_HOST`
pointing at it), and either copy the rows you need back, or switch the
backend to it: update the backend task definition's `RESEARCHNEXUS_DB_HOST`
(its password is the source instance's at that time) and roll the service.
Afterwards bring the stack's own `Database` resource back in line (or import
the restored instance) -- write the steps down as you go.

**Files.** EFS is backed up daily by AWS Backup (35-day default retention).
Restore whole or single files from the AWS Backup console into a new
directory, then move them into `/researchnexus`.

**Secrets.** Secrets Manager keeps previous versions. The key-vault secret
must never be lost: without it, saved model keys can't be decrypted (people
re-enter them; nothing else is lost).

## Rolling back

**A release (application code).** Every release is an immutable image tagged
with its git SHA, and its task definitions keep their revisions.

- *Automatically*: a rollout whose containers never become healthy is undone
  by the ECS deployment circuit breaker; a rollout that is healthy but fails
  the pipeline's smoke test is undone by the pipeline (previous task
  definitions).
- *By hand, fastest*: point each service at the previous revision:

  ```bash
  aws ecs update-service --cluster researchnexus-production --service backend  --task-definition researchnexus-production-backend:<previous revision>
  aws ecs update-service --cluster researchnexus-production --service frontend --task-definition researchnexus-production-frontend:<previous revision>
  aws ecs wait services-stable --cluster researchnexus-production --services backend frontend
  ```

- *Through the pipeline*: Actions > Deploy > Run workflow with the previous
  commit's SHA (its images still exist; the last 30 are kept).

**The database schema is not rolled back.** Migrations are written to be
additive (new tables, new nullable columns, wider types), so the previous
release runs against the newer schema. A migration that must remove or
rewrite data is split into a release that stops using it and a later release
that removes it ("expand, then contract"), each with a snapshot first. To
undo a migration deliberately: snapshot, then run a one-off task with
`["python", "-m", "alembic", "downgrade", "<revision>"]` -- never as part of an
automatic rollback. (Example: downgrading 0022 on PostgreSQL refuses, rather
than truncates, if any venue/URL is now longer than the old column allowed.)

**Infrastructure.** CloudFormation rolls a failed stack update back by
itself. **When you change the stack later, pass the images that are running
now** (`BackendImage`, `FrontendImage` = the current SHA tags): the pipeline
updates the services outside CloudFormation, so a stack update with the old
image parameters would quietly roll the app back.

## Moving existing data into PostgreSQL

A local or single-machine install keeps its data in SQLite. To bring it into
a new deployment (`backend/app/maintenance/sqlite_to_postgres.py`):

1. Stop the local servers (`python start.py stop`), and migrate the SQLite
   file to the latest revision (`python start.py` does it, with a backup).
2. Migrate the empty PostgreSQL database (DEPLOYMENT.md step 7) -- and don't
   start the backend service yet.
3. From a machine that can reach the database (a one-off task, or an
   SSM/bastion session; it isn't public), dry run first:

   ```bash
   python -m app.maintenance.sqlite_to_postgres data/researchnexus.db "postgresql+psycopg://researchnexus:<password>@<endpoint>:5432/researchnexus" --dry-run
   python -m app.maintenance.sqlite_to_postgres data/researchnexus.db "postgresql+psycopg://..."
   ```

   It backs the SQLite file up first, refuses a database that already has
   rows, copies everything in one transaction and checks every table's row
   count. If it finds **orphans** (rows pointing at rows that were deleted --
   SQLite doesn't enforce foreign keys unless asked), it stops and lists them;
   `--skip-orphans` copies everything else and leaves them in the SQLite file.
   Measured on this project's development database: 29,146 rows in 21 tables
   copied and verified, 452 orphans (old test runs' leftovers) left out.
4. Copy the PDFs: `backend/data/papers/` to the EFS access point's root
   (`/researchnexus/papers/`), e.g. with a one-off task mounting both, or
   AWS DataSync.
5. Start the backend (DEPLOYMENT.md step 8). Everyone signs in with their
   email and chooses **Forgot password** once to set a password (accounts
   from before passwords).

## Routine tasks

| Task | How |
|---|---|
| Scale | Stack parameters `BackendDesiredCount`, `BackendCpu`/`BackendMemory` (keep `(DB_POOL_SIZE + DB_MAX_OVERFLOW) x containers` below the database's connection limit). |
| Rotate `SECRET_KEY` | Put a new value in the app secret, roll the backend. Codes in flight stop working; people sign in again. |
| Rotate SES SMTP credentials | Create new ones, update the secret, roll the backend, delete the old IAM user. |
| Database password | RDS rotates it in its own secret when rotation is on; roll the backend afterwards (containers read it at start). |
| Restrict sign-up to a domain | `RESEARCHNEXUS_SIGNUP_ALLOWED_DOMAINS` (task definition environment). |
| Pause staging | `BackendDesiredCount=0`, `FrontendDesiredCount=0`; stop the database (`aws rds stop-db-instance`, restarts itself after 7 days). |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Containers stop at start; log: `ResearchNexus can't start with this configuration:` | a required setting missing or local-only | the log names each variable; fix the task definition / secret. `docker run --rm --env-file x.env <image> check` validates offline |
| Backend never becomes healthy; `/health/ready` → `schema: migration_pending` | migrations not run for this release | run the migration task (DEPLOYMENT.md step 7) |
| `/health/ready` → `database: error` | security group, wrong host, password rotated | from a task: `RESEARCHNEXUS_DB_*`; RDS events; SG `DatabaseSecurityGroup` allows the backend SG |
| `/health/ready` → `storage: error` | EFS mount or permissions | ECS stopped-task reason ("ResourceInitializationError" = mount); the access point's uid/gid 10001 |
| Task stops with `ResourceInitializationError: unable to pull secrets` | execution role can't read the secret, or wrong ARN/key name | `AppSecretArn` parameter; JSON keys exactly `SECRET_KEY`, `KEY_VAULT_SECRET`, `SMTP_USERNAME`, `SMTP_PASSWORD` |
| Sign-up says "We couldn't send the email" | SES: sandbox (recipient not verified → 554), wrong SMTP credentials (535), sender domain not verified | `email_undeliverable` log line has the SMTP code; AUTHENTICATION.md SES steps |
| Codes arrive in spam | missing DKIM/SPF/DMARC | publish the records; use a custom MAIL FROM domain |
| Every POST answers 403 `bad_origin` | the app is opened at an address not in `CORS_ALLOWED_ORIGINS`/`PUBLIC_APP_URL` | set both to the exact `https://` address people use |
| Every POST answers 403 `csrf_failed` | a proxy or CDN strips cookies or the `X-CSRF-Token` header | forward cookies and that header; don't cache `/api/*` |
| Signed out on every page load | cookies not stored: served over http, or a different host than the certificate's | always https on the app's own address (`__Host-` cookies require it) |
| Chat answers cut off after a minute | load balancer idle timeout too short | 300 s in the template; a CDN in front needs a similar origin timeout |
| Discovery slow or "partial" | a scholarly API rate-limiting the shared IP | `upstream_failed` by host; set `CONTACT_EMAIL` and the optional API keys |
| Uploads refused with 413 | over `MAX_PDF_MB` | raise it (and check the load balancer allows it) |
| High CPU during discovery | embedding hundreds of candidates | `EMBEDDING_THREADS` lower for responsiveness, or a larger task |

## Performance without a GPU

Nothing in ResearchNexus needs a GPU, and none is used on AWS.

- **The server's only model** is `BAAI/bge-small-en-v1.5` on ONNX Runtime
  (CPU build, ~70 MB, baked into the image), for discovery relevance and
  workspace search. Measured on a 28-core desktop CPU: **~28 abstracts per
  second on 1 thread, ~150 per second on all cores**; model load ~1 s. On a
  1-vCPU Fargate task expect the one-thread figure: a discovery run embedding
  200-400 candidates spends ~7-15 s embedding, part of it while waiting for
  the sources. With `onnxruntime-gpu` installed, fastembed uses CUDA by itself;
  it would be several times faster, but at this model size CPU is adequate,
  and that path is not part of the images or tests. The log line
  `embedding_model_loaded` names the execution provider that actually ran --
  a fallback to the CPU is never reported as GPU work.
- **Language models** run at the reader's provider (their key); the server
  does no generation.
- **PDF reading** (pypdf/pdfplumber) is CPU-only and single-threaded per upload; its time grows with the page count (uploads are capped at `MAX_PAGES`).
- **In the browser**, the animated backgrounds pick themselves by the
  graphics available: the neural network on a dedicated GPU, light fibers on
  integrated graphics or a weak (software) GPU, a still background without
  WebGL, and nothing moves under `prefers-reduced-motion`. Settings >
  Appearance can force any of them. Every page works the same with any of
  them.
