from __future__ import annotations

import time

import pytest
from jose import jwt as jose_jwt

from app.config import Settings
from app.security.jwt import (
    InvalidToken,
    JwtMisconfigured,
    create_access_token,
    decode_access_token,
)


def _settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {"jwt_secret": "test-secret-value"}
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg, arg-type]


def test_round_trip_accepts_a_valid_token() -> None:
    settings = _settings()
    token = create_access_token(user_id="usr_1", email="a@example.com", settings=settings)
    payload = decode_access_token(token, settings)
    assert payload.sub == "usr_1"
    assert payload.email == "a@example.com"


def test_rejects_token_with_wrong_signature() -> None:
    settings = _settings()
    token = create_access_token(user_id="usr_1", email="a@example.com", settings=settings)
    other_settings = _settings(jwt_secret="a-different-secret-value")
    with pytest.raises(InvalidToken):
        decode_access_token(token, other_settings)


def test_rejects_expired_token() -> None:
    settings = _settings(jwt_expires_minutes=0)
    token = create_access_token(user_id="usr_1", email="a@example.com", settings=settings)
    time.sleep(1.1)
    with pytest.raises(InvalidToken):
        decode_access_token(token, settings)


def test_rejects_token_missing_required_claims() -> None:
    settings = _settings()
    bare_token = jose_jwt.encode({"foo": "bar"}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(InvalidToken):
        decode_access_token(bare_token, settings)


def test_missing_secret_raises_clear_error_on_create() -> None:
    settings = _settings(jwt_secret=None)
    with pytest.raises(JwtMisconfigured):
        create_access_token(user_id="usr_1", email="a@example.com", settings=settings)


def test_missing_secret_raises_clear_error_on_decode() -> None:
    settings = _settings(jwt_secret=None)
    with pytest.raises(JwtMisconfigured):
        decode_access_token("whatever", settings)
