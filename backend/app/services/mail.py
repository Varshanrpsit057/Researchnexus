"""Transactional email: sign-up and sign-in codes, password resets, and
security notices.

Backends (RESEARCHNEXUS_EMAIL_BACKEND):
- "smtp": any SMTP server over STARTTLS -- in production, Amazon SES's SMTP
  endpoint with SES SMTP credentials. Temporary failures (a dropped
  connection, a 4xx reply) are retried twice with a short backoff; a
  permanent one raises MailError at once.
- "console": prints each message, code included, to the server's own
  output. Development only: a staging or production server refuses to
  start with it (app/startup_checks.py). The last messages are also kept
  in memory for the development mailbox (app/routers/dev.py).
- "memory": keeps messages in a list. Tests only.

Nothing here logs a message's body: a failure is logged with the purpose,
the recipient's domain and the error class.
"""

from __future__ import annotations

import smtplib
import ssl
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from app.config import Settings
from app.telemetry.logging import get_logger

_log = get_logger(__name__)

APP_NAME = "ResearchNexus"


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str
    # what the message is for (logged on failure; never the body)
    purpose: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MailError(Exception):
    """The message could not be handed to the mail server."""


class _Outbox:
    """The last messages sent by the console and memory backends."""

    def __init__(self, size: int = 50) -> None:
        self._items: deque[Mail] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, mail: Mail) -> None:
        with self._lock:
            self._items.append(mail)

    def for_address(self, address: str) -> list[Mail]:
        with self._lock:
            return [m for m in reversed(self._items) if m.to.lower() == address.strip().lower()]

    def all(self) -> list[Mail]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


outbox = _Outbox()


def _domain(address: str) -> str:
    return address.rpartition("@")[2].lower() or "?"


def send(settings: Settings, mail: Mail) -> None:
    backend = settings.mail_backend
    if backend == "memory":
        outbox.add(mail)
        return
    if backend == "console":
        if not settings.is_local:  # belt and braces: startup checks refuse this already
            raise MailError("the console email backend is for development only")
        outbox.add(mail)
        print(  # noqa: T201 - this IS the development mailbox
            f"\n----- development email (not sent) -----\nTo: {mail.to}\nSubject: {mail.subject}\n\n{mail.text}\n"
            "----------------------------------------\n",
            file=sys.stderr,
            flush=True,
        )
        return
    _send_smtp(settings, mail)


def _send_smtp(settings: Settings, mail: Mail) -> None:
    if not settings.smtp_host or not settings.email_from:
        raise MailError("email is not set up (RESEARCHNEXUS_SMTP_HOST / RESEARCHNEXUS_EMAIL_FROM)")
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = mail.to
    message["Subject"] = mail.subject
    message["Message-ID"] = make_msgid(domain=_domain(parseaddr(settings.email_from)[1]) or None)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")

    delays = (1.0, 3.0)
    for attempt in range(len(delays) + 1):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_s) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return
        except smtplib.SMTPResponseException as e:
            temporary = 400 <= e.smtp_code < 500
            _log.warning("email_send_failed", purpose=mail.purpose, to_domain=_domain(mail.to), smtp_code=e.smtp_code, attempt=attempt + 1, temporary=temporary)
            if not temporary or attempt == len(delays):
                raise MailError(f"the mail server refused the message ({e.smtp_code})") from e
        except (smtplib.SMTPException, OSError) as e:
            _log.warning("email_send_failed", purpose=mail.purpose, to_domain=_domain(mail.to), error=type(e).__name__, attempt=attempt + 1, temporary=True)
            if attempt == len(delays):
                raise MailError("the mail server could not be reached") from e
        time.sleep(delays[attempt])


# --- messages --------------------------------------------------------------

_INTRO = {
    "signup": ("Confirm your email", "Enter this code to finish creating your ResearchNexus account."),
    "login": ("Your sign-in code", "Enter this code to finish signing in to ResearchNexus."),
    "reset": ("Reset your password", "Enter this code to choose a new password for your ResearchNexus account."),
}


def _html(heading: str, lines: list[str], code: str | None = None) -> str:
    from html import escape

    body = "".join(f'<p style="margin:0 0 14px;color:#33415c;font-size:15px;line-height:1.55">{escape(line)}</p>' for line in lines)
    code_block = (
        f'<p style="margin:6px 0 20px;font:700 30px/1.2 \'Courier New\',monospace;letter-spacing:8px;color:#04060f">{escape(code)}</p>'
        if code
        else ""
    )
    return (
        '<!doctype html><html><body style="margin:0;background:#f4f6fb;padding:28px 16px;font-family:Arial,Helvetica,sans-serif">'
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:14px;padding:28px 28px 18px;border:1px solid #e3e8f2">'
        f'<p style="margin:0 0 18px;font-weight:700;color:#04060f;font-size:15px">{APP_NAME}</p>'
        f'<h1 style="margin:0 0 14px;font-size:20px;color:#04060f">{escape(heading)}</h1>'
        f"{code_block}{body}</div></body></html>"
    )


def code_mail(purpose: str, to: str, code: str, *, ttl_s: int, name: str | None = None) -> Mail:
    subject, intro = _INTRO[purpose]
    minutes = max(1, round(ttl_s / 60))
    greeting = f"Hi {name.strip()}," if name and name.strip() else "Hello,"
    lines = [
        greeting,
        intro,
        f"It works once and expires in {minutes} minutes.",
        "If you didn't ask for this, you can ignore this email -- nothing changes without the code. "
        "Never share it: ResearchNexus will never ask you for it.",
    ]
    text = "\n\n".join([lines[0], lines[1], f"    {code}", *lines[2:], f"-- {APP_NAME}"])
    return Mail(to=to, subject=f"{subject} - {APP_NAME}", text=text, html=_html(subject, [lines[1], *lines[2:]], code), purpose=purpose)


def account_exists_mail(to: str, app_url: str) -> Mail:
    """Sent instead of a code when someone signs up with an email that
    already has an account: the owner learns of it, the stranger learns
    nothing."""
    lines = [
        "Someone (maybe you) tried to create a ResearchNexus account with this email, but it already has one.",
        f"To get in, sign in at {app_url}/sign-in -- or choose \"Forgot password\" there if you don't remember it "
        "(that's also how an account made before passwords existed gets one).",
        "If this wasn't you, you can ignore this email: your account hasn't changed.",
    ]
    return Mail(
        to=to,
        subject=f"You already have an account - {APP_NAME}",
        text="\n\n".join([*lines, f"-- {APP_NAME}"]),
        html=_html("You already have an account", lines),
        purpose="signup-existing",
    )


def password_changed_mail(to: str, app_url: str) -> Mail:
    lines = [
        "The password for your ResearchNexus account was just changed, and every other signed-in device was signed out.",
        f"If this wasn't you, reset your password now at {app_url}/forgot-password.",
    ]
    return Mail(
        to=to,
        subject=f"Your password was changed - {APP_NAME}",
        text="\n\n".join([*lines, f"-- {APP_NAME}"]),
        html=_html("Your password was changed", lines),
        purpose="password-changed",
    )
