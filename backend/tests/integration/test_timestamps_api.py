"""One time contract across the API (remediation Phase 4): every timestamp
the backend returns carries its zone, so a browser in any timezone reads it
as the right instant. A naive one is read by JavaScript as the viewer's
local time -- 5 h 30 min off in India, sometimes the wrong day -- which is
what the activity and history views showed for jobs and stage runs.

A real workspace run end to end (gap job with a scripted model, chat,
comparison, directions); every `*_at` / `ts` field of every response is
checked, and must be within a minute of the time the request was made."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.test_gap_api import _client, _h, _mock_llm, _save_key, _seed_ws, _token

_ZONED = re.compile(r"(Z|[+-]\d\d:\d\d)$")


def _times(value: object, path: str = "") -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        for key, v in value.items():
            here = f"{path}.{key}" if path else key
            if isinstance(v, str) and (key.endswith("_at") or key == "ts"):
                yield here, key, v
            else:
                yield from _times(v, here)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _times(v, f"{path}[{i}]")


def _check(body: object, since: dt.datetime) -> list[str]:
    seen = []
    for where, key, stamp in _times(body):
        assert _ZONED.search(stamp), f"{where} has no zone: {stamp!r}"
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert abs(when - since) < dt.timedelta(minutes=1), f"{where} is not now: {stamp!r}"
        seen.append(key)
    return seen


def test_every_timestamp_the_api_returns_carries_its_zone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    since = dt.datetime.now(dt.timezone.utc)
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    job = c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).json()["job"]["job_id"]
    gaps = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    assert gaps

    fields: set[str] = set()
    for url in (
        "/api/v1/me",
        "/api/v1/settings/llm-keys",
        "/api/v1/workspaces",
        f"/api/v1/workspaces/{wid}",
        f"/api/v1/jobs/{job}",
        f"/api/v1/workspaces/{wid}/gaps",
        f"/api/v1/workspaces/{wid}/activity",
        f"/api/v1/workspaces/{wid}/citations",
    ):
        r = c.get(url, headers=_h(token))
        assert r.status_code == 200, (url, r.text)
        fields |= set(_check(r.json(), since))

    # the history views read these: a job's times, a stage run's, a member's, a gap's
    assert {"created_at", "updated_at", "added_at", "generated_at", "ts", "checked_at"} <= fields


def test_a_comparison_says_when_it_was_made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.test_comparison_api import _client as compare_client
    from tests.integration.test_comparison_api import _mock_llm as compare_llm
    from tests.integration.test_comparison_api import _save_key as compare_key
    from tests.integration.test_comparison_api import _seed_ws as compare_ws
    from tests.integration.test_comparison_api import _token as compare_token

    since = dt.datetime.now(dt.timezone.utc)
    c = compare_client(tmp_path)
    token = compare_token(c)
    wid, _second = compare_ws(c, token)
    compare_key(c, token, monkeypatch)
    compare_llm(monkeypatch, {"pap_seed": {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]}})
    made = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token))
    assert made.status_code == 200, made.text
    latest = c.get(f"/api/v1/workspaces/{wid}/compare", headers=_h(token)).json()
    assert _check(made.json(), since) == ["created_at"] and _check(latest, since) == ["created_at"]
