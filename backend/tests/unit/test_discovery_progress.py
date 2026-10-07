"""A discovery run's live progress (remediation Phase 8): only measured
times, real counts and the limits the run enforces -- written to the job at
most twice a second, and at once when a step starts or ends."""

from __future__ import annotations

from app.domain.candidate import CandidateSource, DiscoveryStrategy, RawExternalRecord
from app.services.discovery.progress import PREVIEW_SIZE, STEPS, DiscoveryProgress


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _rec(title: str, doi: str) -> RawExternalRecord:
    return RawExternalRecord(source=CandidateSource.OPENALEX, doi=doi, title=title, year=2022)


def test_steps_record_their_measured_time_and_only_real_limits() -> None:
    clock = _Clock()
    progress = DiscoveryProgress(clock=clock)
    assert [progress.steps[s]["state"] for s in STEPS] == ["pending"] * len(STEPS)

    progress.begin("search", limit_s=30)
    snap = progress.snapshot()
    assert snap["step"] == "search" and snap["stage"] == "discovery"
    assert snap["steps"]["search"] == {"state": "running", "started_s": 0.0, "limit_s": 30}

    clock.t += 12.34
    progress.end("search", note="4 strategies")
    assert progress.steps["search"] == {"started_s": 0.0, "limit_s": 30, "state": "done", "seconds": 12.3, "note": "4 strategies"}
    assert progress.snapshot()["step"] == ""

    progress.begin("rank")
    assert progress.snapshot()["stage"] == "ranking"  # the coarse stage older pages read
    progress.skip("trail", "no ranked papers")
    assert progress.steps["trail"] == {"state": "skipped", "note": "no ranked papers"}


def test_each_source_counts_its_answers_failures_and_cache_hits() -> None:
    progress = DiscoveryProgress()
    progress.on_request("api.openalex.org", "http_503", 0.1)
    progress.on_request("api.openalex.org", "ok", 3.5)
    progress.on_request("api.openalex.org", "cached", 0.0)
    progress.on_request("export.arxiv.org", "ok", 1.0)
    assert progress.sources["openalex"] == {"answered": 1, "failed": 1, "cached": 1, "last_failure": "http_503", "seconds": 3.6}
    assert progress.sources["arxiv"]["answered"] == 1


def test_found_counts_distinct_papers_across_strategies_and_previews_the_first_few() -> None:
    progress = DiscoveryProgress()
    progress.strategy_started(DiscoveryStrategy.KEYWORD)
    progress.strategy_started(DiscoveryStrategy.CITATION)
    progress.found(DiscoveryStrategy.KEYWORD, [_rec("Alpha", "10.1/a"), _rec("Beta", "10.1/b")])
    progress.found(DiscoveryStrategy.CITATION, [_rec("Alpha", "10.1/a"), _rec("Gamma", "10.1/c")])
    assert progress.distinct_found == 3
    assert [p["title"] for p in progress.preview] == ["Alpha", "Beta", "Gamma"]
    assert progress.strategies["citation"] == {"state": "running", "found": 2}

    progress.found(DiscoveryStrategy.KEYWORD, [_rec(f"Paper {i}", f"10.2/{i}") for i in range(20)])
    assert len(progress.preview) == PREVIEW_SIZE


def test_a_finished_strategy_keeps_its_state_count_time_and_notes() -> None:
    clock = _Clock()
    progress = DiscoveryProgress(clock=clock)
    progress.strategy_started(DiscoveryStrategy.CITATION)
    clock.t += 25.0
    progress.strategy_finished(
        DiscoveryStrategy.CITATION, state="timed_out", found=40, notes=["citation_cites_seed_failed", "citation_cites_seed_failed"]
    )
    assert progress.strategies["citation"] == {
        "state": "timed_out", "found": 40, "seconds": 25.0, "notes": ["citation_cites_seed_failed"],
    }


def test_writes_are_throttled_but_step_changes_go_out_at_once() -> None:
    clock = _Clock()
    written: list[dict] = []
    progress = DiscoveryProgress(written.append, clock=clock, min_interval_s=0.5)

    progress.begin("search")  # forced
    progress.on_request("api.openalex.org", "ok", 1.0)  # within 0.5 s of the last write: held back
    assert len(written) == 1
    clock.t += 0.6
    progress.on_request("api.openalex.org", "ok", 1.0)
    assert len(written) == 2
    assert written[-1]["sources"]["openalex"]["answered"] == 2  # nothing held back is lost
    progress.end("search")  # forced
    assert len(written) == 3


def test_the_report_is_what_the_saved_run_keeps() -> None:
    progress = DiscoveryProgress()
    progress.begin("plan")
    progress.end("plan", note="model")
    progress.warn("resolve_timed_out", "resolve_timed_out")
    report = progress.report()
    assert set(report) == {"started_at", "elapsed_s", "steps", "strategies", "sources", "warnings"}
    assert report["steps"]["plan"]["note"] == "model"
    assert report["warnings"] == ["resolve_timed_out"]


def test_the_seed_itself_is_never_counted_or_shown_as_found() -> None:
    # found on a real run: the seed was the first paper in the live preview
    from app.services.normalize.canonical import title_hash
    from app.services.normalize.dedupe import SeedIdentity

    progress = DiscoveryProgress()
    progress.exclude_seed(SeedIdentity(doi="10.1/seed", title_hash=title_hash("The Seed Paper")))
    progress.strategy_started(DiscoveryStrategy.KEYWORD)
    progress.found(
        DiscoveryStrategy.KEYWORD,
        [_rec("The Seed Paper", "10.9/other-copy"), _rec("Seed By Doi", "10.1/seed"), _rec("A Related Paper", "10.1/related")],
    )
    assert progress.distinct_found == 1
    assert [p["title"] for p in progress.preview] == ["A Related Paper"]
