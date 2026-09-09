from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.security.key_vault import KeyVault, KeyVaultDecryptionError, KeyVaultMisconfigured, last4


def _secret() -> str:
    return Fernet.generate_key().decode()


def test_round_trips_plaintext() -> None:
    vault = KeyVault(_secret())
    ciphertext = vault.encrypt("sk-my-real-key-value")
    assert vault.decrypt(ciphertext) == "sk-my-real-key-value"


def test_ciphertext_never_contains_the_plaintext() -> None:
    vault = KeyVault(_secret())
    ciphertext = vault.encrypt("sk-my-real-key-value")
    assert b"sk-my-real-key-value" not in ciphertext


def test_wrong_key_cannot_decrypt() -> None:
    vault = KeyVault(_secret())
    ciphertext = vault.encrypt("sk-my-real-key-value")
    other_vault = KeyVault(_secret())
    with pytest.raises(KeyVaultDecryptionError):
        other_vault.decrypt(ciphertext)


def test_missing_secret_raises_clear_error() -> None:
    with pytest.raises(KeyVaultMisconfigured):
        KeyVault(None)


def test_last4() -> None:
    assert last4("sk-abcd1234") == "1234"
    assert last4("ab") == "ab"
