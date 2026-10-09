"""A discover job's life (remediation Phase 8): live progress on the job,
cancellation, a start that follows a run already going instead of starting a
second, a run that stopped responding or was cut off by a restart reported
as such, and a failure that says which step failed and why.

The discovery/ranking/trail pipelines are replaced (as in
test_discover_related_api.py) so no scholarly API is called; the job runner,
routes and repository are the real ones.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import JobORM, JobRunnerORM, PaperORM
from app.db.session import get_session_factory
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.profile import ProfileField, ResearchProfile
from app.jobs import runner as job_runner
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import ANONYMOUS, sign_in, signed_in
from tests.integration.test_discover_related_api import (
    _fake_build_trail,
    _fake_rank_search_run,
    _fake_run_discovery,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )


def _client(tmp_path: Path) -> TestClient:
    settings = _settings(tmp_path)
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return signed_in(TestClient(app))


def _sign_in(c: TestClient, email: str = "r@example.com") -> tuple[dict[str, str], str]:
    token = sign_in(c, email)
    return {"Authorization": f"Bearer {token}"}, c.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _seed(paper_id: str = "pap_seed") -> None:
    db = get_session_factory()()
    try:
        repo.save_paper(db, PaperORM(id=paper_id, title="Seed Paper", title_hash=title_hash(paper_id), has_full_text=True))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id=f"prof_{paper_id}", paper_id=paper_id, title="Seed Paper", abstract="ab",
                domain=ProfileField(value="IR"), research_problem=ProfileField(value="dense retrieval"),
            ),
        )
    finally:
        db.close()


def _job(owner_id: str, *, kind: JobKind = JobKind.DISCOVER, status: JobStatus = JobStatus.RUNNING, seed: str = "pap_seed") -> str:
    db = get_session_factory()()
    try:
        job_id = job_runner.new_id("job")
        repo.create_job(db, Job(job_id=job_id, owner_id=owner_id, kind=kind, status=status, progress={"seed_paper_id": seed}))
        return job_id
    finally:
        db.close()


def _age(job_id: str, seconds: float) -> None:
    db = get_session_factory()()
    try:
        row = db.get(JobORM, job_id)
        assert row is not None
        db.query(JobORM).filter(JobORM.id == job_id).update(
            {JobORM.updated_at: datetime.now(timezone.utc) - timedelta(seconds=seconds)}, synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def _patch(monkeypatch: pytest.MonkeyPatch, run_discovery=_fake_run_discovery) -> None:  # noqa: ANN001
    monkeypatch.setattr("app.services.discovery.pipeline.run_discovery", run_discovery)
    monkeypatch.setattr("app.services.ranking.pipeline.rank_search_run", _fake_rank_search_run)
    monkeypatch.setattr("app.services.trail.pipeline.build_trail", _fake_build_trail)


def test_a_finished_job_keeps_its_steps_and_the_seed_it_ran_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    c = _client(tmp_path)
    headers, _ = _sign_in(c)
    _seed()
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    assert started["resumed"] is False
    job = c.get(started["job"]["poll_url"]).json()
    assert job["status"] == "succeeded"
    assert job["progress"]["stage"] == "done"
    assert job["progress"]["seed_paper_id"] == "pap_seed"
    assert job["progress"]["steps"]["rank"]["state"] == "done"
    assert job["progress"]["steps"]["rank"]["ranked"] == 1
    assert job["progress"]["steps"]["trail"]["state"] == "done"


def test_starting_discovery_again_follows_the_run_already_going(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    c = _client(tmp_path)
    headers, user_id = _sign_in(c)
    _seed()
    running = _job(user_id)

    again = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    assert again["resumed"] is True
    assert again["job"]["job_id"] == running

    # a run that stopped responding is not followed: a fresh one starts
    _age(running, 120)
    fresh = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    assert fresh["resumed"] is False and fresh["job"]["job_id"] != running


def test_another_seed_or_another_owner_starts_its_own_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    c = _client(tmp_path)
    headers, _ = _sign_in(c)
    _, other_user = _sign_in(c, "other@example.com")
    _seed()
    _job(other_user)  # someone else's run of the same seed
    _job(other_user, seed="pap_elsewhere")
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    assert started["resumed"] is False


def test_the_owner_can_cancel_a_running_discovery_and_it_stays_cancelled(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, user_id = _sign_in(c)
    job_id = _job(user_id)

    body = c.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers).json()
    assert body["status"] == "cancelled"
    assert body["progress"]["stage"] == "cancelled"
    # whatever its worker writes afterwards is ignored
    db = get_session_factory()()
    try:
        repo.update_job(db, job_id, status=JobStatus.SUCCEEDED, progress={"stage": "done"}, result_ref="run_late")
    finally:
        db.close()
    after = c.get(f"/api/v1/jobs/{job_id}").json()
    assert after["status"] == "cancelled" and after["result_ref"] is None
    # cancelling again changes nothing
    assert c.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers).json()["status"] == "cancelled"


def test_only_the_owner_can_cancel_and_only_what_can_be_stopped(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, user_id = _sign_in(c)
    other_headers, _ = _sign_in(c, "other@example.com")
    job_id = _job(user_id)
    assert c.post(f"/api/v1/jobs/{job_id}/cancel", headers=other_headers).status_code == 404
    assert c.post(f"/api/v1/jobs/{job_id}/cancel", headers=ANONYMOUS).status_code == 401
    gaps = _job(user_id, kind=JobKind.GAPS)
    refused = c.post(f"/api/v1/jobs/{gaps}/cancel", headers=headers)
    assert refused.status_code == 409
    done = _job(user_id, status=JobStatus.SUCCEEDED)
    assert c.post(f"/api/v1/jobs/{done}/cancel", headers=headers).json()["status"] == "succeeded"


def test_a_cancelled_run_stops_within_a_moment_and_saves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached_the_end = threading.Event()

    async def slow_discovery(db, *, seed_paper_id, current_user, settings, options):  # noqa: ANN001, ARG001
        options.progress.begin("search", limit_s=30)
        await asyncio.sleep(10)
        reached_the_end.set()
        raise AssertionError("should have been cancelled")

    _patch(monkeypatch, slow_discovery)
    monkeypatch.setattr(job_runner, "CANCEL_POLL_S", 0.05)
    c = _client(tmp_path)
    _, user_id = _sign_in(c)
    _seed()
    job_id = _job(user_id, status=JobStatus.QUEUED)
    settings = _settings(tmp_path)
    worker = threading.Thread(
        target=job_runner.run_discover_related_job, args=(get_session_factory(), job_id, "pap_seed", user_id, settings)
    )
    worker.start()
    deadline = time.monotonic() + 5
    while c.get(f"/api/v1/jobs/{job_id}").json()["progress"].get("step") != "search" and time.monotonic() < deadline:
        time.sleep(0.02)

    db = get_session_factory()()
    try:
        repo.cancel_job(db, job_id)
    finally:
        db.close()
    stopped_at = time.monotonic()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert time.monotonic() - stopped_at < 1.0
    assert not reached_the_end.is_set()
    job = c.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "cancelled" and job["result_ref"] is None


def test_a_failed_run_says_which_step_failed_and_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(db, *, seed_paper_id, current_user, settings, options):  # noqa: ANN001, ARG001
        options.progress.begin("search", limit_s=30)
        raise RuntimeError("every source refused the request")

    _patch(monkeypatch, broken)
    c = _client(tmp_path)
    headers, _ = _sign_in(c)
    _seed()
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    job = c.get(started["job"]["poll_url"]).json()
    assert job["status"] == "failed"
    assert job["error"] == "The discovery step failed: every source refused the request"
    assert job["progress"]["stage"] == "failed"
    assert job["progress"]["steps"]["search"]["state"] == "failed"


def test_a_run_whose_save_fails_is_still_recorded_as_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # found measuring a real run: a failed write left the session needing a
    # rollback, so the job couldn't record its own failure and stayed "running"
    async def save_fails(db, *, seed_paper_id, current_user, settings, options):  # noqa: ANN001, ARG001
        options.progress.begin("save", total=1)
        db.add(PaperORM(id=seed_paper_id, title="Duplicate", title_hash="dup", has_full_text=False))
        db.flush()  # the seed's id again: IntegrityError

    _patch(monkeypatch, save_fails)
    c = _client(tmp_path)
    headers, _ = _sign_in(c)
    _seed()
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    job = c.get(started["job"]["poll_url"]).json()
    assert job["status"] == "failed"
    assert job["error"].startswith("The discovery step failed: ")
    assert job["progress"]["steps"]["save"]["state"] == "failed"


def test_a_run_that_stopped_responding_is_reported_as_failed(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _, user_id = _sign_in(c)
    job_id = _job(user_id)
    assert c.get(f"/api/v1/jobs/{job_id}").json()["status"] == "running"  # heard from just now
    _age(job_id, 120)
    job = c.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error"] == "The run stopped responding before it finished."
    assert job["progress"]["stage"] == "interrupted"


def _run_by(job_id: str, runner_id: str | None, *, heard_from_s_ago: float | None = None) -> None:
    """Say which server process runs the job (and, if given, when that
    process last said it was alive)."""
    db = get_session_factory()()
    try:
        row = db.get(JobORM, job_id)
        assert row is not None
        row.runner_id = runner_id
        if runner_id is not None and heard_from_s_ago is not None:
            now = datetime.now(timezone.utc)
            beat = now - timedelta(seconds=heard_from_s_ago)
            db.merge(JobRunnerORM(id=runner_id, started_at=beat, heartbeat_at=beat))
        db.commit()
    finally:
        db.close()


def test_jobs_cut_off_by_a_restart_are_failed_when_the_server_starts(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _, user_id = _sign_in(c)
    running = _job(user_id)
    queued = _job(user_id, status=JobStatus.QUEUED)
    finished = _job(user_id, status=JobStatus.SUCCEEDED)
    from_before_runners = _job(user_id)
    # the process that ran them stopped three minutes ago
    for job_id in (running, queued, finished):
        _run_by(job_id, "old-host:41:dead", heard_from_s_ago=180)
    _run_by(from_before_runners, None)
    # another server, alive, is still running this one
    elsewhere = _job(user_id)
    _run_by(elsewhere, "other-host:7:alive", heard_from_s_ago=5)

    settings = _settings(tmp_path)
    app = create_app(settings=settings)
    with signed_in(TestClient(app)) as restarted:  # runs the app's startup
        for job_id in (running, queued, from_before_runners):
            job = restarted.get(f"/api/v1/jobs/{job_id}").json()
            assert job["status"] == "failed"
            assert job["error"] == "The server restarted before this finished."
            assert job["progress"]["stage"] == "interrupted"
        assert restarted.get(f"/api/v1/jobs/{finished}").json()["status"] == "succeeded"
        # a starting server leaves another live server's jobs alone
        assert restarted.get(f"/api/v1/jobs/{elsewhere}").json()["status"] == "running"


def test_related_results_carry_how_the_run_went(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    c = _client(tmp_path)
    headers, _ = _sign_in(c)
    _seed()
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()
    run_id = c.get(started["job"]["poll_url"]).json()["result_ref"]
    run = c.get(f"/api/v1/papers/pap_seed/related?run_id={run_id}", headers=headers).json()["run"]
    assert "report" in run  # the fake run was saved without one: null, never made up
    assert run["report"] is None
    assert run["started_at"] is not None
