"""Playwright test helper (Phase 10): run the REAL comparison pipeline
(app/services/synthesis/compare.py::build_comparison) over a workspace's
real papers, and store its result exactly as POST .../compare would.

Only the language model is scripted -- no BYOK key exists here. It answers
the way a model would: for each column it proposes a value with a quote
copied from the chunks it was shown, or null. The pipeline then does what
it always does: keeps a value only if its quote is verbatim in a chunk it
actually retrieved for that paper, records why every other cell is empty,
and persists the comparison and its claims. The script proposes one value
whose quote is nowhere in the paper, so the "unsupported" path is real too.

Usage: python seed-comparison.py <workspace_id>
Prints the stored comparison as JSON.
"""

import asyncio
import json
import os
import re
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
from app.domain.comparison import ComparisonSchema  # noqa: E402
from app.domain.user import LlmProvider  # noqa: E402
from app.llm.providers.openai_compat import OpenAiCompatClient  # noqa: E402
from app.llm.session import LlmSession  # noqa: E402
from app.retrieval.workspace_index import FaissWorkspaceIndex  # noqa: E402
from app.services.ingest.abstract_chunks import ensure_abstract_chunks  # noqa: E402
from app.services.synthesis.compare import build_comparison  # noqa: E402

COLUMNS = ["method", "dataset", "metric", "result"]
# (column, value, quote): proposed wherever the quote is in a chunk the model was shown
READINGS = [
    ("method", "Dense retrieval with reranking", "Dense + rerank LitSearch 58.6"),
    ("dataset", "LitSearch", "BM25 LitSearch 42.1"),
    ("metric", "F1", "Method Dataset F1"),
    ("result", "58.6 F1 with dense retrieval and reranking", "Dense + rerank LitSearch 58.6"),
    ("method", "Generators that read retrieved passages", "We revisit generators that read retrieved passages"),
    ("result", "Less hallucination, better factual grounding", "retrieval augmented generation reduces hallucination and improves factual grounding"),
    ("method", "Symbolic reasoning checked by a rule engine", "symbolic reasoning instead of retrieval"),
    ("result", "Every generated claim is verified", "A rule engine verifies each generated claim"),
    ("method", "Dense retrieval with a parametric generator", "We extend dense retrieval with a parametric generator"),
    ("result", "Better results on three benchmarks", "Results improve on three benchmarks"),
]


def reader(request: httpx.Request) -> httpx.Response:
    prompt = json.loads(request.content)["messages"][-1]["content"]
    # the pipeline lists each chunk as "[chunk_id] text", blank-line separated; text may span lines
    body = prompt.split("CHUNKS:\n", 1)[1]
    chunks = {
        m.group(1): m.group(2)
        for part in re.split(r"\n\n(?=\[[^\]]+\] )", body)
        if (m := re.match(r"\[([^\]]+)\] (.*)", part, flags=re.S))
    }
    cells: dict[str, dict] = {}
    for column, value, quote in READINGS:
        if column in cells:
            continue
        for chunk_id, text in chunks.items():
            if quote.lower() in " ".join(text.split()).lower():
                cells[column] = {"column": column, "value": value, "chunk_id": chunk_id, "quote": quote}
                break
    # a value the paper never states: the pipeline must refuse it
    if "dataset" not in cells and any("revisit generators" in t for t in chunks.values()):
        first = next(iter(chunks))
        cells["dataset"] = {"column": "dataset", "value": "Natural Questions", "chunk_id": first, "quote": "evaluated on Natural Questions"}
    answer = {"cells": [cells.get(c, {"column": c, "value": None, "chunk_id": None, "quote": None}) for c in COLUMNS]}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}})


workspace_id = sys.argv[1]
engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
db = sessionmaker(bind=engine)()
row = db.get(WorkspaceORM, workspace_id)
assert row is not None, workspace_id
workspace = repo.get_workspace(db, workspace_id, row.owner_id)
assert workspace is not None
settings = Settings()
members = [p.paper_id for p in workspace.papers]

ensure_abstract_chunks(db, members)
index = FaissWorkspaceIndex(
    db, workspace_id=workspace_id, index_dir=settings.data_dir / "workspace_index", vector_backend=settings.rag_vector_backend
)
index.rebuild(members)
session = LlmSession(
    client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(reader))),
    api_key="scripted",
    model="scripted",
    provider=LlmProvider.GROQ,
)
result = asyncio.run(
    build_comparison(
        db,
        workspace=workspace,
        comparison_id=f"cmp_pw_{os.getpid()}",
        paper_ids=members,
        column_schema=ComparisonSchema(columns=COLUMNS),
        session=session,
        settings=settings,
        index=index,
    )
)
repo.save_claims(db, result.claims)
stored = repo.save_comparison(db, result.comparison, owner_id=row.owner_id)
repo.set_workspace_comparison_schema(db, workspace_id, row.owner_id, result.comparison.column_schema)
print(json.dumps(stored.api_dict()))
