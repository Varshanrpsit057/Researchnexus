"""Configuration checks run when the server starts.

A staging or production server refuses to start while anything it needs to
be safe or to work is missing or set for local use only; a development
server logs the same findings as warnings. Findings name the setting (its
environment variable) and what is wrong -- never its value.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from app.config import Settings


@dataclass(frozen=True)
class Finding:
    variable: str
    problem: str
    # fatal outside development/test
    blocking: bool = True


class ConfigError(RuntimeError):
    def __init__(self, findings: list[Finding]) -> None:
        lines = "\n".join(f"  - {f.variable}: {f.problem}" for f in findings)
        super().__init__(f"ResearchNexus can't start with this configuration:\n{lines}")
        self.findings = findings


def _env(name: str) -> str:
    return f"RESEARCHNEXUS_{name.upper()}"


def _is_https_origin(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.netloc) and parts.hostname not in ("localhost", "127.0.0.1")


def check(settings: Settings) -> list[Finding]:
    found: list[Finding] = []
    if not settings.secret_key:
        found.append(Finding(_env("secret_key"), "not set (a random value of at least 32 characters)"))
    elif len(settings.secret_key) < 32:
        found.append(Finding(_env("secret_key"), "too short: use at least 32 random characters"))
    if not settings.key_vault_secret:
        found.append(Finding(_env("key_vault_secret"), "not set (a Fernet key; saved LLM keys are encrypted with it)"))
    else:
        try:
            Fernet(settings.key_vault_secret.encode())
        except (ValueError, TypeError):
            found.append(Finding(_env("key_vault_secret"), "not a valid Fernet key (32 url-safe base64-encoded bytes)"))

    if settings.is_local:
        if settings.mail_backend == "smtp" and not (settings.smtp_host and settings.email_from):
            found.append(Finding(_env("smtp_host"), "the smtp email backend needs SMTP_HOST and EMAIL_FROM", blocking=False))
        return found

    # staging / production
    if settings.database_url.startswith("sqlite"):
        found.append(Finding(_env("database_url"), "SQLite is for development; use PostgreSQL (postgresql+psycopg://...)"))
    if settings.mail_backend != "smtp":
        found.append(Finding(_env("email_backend"), f"'{settings.mail_backend}' is for development and tests; use smtp"))
    else:
        if not settings.smtp_host:
            found.append(Finding(_env("smtp_host"), "not set (e.g. email-smtp.<region>.amazonaws.com)"))
        if not settings.email_from:
            found.append(Finding(_env("email_from"), "not set (a verified sender, e.g. ResearchNexus <no-reply@your-domain>)"))
        if settings.smtp_host and not (settings.smtp_username and settings.smtp_password):
            found.append(Finding(_env("smtp_username"), "SMTP credentials not set (SMTP_USERNAME and SMTP_PASSWORD)", blocking=False))
    if not _is_https_origin(settings.public_app_url):
        found.append(Finding(_env("public_app_url"), "must be the app's public https:// address"))
    if not settings.secure_cookies:
        found.append(Finding(_env("cookie_secure"), "cookies must be Secure outside development"))
    for origin in settings.cors_allowed_origins:
        if not _is_https_origin(origin):
            found.append(Finding(_env("cors_allowed_origins"), "every allowed origin must be an https:// address (no localhost)"))
            break
    if settings.auth_rate_limit_scale != 1.0:
        found.append(Finding(_env("auth_rate_limit_scale"), "development only: sign-in rate limits can't be scaled here"))
    if settings.auto_create_schema:
        found.append(Finding(_env("db_auto_create"), "on: deployed schemas change only through `alembic upgrade head`", blocking=False))
    if not settings.contact_email:
        found.append(
            Finding(_env("contact_email"), "not set: OpenAlex/Crossref run slower anonymously and Unpaywall is skipped", blocking=False)
        )
    return found


def enforce(settings: Settings) -> list[Finding]:
    """Raise ConfigError on blocking findings outside development/test;
    return the findings to log."""
    findings = check(settings)
    blocking = [f for f in findings if f.blocking]
    if blocking and not settings.is_local:
        raise ConfigError(blocking)
    if blocking and settings.environment == "development" and not settings.secret_key:
        raise ConfigError([f for f in blocking if f.variable == _env("secret_key")])
    return findings
