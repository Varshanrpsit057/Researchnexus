# ResearchNexus

An evidence-grounded research workspace: start from one paper, and
ResearchNexus reads it, finds and ranks the related work, connects it in a
research trail and graph, and lets you chat with, compare, and find gaps and
directions across the papers -- every claim pointing at the passage it rests on.

- **Frontend**: Next.js 16 (`frontend/`), the dark navy-and-mint design in [DESIGN.md](DESIGN.md).
- **Backend**: FastAPI + SQLAlchemy (`backend/`), PostgreSQL deployed, SQLite locally.
- **Sign-in**: email + password, confirmed by an emailed code ([AUTHENTICATION.md](AUTHENTICATION.md)).
- **Language models**: each person brings their own key (OpenAI, Groq, DeepSeek, OpenRouter, Together, Gemini). No GPU needed anywhere.

## Run it locally

Python 3.10+ and Node 20.9+:

```bash
python start.py
```

It installs what's missing, creates local secrets and the database, and starts
the frontend on http://localhost:3000 and the backend on http://localhost:8000
(those ports only). In this development mode, sign-up and sign-in codes are
printed in the backend's terminal instead of emailed. `python start.py stop`
stops both.

### Running it on another computer

Needs: Windows 10/11, macOS or Linux; **Python 3.10-3.13** (3.12 recommended;
on Windows tick "Add python.exe to PATH" when installing); **Node.js 20.9+**
(the LTS); internet on the first run (it downloads the packages, ~1 GB on
disk, and a 70 MB model on the first discovery); ports 3000 and 8000 free.
No GPU, Docker or Git needed.

Copy the folder **without** `backend/.venv`, `frontend/node_modules`,
`frontend/.next` and the root `node_modules` (they are built for the computer
that made them; `start.py` makes new ones -- and rebuilds them if they were
copied anyway). Leave out `backend/.env` and `backend/data/` too unless the
other person should have your accounts, papers and saved model keys: they are
your local secrets and database. Then, in the copied folder:

```bash
python start.py
```

In containers, production-like (PostgreSQL, the production images): copy
`.env.example` to `.env`, fill in the three secrets it asks for, then
`docker compose up --build`.

## Tests

```bash
cd backend && pytest -q && ruff check . && mypy app tests
cd frontend && npm test && npm run lint && npx tsc --noEmit
cd frontend && npx playwright test --project=chromium   # with both servers running
```

## Documents

| | |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | deploying to AWS, step by step |
| [AWS_ARCHITECTURE.md](AWS_ARCHITECTURE.md) | the AWS design, why, and its monthly cost |
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | every setting |
| [AUTHENTICATION.md](AUTHENTICATION.md) | sign-up, sign-in codes, sessions, email |
| [SECURITY.md](SECURITY.md) | protections, the audit, known limitations |
| [OPERATIONS_AND_ROLLBACK.md](OPERATIONS_AND_ROLLBACK.md) | logs, alarms, backups, rollbacks, troubleshooting |
| [DESIGN.md](DESIGN.md), [PRODUCT.md](PRODUCT.md) | the design system and the product |
| [backend/README.md](backend/README.md) | backend details: sources, database, maintenance |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | licenses of adapted code |
