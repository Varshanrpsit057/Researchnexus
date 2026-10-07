"""Gap workflow orchestration (Architecture §3 / §4 `GapAnalyzer`; Data
Model §8 "Pipeline (enforced in code order)"; Roadmap Phase 11).

Fixed order, every step a hard gate:

    first-use profiles (a member without one is read by the model: its full
      text, else its abstract, flagged `grounding="abstract"`)
      ->  matrix  ->  deterministic rule candidates (+ trail CONTRADICTION edges)
      ->  evidence assembly (>= 2 real papers or DROP)
      ->  constrained LLM articulation (an unsupported term -> the rule's own
          template phrases it instead; the gap itself is the rule's)
      ->  Self-RAG self-support check over the quotes + the rule's facts (fails -> DROP)
      ->  deterministic confidence band  ->  persist as `user_state="candidate"`

The LLM never sees a paper before a rule has fired, and no `ResearchGap`
is ever built from fewer than two evidence spans. `gap_id` is derived from
(workspace, type, papers, rule, key) so a rerun upserts the same rows;
`match_key` is the same without the papers, so a gap a person accepted or
rejected is recognised even when a later run finds it with more papers: a
rejected gap is never re-proposed and an accepted one never duplicated
(neither costs a model call).

How the work is bounded (remediation Phase 3 -- runs used to die at a 60 s
stage limit while papers were profiled one by one, ~7 s each):
- papers are profiled `gap_llm_concurrency` at a time, each under its own
  time limit; every profile is saved as it finishes, so a run that stops
  early leaves them for the next one;
- candidates are phrased and checked the same way, strongest rules first,
  at most `gap_max_candidates_per_run` of them (the rest are counted);
- `on_progress` hears each step as it happens.

Provider failures are not hidden: a rejected key or an account out of
credit stops the run with that reason (every call would fail the same
way); a slow or failed reply for one paper or candidate is counted and the
run goes on; if every model call failed, the run fails with the provider's
reason instead of reporting "no gaps".
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.gap import GapType, ResearchGap
from app.domain.workspace import Grounding, ResearchWorkspace
from app.llm.client import LlmErrorKind, LlmProviderError
from app.llm.session import LlmSession
from app.services.gaps.articulate_llm import articulate
from app.services.gaps.candidates import (
    GapCandidate,
    contradiction_candidates,
    generate_candidates,
    rule_facts,
)
from app.services.gaps.confidence import assign_confidence, self_support_check
from app.services.gaps.evidence import assemble
from app.services.gaps.matrix import PaperMeta, build_matrix
from app.services.ingest.abstract_chunks import ensure_abstract_chunks
from app.services.profile.pipeline import profile_with_session

ProgressHook = Callable[[dict[str, str]], None]

# failures every later call would repeat: stop the run, say why
_FATAL = {LlmErrorKind.AUTH, LlmErrorKind.INSUFFICIENT_BALANCE}

# which rules are checked first when there are more candidates than a run
# checks: agreement between papers and conflicts before "one paper uses X"
_RULE_ORDER = {
    "trail_contradiction": 0,
    "shared_limitation": 1,
    "method_dataset_combination": 2,
    "dataset_divergence": 3,
    "metric_divergence": 3,
    "temporal_staleness": 4,
    "method_coverage": 5,
}


@dataclass
class GapBuildOptions:
    gap_types: set[GapType] | None = None
    min_supporting_papers: int = 2


@dataclass
class GapBuildResult:
    workspace_id: str
    candidate_count: int = 0
    gap_count: int = 0
    dropped_insufficient_evidence: int = 0
    dropped_self_support: int = 0
    unchecked: int = 0          # a check that couldn't run: a failed or unusable reply, or too slow
    not_checked: int = 0        # beyond this run's cap; the strongest were checked first
    skipped_rejected: int = 0
    kept_accepted: int = 0      # found again, already accepted: kept as it was, no new candidate
    rephrased: int = 0          # phrased by the rule's template because the model's wording added a term
    profiled: int = 0           # members profiled for this run (they had none)
    unprofiled: int = 0         # members with no text to read, so no rule could see them
    profile_failed: int = 0     # members whose reading failed this time; the next run tries again
    by_type: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, str]:
        """What a finished job records: what happened to every candidate
        and paper, so a small or empty result can say why."""
        return {
            "stage": "done",
            "gaps": "done",
            "count": str(self.gap_count),
            "candidates": str(self.candidate_count),
            "dropped_insufficient_evidence": str(self.dropped_insufficient_evidence),
            "dropped_self_support": str(self.dropped_self_support),
            "unchecked": str(self.unchecked),
            "not_checked": str(self.not_checked),
            "skipped_rejected": str(self.skipped_rejected),
            "kept_accepted": str(self.kept_accepted),
            "rephrased": str(self.rephrased),
            "profiled": str(self.profiled),
            "unprofiled": str(self.unprofiled),
            "profile_failed": str(self.profile_failed),
        }


@dataclass
class _ModelCalls:
    """Every piece of model work a run attempted, and the provider failures."""

    attempted: int = 0
    failed: int = 0
    last_error: LlmProviderError | None = None

    def failure(self, error: LlmProviderError) -> None:
        self.failed += 1
        self.last_error = error


def _candidate_key(cand: GapCandidate) -> str:
    f = cand.facts
    return "|".join(
        str(x)
        for x in (
            f.get("value", ""),
            f.get("method", ""),
            f.get("dataset", ""),
            f.get("topic", ""),
            f.get("edge_id", ""),
            f.get("facet", ""),
        )
    )


def _gap_id(workspace_id: str, cand: GapCandidate) -> str:
    papers = ",".join(sorted(set(cand.supporting_papers)))
    raw = f"{workspace_id}|{cand.gap_type.value}|{cand.detection_rule}|{papers}|{_candidate_key(cand)}"
    return f"gap_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _match_key(workspace_id: str, cand: GapCandidate) -> str:
    raw = f"{workspace_id}|{cand.gap_type.value}|{cand.detection_rule}|{_candidate_key(cand)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _priority(item: tuple[GapCandidate, str, str]) -> tuple:
    cand, gap_id, _key = item
    value = str(cand.facts.get("value") or cand.facts.get("method") or cand.facts.get("topic") or "")
    return (
        _RULE_ORDER.get(cand.detection_rule, 9),
        -len(set(cand.supporting_papers)),
        -cand.evidence_coverage,
        len(value),  # a method's name before a sentence describing a feature
        gap_id,
    )


def _paper_metas(db: Session, workspace: ResearchWorkspace) -> list[PaperMeta]:
    metas: list[PaperMeta] = []
    for wp in workspace.papers:
        paper = repo.get_paper(db, wp.paper_id)
        metas.append(
            PaperMeta(
                paper_id=wp.paper_id,
                title=paper.title if paper else wp.paper_id,
                year=paper.year if paper else None,
                abstract_only=wp.grounding is Grounding.ABSTRACT,
            )
        )
    return metas


async def _bounded(limit: int, jobs: Iterable[Awaitable[object]]) -> list[object]:
    """Run `jobs` at most `limit` at a time; the first exception cancels the rest."""
    sem = asyncio.Semaphore(max(1, limit))

    async def gated(job: Awaitable[object]) -> object:
        async with sem:
            return await job

    tasks = [asyncio.ensure_future(gated(j)) for j in jobs]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _read_from_abstract_only(db: Session, paper_id: str) -> bool:
    profile = repo.get_profile(db, paper_id)
    paper = repo.get_paper(db, paper_id)
    return profile is not None and profile.grounding == "abstract" and paper is not None and paper.has_full_text


async def _profile_missing(
    db: Session,
    workspace: ResearchWorkspace,
    session: LlmSession | None,
    settings: Settings,
    result: GapBuildResult,
    report: ProgressHook,
    calls: _ModelCalls,
) -> None:
    never = [wp.paper_id for wp in workspace.papers if repo.get_profile(db, wp.paper_id) is None]
    # a profile read from the abstract of a paper whose full text has since been found is read again
    # (if that fails, the abstract's profile stays)
    stale = [wp.paper_id for wp in workspace.papers if wp.paper_id not in never and _read_from_abstract_only(db, wp.paper_id)]
    missing = [*never, *stale]
    if not missing:
        return
    ensure_abstract_chunks(db, missing)
    readable = [pid for pid in missing if repo.get_chunks_for_paper(db, pid)]
    result.unprofiled += len(never) - len([p for p in readable if p in never])  # nothing to read: no full text, no abstract
    if session is None:
        result.unprofiled += len([p for p in readable if p in never])
        return
    done = 0
    report({"stage": "profiling", "done": "0", "total": str(len(readable))})

    async def read(pid: str) -> None:
        nonlocal done
        calls.attempted += 1
        try:
            paper = repo.get_paper(db, pid)
            profile = (
                await asyncio.wait_for(profile_with_session(db, paper, session, settings), settings.gap_profile_timeout_s)
                if paper is not None
                else None
            )
            if profile is None:
                result.profile_failed += 1  # the reply couldn't be used
            else:
                result.profiled += 1
        except LlmProviderError as e:
            if e.kind in _FATAL:
                raise
            calls.failure(e)
            result.profile_failed += 1
        except asyncio.TimeoutError:
            result.profile_failed += 1
        finally:
            done += 1
            report({"stage": "profiling", "done": str(done), "total": str(len(readable))})

    await _bounded(settings.gap_llm_concurrency, (read(pid) for pid in readable))


async def build_gaps(
    db: Session,
    *,
    workspace: ResearchWorkspace,
    options: GapBuildOptions,
    session: LlmSession | None,
    settings: Settings,
    on_progress: ProgressHook | None = None,
) -> GapBuildResult:
    report: ProgressHook = on_progress or (lambda _progress: None)
    result = GapBuildResult(workspace_id=workspace.workspace_id)
    calls = _ModelCalls()
    await _profile_missing(db, workspace, session, settings, result, report, calls)

    report({"stage": "detecting", "done": "0", "total": "0"})
    profiles = {
        wp.paper_id: p
        for wp in workspace.papers
        if (p := repo.get_profile(db, wp.paper_id)) is not None
    }
    abstract_only = {pid for pid, p in profiles.items() if p.grounding == "abstract"}
    metas = _paper_metas(db, workspace)
    titles = {m.paper_id: m.title for m in metas}
    matrix = build_matrix(profiles, metas)

    candidates = generate_candidates(matrix, gap_types=options.gap_types)
    trail_edges = repo.get_workspace_trail_edges(db, workspace.workspace_id)
    contradiction = contradiction_candidates(trail_edges)
    if options.gap_types is not None:
        contradiction = [c for c in contradiction if c.gap_type in options.gap_types]
    candidates += contradiction
    result.candidate_count = len(candidates)

    decided = repo.get_decided_gaps(db, workspace.workspace_id)
    todo: list[tuple[GapCandidate, str, str]] = []
    for cand in candidates:
        assembled = assemble(cand, min_papers=options.min_supporting_papers, abstract_only=abstract_only)
        if assembled is None:
            result.dropped_insufficient_evidence += 1
            continue
        gap_id, key = _gap_id(workspace.workspace_id, assembled), _match_key(workspace.workspace_id, assembled)
        if decided.rejected(gap_id, key):
            result.skipped_rejected += 1
        elif decided.accepted(gap_id, key):
            result.kept_accepted += 1
        else:
            todo.append((assembled, gap_id, key))

    todo.sort(key=_priority)
    cap = max(0, settings.gap_max_candidates_per_run)
    result.not_checked = max(0, len(todo) - cap)
    todo = todo[:cap]
    done = 0
    report({"stage": "checking", "done": "0", "total": str(len(todo))})

    async def check(item: tuple[GapCandidate, str, str]) -> ResearchGap | None:
        nonlocal done
        assembled, gap_id, key = item
        if session is not None:
            calls.attempted += 1
        try:
            return await asyncio.wait_for(
                _check_candidate(assembled, gap_id, key, session, titles, workspace.workspace_id, result),
                settings.gap_candidate_timeout_s,
            )
        except LlmProviderError as e:
            if e.kind in _FATAL:
                raise
            calls.failure(e)
            result.unchecked += 1
            return None
        except asyncio.TimeoutError:
            result.unchecked += 1
            return None
        finally:
            done += 1
            report({"stage": "checking", "done": str(done), "total": str(len(todo))})

    checked = await _bounded(settings.gap_llm_concurrency, (check(item) for item in todo))
    gaps = [g for g in checked if isinstance(g, ResearchGap)]

    if calls.attempted and calls.failed == calls.attempted and calls.last_error is not None:
        raise calls.last_error  # the provider failed every call: that is the result, not "no gaps"

    for gap in gaps:
        result.by_type[gap.gap_type.value] = result.by_type.get(gap.gap_type.value, 0) + 1
    report({"stage": "saving", "done": "0", "total": str(len(gaps))})
    repo.save_gaps(db, workspace.workspace_id, gaps, owner_id=workspace.owner_id)
    result.gap_count = len(gaps)
    return result


async def _check_candidate(
    assembled: GapCandidate,
    gap_id: str,
    match_key: str,
    session: LlmSession | None,
    titles: dict[str, str],
    workspace_id: str,
    result: GapBuildResult,
) -> ResearchGap | None:
    art = await articulate(session, assembled, strict=True)
    if art.fallback == "ungrounded":
        result.rephrased += 1

    quotes = [e.span.quote for e in assembled.supporting_evidence] + [
        e.span.quote for e in assembled.conflicting_evidence
    ]
    self_support = await self_support_check(
        session, art.statement, quotes, facts=rule_facts(assembled, titles), strict=True
    )
    if self_support is None:
        result.unchecked += 1
        return None
    if not self_support:
        result.dropped_self_support += 1
        return None

    confidence, basis = assign_confidence(
        assembled, self_support_passed=self_support, evidence_coverage=assembled.evidence_coverage
    )
    return ResearchGap(
        gap_id=gap_id,
        workspace_id=workspace_id,
        statement=art.statement,
        gap_type=assembled.gap_type,
        supporting_papers=assembled.supporting_papers,
        supporting_evidence=list(assembled.supporting_evidence),
        conflicting_evidence=list(assembled.conflicting_evidence),
        why_unaddressed=art.why_unaddressed,
        affected_methods=list(assembled.affected_methods),
        affected_datasets=list(assembled.affected_datasets),
        evidence_coverage=assembled.evidence_coverage,
        confidence=confidence,
        confidence_basis=basis,
        proposed_direction=art.proposed_direction,
        detection_rule=assembled.detection_rule,
        self_support_passed=self_support,
        generator_model=art.generator_model,
        match_key=match_key,
    )
