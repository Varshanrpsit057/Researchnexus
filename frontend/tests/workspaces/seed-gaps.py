"""Playwright test helper (Phase 11): run the REAL gap pipeline
(app/services/gaps/pipeline.py::build_gaps) over a workspace's real papers,
exactly as POST .../gaps does in its background job.

Only the language model is scripted -- no BYOK key exists here -- and every
answer it gives is checked by the pipeline as usual:
- profiles: the seed is re-analysed from its parsed full text (it only had
  the fixture profile workspace creation needed), and the discovered papers
  are profiled lazily from their abstracts by the run itself. The scripted
  reader proposes a value only where its quote is verbatim in the excerpt
  it was sent; provenance_check turns each quote into a real span.
- the deterministic rules then find the candidates from those profiles;
- articulation: the reader returns nothing, so each gap is phrased by the
  pipeline's own template from the rule's facts (no invented prose);
- self-support: the scripted verifier confirms each statement except the one
  naming BM25 -- the seed's own baseline row, which a careful reader would
  not call a gap -- so the "dropped" path is real too.

Usage: python seed-gaps.py <workspace_id>
Prints {"progress": <the job progress a real run records>, "gaps": [...]}.
Set RN_DB to run against another SQLite file (a dry run on a copy).
"""

import asyncio
import json
import os
import sys

BACKEND = r"H:\Researchnexus\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)  # the workspace index lives under data/

import httpx  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import repository as repo  # noqa: E402
from app.db.models import WorkspaceORM  # noqa: E402
from app.domain.user import LlmProvider  # noqa: E402
from app.llm.providers.openai_compat import OpenAiCompatClient  # noqa: E402
from app.llm.session import LlmSession  # noqa: E402
from app.services.gaps.pipeline import GapBuildOptions, build_gaps  # noqa: E402
from app.services.profile.pipeline import profile_with_session  # noqa: E402

DB = os.environ.get("RN_DB", r"H:/Researchnexus/backend/data/researchnexus.db")

# (profile field, value, quote): proposed wherever the quote is verbatim in the excerpt
READINGS = [
    ("research_problem", "hallucination in knowledge intensive tasks", "hallucination in knowledge intensive tasks"),
    ("research_problem", "reducing hallucination and improving factual grounding", "reduces hallucination and improves factual grounding"),
    ("research_problem", "factual grounding for knowledge intensive tasks", "factual grounding for knowledge intensive tasks"),
    ("research_problem", "multi-hop question answering", "multi-hop questions"),
    ("subdomains", "knowledge intensive tasks", "knowledge intensive tasks"),
    ("methods", "dense retrieval with reranking", "Dense + rerank"),
    ("methods", "BM25", "BM25"),
    ("methods", "generators that read retrieved passages", "generators that read retrieved passages"),
    ("methods", "symbolic reasoning", "symbolic reasoning"),
    ("methods", "rule-engine verification of generated claims", "A rule engine verifies each generated claim"),
    ("methods", "dense retrieval with a parametric generator", "dense retrieval with a parametric generator"),
    ("datasets", "LitSearch", "LitSearch"),
    ("evaluation_metrics", "F1", "F1"),
    ("evaluation_metrics", "factual grounding", "improves factual grounding"),
    ("limitations", "no out-of-domain evaluation", "does not evaluate on out-of-domain benchmarks"),
    ("findings", "Retrieval augmented generation reduces hallucination", "retrieval augmented generation reduces hallucination"),
    ("findings", "Results improve on three benchmarks", "Results improve on three benchmarks"),
]
LISTS = ("subdomains", "methods", "datasets", "evaluation_metrics", "limitations", "findings")


def _reply(payload: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    )


def reader(request: httpx.Request) -> httpx.Response:
    messages = json.loads(request.content)["messages"]
    system, user = messages[0]["content"], messages[-1]["content"]
    if "scientific paper analysis assistant" in system:
        excerpt = user.split("Paper excerpts:\n\n", 1)[-1]
        found = [(f, v, q) for f, v, q in READINGS if q in excerpt]
        problem = next(({"value": v, "quote": q} for f, v, q in found if f == "research_problem"), {"value": "", "quote": None})
        out: dict = {"domain": {"value": "", "quote": None}, "research_problem": problem}
        for field in LISTS:
            out[field] = {"items": [{"value": v, "quote": q} for f, v, q in found if f == field]}
        return _reply(out)
    if "phrase a research gap" in system:
        return _reply({})  # nothing: the pipeline phrases it from the rule's facts
    if "fully supports the statement" in system:
        return _reply({"results": [{"index": 0, "supported": "BM25" not in user.split("EVIDENCE:", 1)[0]}]})
    return _reply({})


workspace_id = sys.argv[1]
engine = create_engine(f"sqlite:///{DB}")
db = sessionmaker(bind=engine)()
row = db.get(WorkspaceORM, workspace_id)
assert row is not None, workspace_id
workspace = repo.get_workspace(db, workspace_id, row.owner_id)
assert workspace is not None
settings = Settings()
session = LlmSession(
    client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(reader))),
    api_key="scripted",
    model="scripted",
    provider=LlmProvider.GROQ,
)

seed = repo.get_paper(db, workspace.seed_paper_id)
assert seed is not None and asyncio.run(profile_with_session(db, seed, session, settings)) is not None
result = asyncio.run(build_gaps(db, workspace=workspace, options=GapBuildOptions(), session=session, settings=settings))
# exactly what the real job records when it finishes (GapBuildResult.summary)
print(json.dumps({"progress": result.summary(), "gaps": [g.model_dump(mode="json") for g in repo.get_gaps(db, workspace_id)]}))
