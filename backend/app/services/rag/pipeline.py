"""RAG orchestration (Architecture §3 S13; Roadmap Phase 9).

Fixed stage order, each stage degrading safely:

    retrieve -> rerank -> contextual filter -> answerability gate
      -> generate (per-sentence chunk tags) -> IsSupported? verify
      -> faithfulness gate (regenerate once, then warn)
      -> assemble claims (deterministic chunk->paper link)

Guarantees carried out of this module:
- a rendered sentence cites only retrieved chunk ids (generate + link);
- unsupported sentences are dropped (default) or flagged, never rendered as
  a grounded claim with no chunk;
- the answerability gate returns "not enough in this workspace" + a
  suggestion with **no generation tokens billed**;
- reference strings are never generated (stripped in `generate`);
- a provider failure (rejected key, no credit, timeout, ...) is raised as
  `LlmProviderError`, never reported as a bad answer; a verifier whose reply
  couldn't be used is the warning `verification_failed`, never "every
  sentence unsupported"; the model finding nothing in the context that
  answers the question is "not answerable", never an empty answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.rag import AnswerSentence, RagAnswer
from app.domain.workspace import ResearchWorkspace
from app.llm.client import LlmProviderError
from app.llm.session import LlmSession
from app.retrieval.embeddings import get_embedding_provider
from app.retrieval.reranker import CrossEncoderReranker, get_reranker
from app.retrieval.workspace_index import FaissWorkspaceIndex, WorkspaceChunkIndex
from app.services.citations.validate import link_claims
from app.services.ingest.abstract_chunks import ensure_abstract_chunks
from app.services.rag.answerability import assess, suggestion_for
from app.services.rag.context_filter import filter_chunks
from app.services.rag.faithfulness import passes, score_faithfulness
from app.services.rag.generate import DraftAnswer, generate_answer
from app.services.rag.rerank import rerank
from app.services.rag.retriever import retrieve
from app.services.rag.verify import VerificationUnavailable, verify_sentences

# What the pipeline is doing right now, for a caller streaming progress:
# searching (retrieve + rerank), reading (the contextual filter), writing
# (generation), checking (per-sentence verification), rewriting (the one
# faithfulness-gate regeneration).
RagStage = Literal["searching", "reading", "writing", "checking", "rewriting"]
StageHook = Callable[[RagStage], None]


def _noop(_: RagStage) -> None:
    return None


@dataclass
class RagRequest:
    query: str
    scope_paper_ids: list[str] | None = None  # None -> the whole workspace
    mode: str = "qa"


@dataclass
class _Budget:
    prompt: int = 0
    completion: int = 0
    warnings: list[str] = field(default_factory=list)

    def add(self, pt: int, ct: int) -> None:
        self.prompt += pt
        self.completion += ct


def _build_index(db: Session, workspace: ResearchWorkspace, settings: Settings) -> FaissWorkspaceIndex:
    idx = FaissWorkspaceIndex(
        db,
        workspace_id=workspace.workspace_id,
        index_dir=Path(settings.data_dir) / "workspace_index",
        embedder=get_embedding_provider(settings.rag_embedder),
        vector_backend=settings.rag_vector_backend,
    )
    ensure_abstract_chunks(db, [p.paper_id for p in workspace.papers])
    idx.rebuild([p.paper_id for p in workspace.papers])
    return idx


async def answer_question(
    db: Session,
    *,
    workspace: ResearchWorkspace,
    request: RagRequest,
    session: LlmSession | None,
    settings: Settings,
    index: WorkspaceChunkIndex | None = None,
    reranker: CrossEncoderReranker | None = None,
    on_stage: StageHook | None = None,
) -> RagAnswer:
    stage = on_stage or _noop
    stage("searching")
    index = index or _build_index(db, workspace, settings)
    reranker = reranker or get_reranker(settings.rag_reranker)
    budget = _Budget()

    retrieved = retrieve(
        db, index, request.query, k=settings.rag_retrieve_k, scope_paper_ids=request.scope_paper_ids
    )
    reranked = rerank(request.query, retrieved, reranker, settings.rag_rerank_top_n)
    stage("reading")
    filtered, pt, ct = await filter_chunks(session, request.query, reranked, raise_provider_errors=True)
    budget.add(pt, ct)

    verdict = assess(request.query, filtered, min_chunks=settings.rag_min_answerable_chunks)
    if not verdict.answerable:
        return RagAnswer(
            answerable=False,
            suggestion=verdict.suggestion,
            prompt_tokens=budget.prompt,
            completion_tokens=budget.completion,
            warnings=["not_answerable"],
        )

    kept = [c for c in filtered if c.kept]
    chunk_text = {c.chunk_id: c.text for c in kept}

    sentences, faith, regenerated = await _generate_verify_gate(
        session, request.query, kept, chunk_text, settings, budget, stage
    )
    if not sentences and "no_answer_in_context" in budget.warnings:
        # the model read the passages and found nothing that answers the question
        return RagAnswer(
            answerable=False,
            suggestion=suggestion_for(request.query),
            prompt_tokens=budget.prompt,
            completion_tokens=budget.completion,
            warnings=["not_answerable"],
        )

    rendered, dropped = _apply_support_policy(sentences, settings.rag_drop_unsupported)
    answer = RagAnswer(
        answerable=True,
        text=" ".join(s.text for s in rendered),
        sentences=rendered,
        faithfulness=faith,
        faithfulness_passed=passes(faith, settings.rag_faithfulness_min),
        regenerated=regenerated,
        unsupported_dropped=dropped,
        used_chunk_ids=sorted({cid for s in rendered for cid in s.chunk_ids}),
        prompt_tokens=budget.prompt,
        completion_tokens=budget.completion,
        warnings=list(budget.warnings),
    )
    if not answer.faithfulness_passed:
        answer.warnings.append("faithfulness_below_threshold")
    if not rendered:
        answer.warnings.append("no_supported_sentences")
    return answer


async def _generate_verify_gate(
    session: LlmSession | None,
    query: str,
    kept: list,
    chunk_text: dict[str, str],
    settings: Settings,
    budget: _Budget,
    stage: StageHook = _noop,
) -> tuple[list[AnswerSentence], float, bool]:
    async def one_pass(q: str) -> tuple[DraftAnswer, list[AnswerSentence], float]:
        draft = await generate_answer(session, q, kept, raise_provider_errors=True)
        budget.add(draft.prompt_tokens, draft.completion_tokens)
        if not draft.ok:
            return draft, [], 0.0
        if not draft.sentences:
            _warn(budget, "no_answer_in_context")
            return draft, [], 0.0
        stage("checking")
        try:
            verified, pt, ct = await verify_sentences(session, draft.sentences, chunk_text, strict=True)
        except VerificationUnavailable as e:
            budget.add(e.prompt_tokens, e.completion_tokens)
            _warn(budget, "verification_failed")
            return draft, [], 0.0
        budget.add(pt, ct)
        supported_text = [s.text for s in verified if s.is_supported]
        score = score_faithfulness(" ".join(supported_text), [chunk_text[c] for c in chunk_text])
        return draft, verified, score

    stage("writing")
    draft, sentences, faith = await one_pass(query)
    if not draft.ok:
        budget.warnings.append("generation_failed")
        return [], 0.0, False
    if not draft.sentences:
        return [], 0.0, False  # no_answer_in_context

    if not passes(faith, settings.rag_faithfulness_min):
        retry_q = (
            f"{query}\n\n(The previous answer failed a faithfulness check. "
            "Ground every sentence strictly in the context and cite the exact chunk.)"
        )
        stage("rewriting")
        before = list(budget.warnings)
        try:
            draft2, sentences2, faith2 = await one_pass(retry_q)
        except LlmProviderError:
            if sentences:
                return sentences, faith, False  # the rewrite is optional: keep the first answer
            raise
        if draft2.ok and sentences2:
            # the rewrite was generated and checked: only its own outcome stands
            budget.warnings[:] = [w for w in budget.warnings if w not in ("verification_failed", "no_answer_in_context")]
            return sentences2, faith2, True
        if sentences:
            budget.warnings[:] = before  # a rewrite that went nowhere changes nothing
    return sentences, faith, False


def _warn(budget: _Budget, warning: str) -> None:
    if warning not in budget.warnings:
        budget.warnings.append(warning)


def _apply_support_policy(
    sentences: list[AnswerSentence], drop_unsupported: bool
) -> tuple[list[AnswerSentence], int]:
    dropped = 0
    rendered: list[AnswerSentence] = []
    for s in sentences:
        grounded = bool(s.chunk_ids) and s.is_supported
        if grounded:
            rendered.append(s)
        elif drop_unsupported:
            dropped += 1
        else:
            rendered.append(s.model_copy(update={"flagged_unsupported": True}))
    return rendered, dropped


def build_answer_claims(
    answer: RagAnswer, *, workspace_id: str, message_id: str, retrieved_chunk_ids: set[str], chunk_to_paper: dict[str, str]
) -> list:
    claims = answer.to_claims(workspace_id=workspace_id, artefact_id=message_id)
    return link_claims(claims, retrieved_chunk_ids=retrieved_chunk_ids, chunk_to_paper=chunk_to_paper)
