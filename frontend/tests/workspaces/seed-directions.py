"""Playwright test helper (Phase 12): run the REAL direction pipeline
(app/services/directions/pipeline.py::build_directions) over a workspace's
accepted gaps, exactly as POST .../directions does, and print its response.

Only the language model is scripted -- no BYOK key exists here. Every
answer still passes through the pipeline's own checks:
- proposals: for each gap the model sends two. The first restates the gap's
  own suggested direction with a method the gap itself names, so the
  pipeline classes it an evidence-backed inference. The second is, for a
  gap naming a method, a hypothesis pairing it with a new method (a
  direction may propose one); for any other gap it names something the
  gap's evidence doesn't contain, which the grounding check must drop.
- critique: fixed scores per kind, as a model would give them; the
  pipeline caps feasibility and derives the confidence band itself.

Usage: python seed-directions.py <workspace_id> <gap_id> [<gap_id> ...]
Prints the POST .../directions response as JSON.
Set RN_DB to run against another SQLite file (a dry run on a copy).
"""

import ast
import asyncio
import json
import os
import re
import sys

BACKEND = r"H:\Researchnexus\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import httpx  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import repository as repo  # noqa: E402
from app.db.models import WorkspaceORM  # noqa: E402
from app.domain.user import LlmProvider  # noqa: E402
from app.llm.providers.openai_compat import OpenAiCompatClient  # noqa: E402
from app.llm.session import LlmSession  # noqa: E402
from app.services.directions.pipeline import build_directions  # noqa: E402

DB = os.environ.get("RN_DB", r"H:/Researchnexus/backend/data/researchnexus.db")


def _reply(payload: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    )


def _line(user: str, key: str) -> str:
    m = re.search(rf"^{key}: (.*)$", user, flags=re.M)
    return m.group(1).strip() if m else ""


def reader(request: httpx.Request) -> httpx.Response:
    messages = json.loads(request.content)["messages"]
    system, user = messages[0]["content"], messages[-1]["content"]
    if "next-step research directions" in system:
        why = _line(user, "WHY_UNADDRESSED")
        methods = ast.literal_eval(_line(user, "AFFECTED_METHODS") or "[]")
        gap_id = next(g for g in GAPS if GAPS[g].statement == _line(user, "GAP"))
        suggested = GAPS[gap_id].proposed_direction.rstrip(".")
        method = methods[0] if methods else ("a shared metric" if "shared metric" in suggested else "")
        grounded = {
            "proposal": f"{suggested}, and compare against the papers' own reported results.",
            "motivation": why,
            "suggested_method": method,
            "possible_dataset": None,
            "evaluation_strategy": "Run it in the setting the papers share and compare against the results they report.",
            "risks": ["The papers may frame the shared problem differently."],
        }
        second = (
            {
                "proposal": f"Pair {methods[0]} with claim-level verification on the problem the papers share.",
                "motivation": why,
                "suggested_method": "claim-level verification",
                "possible_dataset": None,
                "evaluation_strategy": "Measure how often each generated claim is confirmed by a retrieved passage.",
                "risks": ["Verifying every claim adds latency.", "The verifier can share the generator's blind spots."],
            }
            if methods
            else {
                "proposal": "Train a reinforcement learning agent to rewrite each paper's reported numbers.",
                "motivation": "Reinforcement learning already solves metric mismatch reliably.",
                "suggested_method": "policy optimisation",
                "possible_dataset": None,
                "evaluation_strategy": "Evaluate.",
                "risks": [],
            }
        )
        return _reply({"directions": [grounded, second]})
    if "Rate the DIRECTION" in system:
        if "kind: llm_hypothesis" in user:
            return _reply({"novelty": 4, "specificity": 3, "feasibility": 2, "groundedness": 3})
        return _reply({"novelty": 2, "specificity": 4, "feasibility": 3, "groundedness": 5})
    return _reply({})


workspace_id, gap_ids = sys.argv[1], sys.argv[2:]
engine = create_engine(f"sqlite:///{DB}")
db = sessionmaker(bind=engine)()
row = db.get(WorkspaceORM, workspace_id)
assert row is not None, workspace_id
workspace = repo.get_workspace(db, workspace_id, row.owner_id)
assert workspace is not None
GAPS = {g.gap_id: g for g in repo.get_gaps(db, workspace_id)}
session = LlmSession(
    client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(reader))),
    api_key="scripted",
    model="scripted",
    provider=LlmProvider.GROQ,
)
result = asyncio.run(build_directions(db, workspace=workspace, gap_ids=gap_ids, session=session, settings=Settings()))
print(
    json.dumps(
        {
            "directions": [d.model_dump(mode="json") for d in repo.get_directions(db, workspace_id)],
            "requested": result.requested,
            "generated": result.direction_count,
            "skipped_not_accepted": result.skipped_not_accepted,
            "skipped_not_found": result.skipped_not_found,
            "dropped_unsupported": result.dropped_unsupported,
        }
    )
)
