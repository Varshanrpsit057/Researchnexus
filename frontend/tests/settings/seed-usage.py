"""Playwright test helper (remediation Phase 5): give the test user a known
usage history in the real usage ledger.

Every call goes through the real metering path -- `MeteredClient` with the
server's `db_recorder`, inside the same `usage_scope` the app uses -- with a
scripted model in place of the provider, since tests never send a key to a
real provider. One call is then dated 45 days back, so the page's ranges
have something to tell apart.

Usage:
  python seed-usage.py seed <email>    # into the user's newest workspace
  python seed-usage.py clear <email>   # the user's whole usage history
Prints JSON: the workspace used ({"workspace_id", "title"}) or {}.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

BACKEND = r"H:\Researchnexus\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from sqlalchemy import create_engine, delete, update  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import repository as repo  # noqa: E402
from app.db.models import LlmCallORM, WorkspaceORM  # noqa: E402
from app.domain.user import LlmProvider  # noqa: E402
from app.llm.client import ChatMessage, ChatResult, LlmErrorKind, LlmProviderError  # noqa: E402
from app.llm.usage import MeteredClient, db_recorder, usage_scope  # noqa: E402

mode, email = sys.argv[1], sys.argv[2]
engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
db = sessionmaker(bind=engine)()
user = repo.get_user_by_email(db, email)
assert user is not None, f"sign in as {email} first"

if mode == "clear":
    db.execute(delete(LlmCallORM).where(LlmCallORM.owner_id == user.id))
    db.commit()
    print("{}")
    sys.exit(0)


class Scripted:
    """Answers like a provider would, with these token counts."""

    def __init__(self, model: str, prompt: int, completion: int, cached: int = 0, reasoning: int = 0, fail: bool = False) -> None:
        self.result = ChatResult(
            content="ok", latency_ms=5, prompt_tokens=prompt, completion_tokens=completion,
            cached_prompt_tokens=cached, reasoning_tokens=reasoning, model=model,
        )
        self.fail = fail

    async def chat(self, **kw: object) -> ChatResult:
        if self.fail:
            raise LlmProviderError("rate limited", kind=LlmErrorKind.RATE_LIMITED, provider="deepseek")
        return self.result


ws = db.query(WorkspaceORM).filter(WorkspaceORM.owner_id == user.id).order_by(WorkspaceORM.created_at.desc()).first()
wid = ws.id if ws else None
record = db_recorder(engine)
PING = [ChatMessage(role="user", content="q")]


async def call(feature: str, provider: LlmProvider, model: Scripted, workspace_id: str | None) -> None:
    client = MeteredClient(model, owner_id=user.id, provider=provider, recorder=record)  # type: ignore[arg-type]
    with usage_scope(feature, workspace_id=workspace_id):
        try:
            await client.chat(api_key="sk-test-not-sent", model=model.result.model or "m", messages=PING)
        except LlmProviderError:
            pass


async def main() -> None:
    flash = "deepseek-flash"
    await call("chat", LlmProvider.DEEPSEEK, Scripted(flash, 1200, 300, cached=400), wid)
    await call("chat", LlmProvider.DEEPSEEK, Scripted(flash, 1200, 300, cached=400), wid)
    await call("chat", LlmProvider.DEEPSEEK, Scripted(flash, 0, 0, fail=True), wid)
    await call("gaps", LlmProvider.DEEPSEEK, Scripted(flash, 5000, 800, reasoning=200), wid)
    await call("profile", LlmProvider.GEMINI, Scripted("gemini-2.5-flash", 2000, 500), None)
    await call("chat", LlmProvider.DEEPSEEK, Scripted(flash, 10_000, 1000), wid)  # dated back below


asyncio.run(main())
newest = db.query(LlmCallORM).filter(LlmCallORM.owner_id == user.id).order_by(LlmCallORM.created_at.desc()).first()
assert newest is not None and newest.prompt_tokens == 10_000
db.execute(update(LlmCallORM).where(LlmCallORM.id == newest.id).values(created_at=datetime.now(timezone.utc) - timedelta(days=45)))
db.commit()
print(json.dumps({"workspace_id": wid, "title": ws.title} if ws else {}))
