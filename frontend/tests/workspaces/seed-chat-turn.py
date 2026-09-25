"""Playwright test helper (Phase 9): persist one real chat turn -- a
question and its answer -- exactly as app/routers/chat.py would after the
RAG pipeline answered it. An answered turn's claims cite REAL chunks of the
workspace's seed paper (its own parsed text).

Generation is LLM-gated and no BYOK key exists in this environment, so the
spec mocks only the chat POST's stream, pointing it at the turn stored
here. Everything the page then reads back -- the conversation list, the
reloaded thread, each claim's sources (paper, section, page, quote) --
comes from the real backend resolving these real rows.

Usage:
  python seed-chat-turn.py answer <workspace_id> <tag>
  python seed-chat-turn.py unanswerable <workspace_id> <tag>
Prints JSON describing the stored turn.
"""

import json
import re
import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.db.models import WorkspaceORM
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.citation import ArtefactKind, Claim

mode, workspace_id, tag = sys.argv[1], sys.argv[2], sys.argv[3]
engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
db = sessionmaker(bind=engine)()
ws = db.get(WorkspaceORM, workspace_id)
assert ws is not None, workspace_id

session_id = f"cs_pw_{tag}"
question = (
    "What learning rate did pretraining use?"
    if mode == "unanswerable"
    else "What does the seed paper propose, and what does it show?"
)
repo.create_chat_session(
    db, ChatSession(session_id=session_id, workspace_id=workspace_id, owner_id=ws.owner_id, title=question[:80])
)
repo.add_chat_message(
    db, ChatMessage(message_id=f"cm_pw_q_{tag}", session_id=session_id, role=ChatRole.USER, content=question)
)

if mode == "unanswerable":
    suggestion = "The workspace papers don't report training hyperparameters; add a paper that describes its training setup."
    repo.add_chat_message(
        db,
        ChatMessage(
            message_id=f"cm_pw_a_{tag}", session_id=session_id, role=ChatRole.ASSISTANT, content="",
            answerable=False, suggestion=suggestion, warnings=["not_answerable"],
        ),
    )
    print(json.dumps({"session_id": session_id, "question": question, "suggestion": suggestion}))
    sys.exit(0)

# two real sentences from the seed paper's own parsed text
picked = []
for chunk in repo.get_chunks_for_paper(db, ws.seed_paper_id):
    m = re.search(r"[A-Z][^.]{40,200}\.", chunk.text)
    if m:
        picked.append((chunk, m.group(0).strip()))
    if len(picked) == 2:
        break
assert len(picked) == 2, "the seed paper has too few parsed chunks"

message_id = f"cm_pw_a_{tag}"
claims = [
    Claim(
        claim_id=f"clm_{message_id}_{i}",
        workspace_id=workspace_id,
        artefact_kind=ArtefactKind.ANSWER.value,
        artefact_id=message_id,
        sentence=sentence,
        supporting_chunk_ids=[chunk.chunk_id],
        supporting_paper_ids=[chunk.paper_id],
        is_supported=True,
    )
    for i, (chunk, sentence) in enumerate(picked)
]
repo.save_claims(db, claims)
repo.add_chat_message(
    db,
    ChatMessage(
        message_id=message_id,
        session_id=session_id,
        role=ChatRole.ASSISTANT,
        content=" ".join(c.sentence for c in claims),
        citations=[c.claim_id for c in claims],
        faithfulness=0.93,
        answerable=True,
        unsupported_dropped=1,
    ),
)

print(
    json.dumps(
        {
            "session_id": session_id,
            "message_id": message_id,
            "question": question,
            "seed_paper_id": ws.seed_paper_id,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "sentence": c.sentence,
                    "chunk_id": chunk.chunk_id,
                    "paper_id": chunk.paper_id,
                    "section": chunk.section,
                    "page": chunk.page,
                    "quote": chunk.text.strip()[:700],
                }
                for c, (chunk, _) in zip(claims, picked)
            ],
        }
    )
)
