"""What the server knows about the outside world (remediation, 2026-10-06):
the scholarly sources and how each is doing, and the publishers a reader
can prefer. Settings shows both."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AppSettings, CurrentUser
from app.services.metadata.publishers import TRUSTED_PUBLISHERS, known_publishers
from app.services.sources import check_sources, describe_sources

router = APIRouter(tags=["service"])


@router.get("/api/v1/service/sources")
def get_sources(settings: AppSettings, current_user: CurrentUser) -> dict[str, object]:
    """Each source, what it is used for and how it is set up -- never a key."""
    return describe_sources(settings)


@router.post("/api/v1/service/sources/check")
async def check_sources_now(settings: AppSettings, current_user: CurrentUser) -> dict[str, object]:
    """Ask every source one cheap question now (one request each)."""
    return {"results": await check_sources(settings)}


@router.get("/api/v1/publishers")
def get_publishers() -> dict[str, list[str]]:
    """The publishers a reader can prefer, named as readers know them, and the default ones."""
    return {"default": list(TRUSTED_PUBLISHERS), "known": known_publishers()}
