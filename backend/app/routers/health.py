from fastapi import APIRouter
from sqlalchemy import text

from app.deps import DbSession

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health")
def health(db: DbSession) -> dict[str, object]:
    # API spec §2: a status plus the checks behind it, so a client can tell what is down
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - reported, not raised: health must answer
        database = "error"
    return {"status": "ok" if database == "ok" else "degraded", "version": VERSION, "checks": {"db": database}}
