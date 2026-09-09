"""Envelope encryption for BYOK provider keys (Roadmap Task 1 item 4).

A local KEK (`RESEARCHNEXUS_KEY_VAULT_SECRET`, a Fernet key) encrypts each
provider API key before it is stored; plaintext is never written to the DB
or logs (Architecture §7; Data Model §13: "plaintext never stored/logged").
The KEK itself must come from a real secret store in production -- only how
the KEK is obtained changes when that backend is swapped in later, not this
encrypt/decrypt interface.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as _FernetInvalidToken


class KeyVaultMisconfigured(RuntimeError):
    """Raised when no KEK is configured (RESEARCHNEXUS_KEY_VAULT_SECRET unset)."""


class KeyVaultDecryptionError(RuntimeError):
    """Raised when ciphertext cannot be decrypted with the configured KEK
    (wrong/rotated key, or corrupted data)."""


class KeyVault:
    def __init__(self, secret: str | None) -> None:
        if not secret:
            raise KeyVaultMisconfigured(
                "RESEARCHNEXUS_KEY_VAULT_SECRET is not set; generate one with "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`'
            )
        self._fernet = Fernet(secret.encode())

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except _FernetInvalidToken as e:
            raise KeyVaultDecryptionError("stored key could not be decrypted") from e


def last4(plaintext: str) -> str:
    return plaintext[-4:] if len(plaintext) >= 4 else plaintext
