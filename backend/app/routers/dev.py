"""The development mailbox: the emails a development server "sent" (with the
console email backend they are printed, never delivered), so a person or
an end-to-end test can read a sign-in code without a real inbox.

Mounted only when RESEARCHNEXUS_ENVIRONMENT=development and the email
backend is "console" (app/main.py), and it answers only requests from this
machine. A staging or production server never has it: startup checks
refuse the console backend there.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.services import mail

router = APIRouter(prefix="/api/v1/dev", tags=["development"])

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


@router.get("/mailbox")
def mailbox(request: Request, email: str = Query(max_length=320)) -> dict[str, list[dict[str, str]]]:
    if not request.client or request.client.host not in _LOOPBACK:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Not Found"}})
    return {
        "messages": [
            {"subject": m.subject, "text": m.text, "purpose": m.purpose, "sent_at": m.sent_at.isoformat()}
            for m in mail.outbox.for_address(email)[:10]
        ]
    }
