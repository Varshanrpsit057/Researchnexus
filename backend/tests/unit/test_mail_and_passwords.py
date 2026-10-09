"""Email delivery (app/services/mail.py) and passwords (app/security/passwords.py)."""

from __future__ import annotations

import smtplib
from pathlib import Path

import pytest

from app.config import Settings
from app.security.passwords import PasswordPolicyError, check_policy, hash_password, verify_password
from app.services import mail


def _smtp_settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        data_dir=tmp_path,
        environment="production",
        smtp_host="email-smtp.eu-west-1.amazonaws.com",
        smtp_username="user",
        smtp_password="pass",
        email_from="ResearchNexus <no-reply@example.org>",
    )


class _FakeSMTP:
    """Records what an SMTP session did; fails as told."""

    sessions: list[_FakeSMTP] = []
    failures: list[Exception] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[object] = []
        _FakeSMTP.sessions.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")

    def send_message(self, message: object) -> None:
        if _FakeSMTP.failures:
            raise _FakeSMTP.failures.pop(0)
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    _FakeSMTP.sessions, _FakeSMTP.failures = [], []
    monkeypatch.setattr(mail.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mail.time, "sleep", lambda _s: None)
    return _FakeSMTP


def test_a_code_email_goes_out_over_starttls_with_login_and_both_text_and_html(tmp_path: Path, fake_smtp: type[_FakeSMTP]) -> None:
    mail.send(_smtp_settings(tmp_path), mail.code_mail("login", "ada@example.org", "482913", ttl_s=300, name="Ada"))
    (session,) = fake_smtp.sessions
    assert session.host == "email-smtp.eu-west-1.amazonaws.com" and session.port == 587
    assert session.calls == ["starttls", "login"]
    (message,) = session.sent
    assert message["To"] == "ada@example.org" and message["From"] == "ResearchNexus <no-reply@example.org>"  # type: ignore[index]
    assert "482913" not in message["Subject"]  # type: ignore[index]  # the code is in the body only
    kinds = [part.get_content_type() for part in message.iter_parts()]  # type: ignore[attr-defined]
    assert kinds == ["text/plain", "text/html"]
    assert "482913" in message.get_body(("plain",)).get_content() and "expires in 5 minutes" in message.get_body(("plain",)).get_content()  # type: ignore[attr-defined]


def test_a_temporary_failure_is_retried_and_a_permanent_one_is_not(tmp_path: Path, fake_smtp: type[_FakeSMTP]) -> None:
    settings = _smtp_settings(tmp_path)
    message = mail.code_mail("signup", "ada@example.org", "123456", ttl_s=300)
    fake_smtp.failures = [smtplib.SMTPServerDisconnected("dropped"), smtplib.SMTPResponseException(421, b"try later")]
    mail.send(settings, message)
    assert len(fake_smtp.sessions) == 3 and fake_smtp.sessions[-1].sent

    fake_smtp.sessions.clear()
    fake_smtp.failures = [smtplib.SMTPResponseException(554, b"Message rejected: Email address is not verified.")]
    with pytest.raises(mail.MailError, match="554"):
        mail.send(settings, message)
    assert len(fake_smtp.sessions) == 1

    fake_smtp.sessions.clear()
    fake_smtp.failures = [OSError("unreachable")] * 3
    with pytest.raises(mail.MailError, match="could not be reached"):
        mail.send(settings, message)
    assert len(fake_smtp.sessions) == 3


def test_the_console_mailer_works_only_in_development(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dev = Settings(_env_file=None, data_dir=tmp_path, environment="development")  # type: ignore[call-arg]
    mail.send(dev, mail.code_mail("login", "ada@example.org", "654321", ttl_s=300))
    assert "654321" in capsys.readouterr().err
    assert mail.outbox.for_address("ADA@example.org")[0].purpose == "login"
    production = Settings(_env_file=None, data_dir=tmp_path, environment="production", email_backend="console")  # type: ignore[call-arg]
    with pytest.raises(mail.MailError):
        mail.send(production, mail.code_mail("login", "ada@example.org", "111111", ttl_s=300))
    assert "111111" not in capsys.readouterr().err


def test_smtp_without_a_server_says_so(tmp_path: Path) -> None:
    unset = Settings(_env_file=None, data_dir=tmp_path, environment="production")  # type: ignore[call-arg]
    with pytest.raises(mail.MailError, match="not set up"):
        mail.send(unset, mail.code_mail("login", "ada@example.org", "123456", ttl_s=300))


def test_passwords_are_argon2id_and_verify_only_themselves() -> None:
    stored = hash_password("Tidal-pools-9")
    assert stored.startswith("$argon2id$") and "Tidal-pools-9" not in stored
    assert verify_password(stored, "Tidal-pools-9")
    assert not verify_password(stored, "tidal-pools-9")
    assert not verify_password(None, "Tidal-pools-9")  # no account: still a full check, still no
    assert not verify_password("not-a-hash", "Tidal-pools-9")
    assert not verify_password(stored, "x" * 5000)


@pytest.mark.parametrize("password", ["Tidal-pools-9", "correct horse battery staple 7", "ünïcödé-pässwörd-1"])
def test_good_passwords_pass_the_policy(password: str) -> None:
    check_policy(password, email="ada@example.org")


@pytest.mark.parametrize("password", ["short-1", "a" * 129 + "1", "          ", "aaaaaaaaaa1", "Password123", "ada-lovelace-1"])
def test_weak_passwords_are_refused(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        check_policy(password, email="ada-lovelace@example.org")
