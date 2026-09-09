# ResearchNexus backend

FastAPI backend. Phase 1 (auth/BYOK foundation) and Phase 2 (PDF ingestion)
are implemented; see `docs/architecture/ResearchNexus_Implementation_Roadmap.md`
for the full build sequence.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows; use `source .venv/bin/activate` on Linux/macOS
pip install -e ".[dev]"
```

## Run the tests / linters

```bash
pytest -q
ruff check .
mypy app tests
```

## Local dev secrets

Two settings have no default (by design -- see `app/config.py`) and must be
set before the auth or BYOK-key endpoints are used:

```bash
export RESEARCHNEXUS_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export RESEARCHNEXUS_KEY_VAULT_SECRET="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

Everything else (PDF ingestion, health) works without them. Optional heavy
retrieval backends (`sentence-transformers`/`torch`, `faiss-cpu`) are not
installed by the base `pip install -e .` -- add `.[embeddings]` / `.[faiss]`
when a later phase needs them.

## Run the dev server

```bash
uvicorn app.main:app --reload
```

## Apply migrations

```bash
alembic upgrade head
```
