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

Discovery's ranking, chat and comparison search with one real embedding
model, `BAAI/bge-small-en-v1.5` through `fastembed` (ONNX, no torch, no
GPU needed). It is downloaded once, on first use, to `data/models/`
(about 70 MB). Offline before that first download, chat and comparison
search a workspace by its words instead (the lexical index) and discovery
ranks without its semantic signals -- nothing falls back to made-up
vectors. A cross-encoder reranker is optional
(`RESEARCHNEXUS_RAG_RERANKER=cross-encoder`, needs `.[embeddings]`);
without it the retrieval order stands. The test suite pins deterministic
stand-ins (`tests/conftest.py`).

## Scholarly sources

Discovery searches OpenAlex, Semantic Scholar, arXiv, Crossref, DBLP, CORE
and Europe PMC. None needs a key, but the keyless quotas are small, and
these optional settings in `backend/.env` raise them:

| Setting | What it does |
|---|---|
| `RESEARCHNEXUS_CONTACT_EMAIL` | Sent to OpenAlex and Crossref (their "polite pool") and to Unpaywall, which requires it. Without it, Unpaywall is skipped. |
| `RESEARCHNEXUS_CORE_API_KEY` | CORE's free key. Without it, CORE allows only a few requests, so discovery asks it once per run. |
| `RESEARCHNEXUS_OPENALEX_API_KEY` | OpenAlex's key. Keyless use has a daily budget shared by everyone on the same IP address. |
| `RESEARCHNEXUS_SEMANTIC_SCHOLAR_API_KEY` | Raises Semantic Scholar's rate limit. |
| `RESEARCHNEXUS_METADATA_LOOKUP` | `true` by default. After an upload is read, its record (authors, year, venue, publisher, DOI) is completed from Crossref, OpenAlex, Semantic Scholar or arXiv, using the PDF's DOI or its exact title. |

Full text is downloaded from any public HTTPS host that a scholarly API
(arXiv, Europe PMC, Unpaywall, OpenAlex, CORE or Semantic Scholar) names for
the paper. The download refuses private and loopback addresses and checks
every redirect, and it is size-capped. A paywalled PDF can't be fetched;
upload it on the paper's page instead (`POST /api/v1/papers/{id}/pdf`).

## Maintenance

Run these from `backend/`, preferably with the backend stopped (both write
to the SQLite database).

```bash
# read every uploaded PDF again with the current reader (abstract, DOI,
# columns), then complete each record from the scholarly sources;
# backs up the database to data/researchnexus.db.bak-pre-reread-* first
python -m app.maintenance.reread_uploads [--no-metadata | --records-only]

# name the publisher of stored papers from their DOI prefix, and normalise
# publisher names ("Institute of Electrical and Electronics Engineers" -> IEEE)
python -m app.maintenance.backfill_publishers
```

A single paper can also be re-read from its page ("Read the PDF again", or
`POST /api/v1/papers/{id}/reread`).

## Run the dev server

From the repo root, one command checks and installs what's missing (this
virtualenv and its packages, `.env`'s local secrets, migrations, the
frontend's `node_modules`), then runs the backend on http://localhost:8000
and the frontend on http://localhost:3000 -- only those ports, never a
fallback:

```bash
python start.py            # both; Ctrl+C stops both
python start.py backend    # only this API
python start.py stop       # stop a server left over from an earlier run
python start.py status
```

Or run just the API by hand from `backend/`:

```bash
uvicorn app.main:app --port 8000
```

## Apply migrations

```bash
alembic upgrade head
```
