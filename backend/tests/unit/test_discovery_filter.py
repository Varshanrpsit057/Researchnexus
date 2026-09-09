from __future__ import annotations

from app.domain.candidate import NormalizedCandidate
from app.services.discovery.base import DiscoveryFilters
from app.services.discovery.filter import apply_filters
from app.services.normalize.canonical import title_hash


def _c(title: str, *, year: int | None = 2022, abstract: str | None = "an abstract") -> NormalizedCandidate:
    return NormalizedCandidate(title=title, title_hash=title_hash(title), year=year, abstract=abstract)


def test_keeps_everything_when_no_filters_are_set() -> None:
    cands = [_c("A"), _c("B", year=None), _c("C", abstract=None)]
    result = apply_filters(cands, DiscoveryFilters())
    assert result.kept == cands
    assert result.dropped == []


def test_date_window_drops_out_of_range_years_but_not_unknown_years() -> None:
    cands = [_c("Old", year=2010), _c("New", year=2024), _c("Unknown", year=None)]
    result = apply_filters(cands, DiscoveryFilters(min_year=2018, max_year=2023))
    kept_titles = {c.title for c in result.kept}
    assert kept_titles == {"Unknown"}  # 2010 and 2024 dropped; unknown year is kept
    reasons = {c.title: r for c, r in result.dropped}
    assert reasons["Old"] == ["before_min_year"]
    assert reasons["New"] == ["after_max_year"]


def test_require_abstract_drops_candidates_without_one() -> None:
    result = apply_filters([_c("Has"), _c("Missing", abstract=None), _c("Blank", abstract="   ")], DiscoveryFilters(require_abstract=True))
    assert {c.title for c in result.kept} == {"Has"}
    assert {c.title for c, _ in result.dropped} == {"Missing", "Blank"}


def test_blank_title_is_always_dropped() -> None:
    result = apply_filters([_c("   ")], DiscoveryFilters())
    assert result.kept == []
    assert result.dropped[0][1] == ["no_title"]
