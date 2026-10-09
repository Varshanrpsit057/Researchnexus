"""Password hashing and the password policy.

Hashes are Argon2id (argon2-cffi's defaults, RFC 9106's low-memory profile:
64 MiB, 3 passes, 4 lanes -- OWASP's first recommendation). A hash made with
older parameters is upgraded the next time its owner signs in.

The policy follows NIST SP 800-63B in spirit -- length over composition,
and no common or guessable passwords -- with one composition rule people
expect: a letter plus a digit or symbol.
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
# long enough for any passphrase, short enough that hashing it is cheap
MAX_LENGTH = 128

_hasher = PasswordHasher()

# A hash to verify against when the account doesn't exist (or has no
# password), so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("researchnexus-timing-equaliser")

# The most common passwords of at least MIN_LENGTH characters (from public
# breach-corpus rankings); anything here is refused outright.
_COMMON = frozenset(
    {
        "1234567890", "12345678910", "0123456789", "qwertyuiop", "1q2w3e4r5t", "password1",
        "password12", "password123", "password1234", "passw0rd123", "qwerty1234", "qwerty12345",
        "qwerty123456", "1qaz2wsx3edc", "iloveyou123", "abc1234567", "abcd123456", "welcome123",
        "letmein123", "admin12345", "administrator", "football123", "baseball123", "sunshine123",
        "princess123", "dragon1234", "monkey1234", "starwars123", "computer123", "internet123",
        "trustno1234", "superman123", "michael123", "jennifer123", "1234qwerty", "zaq12wsxcde",
        "asdfghjkl1", "zxcvbnm123", "qazwsxedc123", "researchnexus", "researchnexus1", "researchnexus123",
        "changeme123", "p@ssw0rd123", "p@ssword123", "passwordpassword", "aa12345678", "a1234567890",
    }
)


class PasswordPolicyError(ValueError):
    """The password breaks the policy; `message` says how, for the reader."""


def check_policy(password: str, *, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")
    if not password.strip():
        raise PasswordPolicyError("A password can't be only spaces.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[^A-Za-z]", password):
        raise PasswordPolicyError("Mix letters with at least one number or symbol.")
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) <= 3:
        raise PasswordPolicyError("That password is too common. Choose one that's harder to guess.")
    local = email.split("@", 1)[0].lower()
    if (len(local) >= 4 and local in lowered) or (email and lowered == email.lower()):
        raise PasswordPolicyError("Don't use your email address in your password.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Whether `password` matches. With no hash (no account, or one without
    a password yet) it still does a full verification, then says no."""
    if len(password) > MAX_LENGTH:
        password = password[:MAX_LENGTH]  # bound the work; the stored hash can't be of a longer one
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False
