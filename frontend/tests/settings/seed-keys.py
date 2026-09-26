"""Playwright test helper (Phase 14): store LLM keys for the test user
through the real repository, encrypted with the server's own key-vault
secret (backend/.env), exactly as PUT .../llm-keys stores them after its
provider check. The values are fake test keys: a key's status here stands
in for what the provider would have answered, since tests never send a key
to a real provider.

Usage:
  python seed-keys.py set <email> <provider>=<working|failed>[:<last4>] ...
  python seed-keys.py clear <email>      # every key, and the default provider
Prints JSON of the user's keys.
"""

import json
import os
import sys
from datetime import datetime, timezone

BACKEND = r"H:\Researchnexus\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)  # Settings() reads backend/.env for the key-vault secret

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import repository as repo  # noqa: E402
from app.domain.user import ApiKeyStatus, LlmProvider  # noqa: E402
from app.jobs.runner import new_id  # noqa: E402
from app.security.key_vault import KeyVault  # noqa: E402

mode, email = sys.argv[1], sys.argv[2]
db = sessionmaker(bind=create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db"))()
user = repo.get_user_by_email(db, email)
assert user is not None, f"sign in as {email} first"

if mode == "clear":
    for k in repo.list_api_keys(db, user.id):
        repo.delete_api_key(db, user.id, k.provider)
    repo.set_default_provider(db, user.id, None)
else:
    vault = KeyVault(Settings().key_vault_secret)
    for spec in sys.argv[3:]:
        provider, _, rest = spec.partition("=")
        status, _, last4 = rest.partition(":")
        fake = f"sk-test-{provider}-seeded-{last4 or '0000'}"
        repo.upsert_api_key(
            db, new_key_id=new_id("key"), owner_id=user.id, provider=LlmProvider(provider),
            key_ciphertext=vault.encrypt(fake), key_last4=fake[-4:], status=ApiKeyStatus(status),
            checked_at=datetime.now(timezone.utc),
        )

print(json.dumps([{"provider": k.provider.value, "status": k.status.value, "key_last4": k.key_last4} for k in repo.list_api_keys(db, user.id)]))
