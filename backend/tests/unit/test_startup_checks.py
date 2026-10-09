"""Production configuration is checked at start (app/startup_checks.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.startup_checks import ConfigError, check, enforce

_SECRET_VALUES = ("s" * 40, "smtp-password-value", "postgres-password-value")


def _production(tmp_path: Path, **overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "environment": "production",
        "data_dir": tmp_path,
        "database_url": "postgresql+psycopg://rn:postgres-password-value@db.internal:5432/researchnexus",
        "secret_key": "s" * 40,
        "key_vault_secret": Fernet.generate_key().decode(),
        "public_app_url": "https://researchnexus.example.org",
        "cors_allowed_origins": ["https://researchnexus.example.org"],
        "smtp_host": "email-smtp.eu-west-1.amazonaws.com",
        "smtp_username": "AKIAEXAMPLE",
        "smtp_password": "smtp-password-value",
        "email_from": "ResearchNexus <no-reply@example.org>",
        "contact_email": "ops@example.org",
    }
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg, arg-type]


def test_a_complete_production_configuration_passes(tmp_path: Path) -> None:
    settings = _production(tmp_path)
    assert check(settings) == []
    assert settings.secure_cookies and settings.mail_backend == "smtp" and not settings.auto_create_schema


@pytest.fixture
def no_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("RESEARCHNEXUS_SECRET_KEY", "RESEARCHNEXUS_JWT_SECRET", "RESEARCHNEXUS_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)


def test_the_default_environment_is_production_and_fails_closed(tmp_path: Path, no_secret_env: None) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    assert settings.environment == "production"
    with pytest.raises(ConfigError) as raised:
        enforce(settings)
    message = str(raised.value)
    for variable in (
        "RESEARCHNEXUS_SECRET_KEY",
        "RESEARCHNEXUS_KEY_VAULT_SECRET",
        "RESEARCHNEXUS_DATABASE_URL",
        "RESEARCHNEXUS_SMTP_HOST",
        "RESEARCHNEXUS_EMAIL_FROM",
        "RESEARCHNEXUS_PUBLIC_APP_URL",
        "RESEARCHNEXUS_CORS_ALLOWED_ORIGINS",
    ):
        assert variable in message


@pytest.mark.parametrize(
    ("overrides", "variable"),
    [
        ({"secret_key": "tiny-secret"}, "RESEARCHNEXUS_SECRET_KEY"),
        ({"key_vault_secret": "not-a-fernet-key"}, "RESEARCHNEXUS_KEY_VAULT_SECRET"),
        ({"database_url": "sqlite:///./data/researchnexus.db"}, "RESEARCHNEXUS_DATABASE_URL"),
        ({"email_backend": "console"}, "RESEARCHNEXUS_EMAIL_BACKEND"),
        ({"email_backend": "memory"}, "RESEARCHNEXUS_EMAIL_BACKEND"),
        ({"public_app_url": "http://researchnexus.example.org"}, "RESEARCHNEXUS_PUBLIC_APP_URL"),
        ({"cookie_secure": False}, "RESEARCHNEXUS_COOKIE_SECURE"),
        ({"cors_allowed_origins": ["http://localhost:3000"]}, "RESEARCHNEXUS_CORS_ALLOWED_ORIGINS"),
    ],
)
def test_each_unsafe_production_setting_stops_the_start_and_is_named_without_its_value(
    tmp_path: Path, overrides: dict[str, object], variable: str
) -> None:
    with pytest.raises(ConfigError) as raised:
        enforce(_production(tmp_path, **overrides))
    message = str(raised.value)
    assert variable in message
    for value in (*_SECRET_VALUES, "not-a-fernet-key", "tiny-secret"):
        assert value not in message


def test_development_only_warns_and_has_its_local_conveniences(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, environment="development", secret_key="d" * 40)  # type: ignore[call-arg]
    findings = enforce(settings)  # no raise
    assert {f.variable for f in findings} == {"RESEARCHNEXUS_KEY_VAULT_SECRET"}
    assert not settings.secure_cookies and settings.mail_backend == "console" and settings.auto_create_schema


def test_development_still_needs_the_secret_behind_codes_and_csrf(tmp_path: Path, no_secret_env: None) -> None:
    with pytest.raises(ConfigError, match="RESEARCHNEXUS_SECRET_KEY"):
        enforce(Settings(_env_file=None, data_dir=tmp_path, environment="development"))  # type: ignore[call-arg]


def test_the_old_jwt_secret_variable_still_provides_the_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RESEARCHNEXUS_SECRET_KEY", raising=False)
    monkeypatch.setenv("RESEARCHNEXUS_JWT_SECRET", "j" * 40)
    assert Settings(_env_file=None, data_dir=tmp_path).secret_key == "j" * 40  # type: ignore[call-arg]


def test_production_without_a_contact_email_or_smtp_login_starts_with_a_warning(tmp_path: Path) -> None:
    findings = enforce(_production(tmp_path, contact_email=None, smtp_username=None, smtp_password=None))
    assert {f.variable for f in findings} == {"RESEARCHNEXUS_CONTACT_EMAIL", "RESEARCHNEXUS_SMTP_USERNAME"}
    assert not any(f.blocking for f in findings)


def test_a_database_given_in_parts_becomes_its_url_with_the_password_quoted(tmp_path: Path) -> None:
    settings = _production(tmp_path, database_url="sqlite:///ignored.db", db_host="rn.cluster.eu-west-1.rds.amazonaws.com", db_user="rn_app", db_password="p@ss/w:rd#1")
    assert settings.database_url == "postgresql+psycopg://rn_app:p%40ss%2Fw%3Ard%231@rn.cluster.eu-west-1.rds.amazonaws.com:5432/researchnexus"
    assert check(settings) == []
