# Environment variables

Every backend setting is an environment variable prefixed `RESEARCHNEXUS_`
(defined in `backend/app/config.py`). A local run reads `backend/.env` too
(git-ignored); real environment variables win over it. A sanitized template
is [.env.example](.env.example).

**Secrets** (marked 🔒) never go in source control, a Docker image, a
`NEXT_PUBLIC_*` variable or a log. Deployed, they come from AWS Secrets
Manager, injected into the container at start (DEPLOYMENT.md).

**Startup validation.** A `staging` or `production` server refuses to start
while a required setting is missing or set for local use only, and lists each
problem by variable name -- never its value
(`backend/app/startup_checks.py`). Check a configuration without starting:
`docker run --rm --env-file prod.env researchnexus-backend check`.

## Per environment

| | development | test | staging / production |
|---|---|---|---|
| How it's set | `python start.py` sets it | `tests/conftest.py` | the container's environment |
| `RESEARCHNEXUS_ENVIRONMENT` | `development` | `test` | `staging` / `production` (also the default when unset: fails closed) |
| Database | SQLite file `backend/data/researchnexus.db` | a temporary SQLite (or PostgreSQL, opt-in) | PostgreSQL (SQLite refused) |
| Tables | made at start, then migrated by `start.py` | made at start | only by `alembic upgrade head` (the deploy's migration step) |
| Email | printed in the terminal + development mailbox | kept in memory | SMTP (Amazon SES) required |
| Cookies | plain http (`localhost`) | plain http | `Secure`, `__Host-` names (required) |
| API docs (`/docs`) | on | on | off |
| Sign-in rate limits | x10 (`start.py`) | real | real (scaling refused) |

## Required everywhere

| Variable | | Description |
|---|---|---|
| `RESEARCHNEXUS_ENVIRONMENT` | | `development`, `test`, `staging` or `production`. Unset = `production`. |
| `RESEARCHNEXUS_SECRET_KEY` | 🔒 | At least 32 random characters. Keys the HMACs of emailed codes and CSRF tokens. Changing it invalidates codes in flight and every session's CSRF token (people sign in again). `RESEARCHNEXUS_JWT_SECRET` (the old name) is still read. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `RESEARCHNEXUS_KEY_VAULT_SECRET` | 🔒 | A Fernet key; encrypts the LLM keys people save. **Keep it stable**: with a new one, saved keys can't be decrypted (people re-enter them). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

## Database

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_DATABASE_URL` | 🔒 `sqlite:///./data/researchnexus.db` | SQLAlchemy URL. PostgreSQL: `postgresql+psycopg://user:password@host:5432/researchnexus` |
| `RESEARCHNEXUS_DB_HOST` | unset | Instead of a URL: the parts (how ECS passes the RDS database). When set, these build the URL. |
| `RESEARCHNEXUS_DB_PORT` | `5432` | |
| `RESEARCHNEXUS_DB_NAME` | `researchnexus` | |
| `RESEARCHNEXUS_DB_USER` | unset | |
| `RESEARCHNEXUS_DB_PASSWORD` | 🔒 unset | (RDS keeps it in Secrets Manager and can rotate it; a rotation reaches new containers at their start.) |
| `RESEARCHNEXUS_DB_POOL_SIZE` | `5` | Connections each server process keeps open (PostgreSQL). |
| `RESEARCHNEXUS_DB_MAX_OVERFLOW` | `5` | Extra connections allowed under load. Keep `(pool + overflow) x containers` under the database's limit (~80 on db.t4g.micro). |
| `RESEARCHNEXUS_DB_POOL_TIMEOUT_S` | `10` | How long a request waits for a free connection. |
| `RESEARCHNEXUS_DB_POOL_RECYCLE_S` | `1800` | Connections are replaced after this many seconds (and checked before each use). |
| `RESEARCHNEXUS_DB_AUTO_CREATE` | on in development/test, off elsewhere | Create missing tables at start. Deployed schemas change only through migrations. |

## Addresses

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_PUBLIC_APP_URL` | `http://localhost:3000` | Where people open the app. Used in emails and as an allowed origin. Must be `https://` in staging/production. |
| `RESEARCHNEXUS_CORS_ALLOWED_ORIGINS` | `["http://localhost:3000"]` | JSON list of origins allowed to call the API from a browser (and to make state-changing requests). Deployed behind one address, it is just that address. |

## Sign-in, sessions and codes

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_SESSION_MAX_AGE_HOURS` | `336` (14 days) | A session's absolute lifetime. |
| `RESEARCHNEXUS_SESSION_IDLE_HOURS` | `72` | A session unused this long ends. |
| `RESEARCHNEXUS_COOKIE_SECURE` | unset (= on outside development/test) | Must stay on in staging/production. |
| `RESEARCHNEXUS_SIGNUP_ALLOWED_DOMAINS` | `[]` (anyone) | JSON list of email domains that may create accounts, e.g. `["university.edu"]` (subdomains included). |
| `RESEARCHNEXUS_OTP_TTL_SECONDS` | `300` | How long an emailed code works. |
| `RESEARCHNEXUS_OTP_MAX_ATTEMPTS` | `5` | Wrong codes allowed per code. |
| `RESEARCHNEXUS_OTP_RESEND_COOLDOWN_SECONDS` | `60` | Wait before another code can be sent. |
| `RESEARCHNEXUS_OTP_MAX_RESENDS` | `3` | New codes per sign-in attempt. |
| `RESEARCHNEXUS_AUTH_RATE_LIMIT_SCALE` | `1` | Development only: multiplies the sign-in rate limits (`start.py` uses 10). Refused elsewhere. |

## Email

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_EMAIL_BACKEND` | `console` in development, `memory` in test, `smtp` elsewhere | `smtp` is required in staging/production. |
| `RESEARCHNEXUS_EMAIL_FROM` | unset | Sender, on an SES-verified domain: `ResearchNexus <no-reply@your-domain>`. Required for smtp. |
| `RESEARCHNEXUS_SMTP_HOST` | unset | `email-smtp.<region>.amazonaws.com` for SES. Required for smtp. |
| `RESEARCHNEXUS_SMTP_PORT` | `587` | |
| `RESEARCHNEXUS_SMTP_USERNAME` | 🔒 unset | SES SMTP credentials (not IAM access keys). |
| `RESEARCHNEXUS_SMTP_PASSWORD` | 🔒 unset | |
| `RESEARCHNEXUS_SMTP_STARTTLS` | `true` | |
| `RESEARCHNEXUS_SMTP_TIMEOUT_S` | `10` | Per attempt (two retries on temporary failures). |

## Scholarly sources and full text

All optional: everything works without keys, within each source's keyless quota.

| Variable | Description |
|---|---|
| `RESEARCHNEXUS_CONTACT_EMAIL` | An address the sources may contact about this app's traffic. OpenAlex and Crossref answer faster with it; Unpaywall (open-access full text) needs it. |
| `RESEARCHNEXUS_OPENALEX_API_KEY` 🔒 | Raises OpenAlex's daily budget (keyless use shares one per IP address). |
| `RESEARCHNEXUS_SEMANTIC_SCHOLAR_API_KEY` 🔒 | Raises Semantic Scholar's rate limit. |
| `RESEARCHNEXUS_CORE_API_KEY` 🔒 | Turns on CORE search and its full-text copies. |
| `RESEARCHNEXUS_EXTERNAL_TIMEOUT_S` (`15`), `_EXTERNAL_MAX_RETRIES` (`3`), `_EXTERNAL_BACKOFF_BASE_S` (`0.5`), `_EXTERNAL_CACHE_TTL_S` (`300`) | How patiently the sources are asked. |
| `RESEARCHNEXUS_METADATA_LOOKUP` (`true`) | Complete an uploaded paper's record from its DOI or title. |
| `RESEARCHNEXUS_FULLTEXT_AUTO` (`true`) | Look for open-access full text when papers join a workspace. |
| `RESEARCHNEXUS_FULLTEXT_TIMEOUT_S` (`30`), `_FULLTEXT_CONCURRENCY` (`3`) | Full-text download limits. Only legal open-access copies are fetched (public HTTPS hosts a scholarly API names as open access; PDF only; size-capped). |

## Uploads, storage and requests

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_DATA_DIR` | `data` (`/data` in the image) | Uploaded PDFs and workspace indexes. Deployed: a persistent volume (EFS). |
| `RESEARCHNEXUS_MAX_PDF_MB` | `30` | Larger uploads are refused with 413 before they're read. |
| `RESEARCHNEXUS_MAX_PAGES` | `60` | |
| `RESEARCHNEXUS_MAX_PAGE_CHARS` | `500000` | Guard against decompression bombs. |
| `RESEARCHNEXUS_MAX_JSON_BODY_KB` | `1024` | Any other request body larger than this is refused with 413. |

## CPU-heavy work and models

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_DISCOVERY_EMBEDDER` | `fastembed` | The relevance model behind discovery's semantic ranking (`BAAI/bge-small-en-v1.5`, ONNX, CPU). `none` turns semantic signals off. |
| `RESEARCHNEXUS_RAG_EMBEDDER` | `fastembed` | The same model for chat and comparison retrieval (falls back to the lexical index when it can't load). |
| `RESEARCHNEXUS_RAG_RERANKER` | `none` | `cross-encoder` needs the optional `.[embeddings]` extra (torch). |
| `RESEARCHNEXUS_MODELS_DIR` | `<data_dir>/models` (`/opt/models` in the image, baked in) | Where models are cached. |
| `RESEARCHNEXUS_EMBEDDING_THREADS` | unset (all cores) | CPU threads for the embedding model. On a 1-vCPU container, `1` keeps requests responsive. |
| `RESEARCHNEXUS_GAP_LLM_CONCURRENCY` (`6`), `_COMPARE_LLM_CONCURRENCY` (`4`) | | Model calls made at once (each with the reader's own key). |

Ranking, trail, RAG, comparison, gaps, directions and orchestrator tuning
(`RANK_*`, `TRAIL_*`, `RAG_*`, `COMPARE_*`, `GAP_*`, `DIRECTION_*`,
`ORCHESTRATOR_*`, `CHUNK_*`, `PROFILE_MAX_CONTEXT_CHARS`) keep their calibrated
defaults; each is documented where it is defined in `backend/app/config.py`.

## Language models

People bring their own keys (OpenAI, Groq, DeepSeek, OpenRouter, Together,
Gemini) in Settings > Language models; they are stored encrypted with the
key-vault secret and never shown again. The server needs no model key.

| Variable | Description |
|---|---|
| `RESEARCHNEXUS_LLM_MODELS` | JSON map overriding a provider's default model, e.g. `{"deepseek": "deepseek-chat"}`. |

## Logging

| Variable | Default | Description |
|---|---|---|
| `RESEARCHNEXUS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. One JSON line per event on stdout, each with its request id. Secret-shaped fields are always redacted. |

## Frontend

The frontend has one setting, and it is public (compiled into the browser bundle):

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` when unset | Where the API is. **Empty** = this same site (the API under `/api` on the app's address): the production build, so one image serves every environment. `start.py` sets `http://localhost:8000`; `docker compose` builds with it too. |

Never put a secret in a `NEXT_PUBLIC_*` variable.

## Tests only

| Variable | Description |
|---|---|
| `RESEARCHNEXUS_TEST_POSTGRES_URL` | A PostgreSQL server for the migration tests (CI provides one). |
| `RESEARCHNEXUS_TEST_ON_POSTGRES=1` | Run the integration tests on it (each on its own database). |
