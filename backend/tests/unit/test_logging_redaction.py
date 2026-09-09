from __future__ import annotations

import io

from app.telemetry.logging import configure_logging, get_logger


def test_api_key_field_never_appears_in_rendered_logs() -> None:
    buf = io.StringIO()
    configure_logging(stream=buf)
    logger = get_logger("test")
    logger.info("saved key", api_key="sk-super-secret-value", provider="groq")
    output = buf.getvalue()
    assert "sk-super-secret-value" not in output
    assert "[REDACTED]" in output
    assert "groq" in output  # non-secret fields still render


def test_bearer_token_inside_a_message_string_is_redacted() -> None:
    buf = io.StringIO()
    configure_logging(stream=buf)
    logger = get_logger("test")
    logger.info("request", headers="Authorization: Bearer abc123.def456.ghi789")
    output = buf.getvalue()
    assert "abc123.def456.ghi789" not in output
    assert "[REDACTED]" in output


def test_key_ciphertext_field_is_redacted() -> None:
    buf = io.StringIO()
    configure_logging(stream=buf)
    logger = get_logger("test")
    logger.info("stored", key_ciphertext=str(b"\x00\x01not-real-ciphertext"))
    output = buf.getvalue()
    assert "not-real-ciphertext" not in output
