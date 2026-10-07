"""Per-paper ranking explanation (Architecture §3 S10; Data Model §4
`RankingExplanation`).

`build_explanation` is fully deterministic: one bullet per signal at or
above the display threshold, phrased with that signal's *actual* value.
There is never a bullet without a signal, and the list is never empty
(a below-threshold match still gets one bullet naming its strongest
signal). `bullet_reasons` and `signals_used` are the auditable output and
are NEVER produced by an LLM.

`add_llm_prose` is the single optional, constrained LLM touch: it rewrites
the already-built bullets into one sentence and may not add anything. Any
failure leaves the explanation exactly as built (`template_only=True`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.ranking import SIGNAL_NAMES, RankingExplanation, SignalContribution, SignalScores
from app.llm.client import ChatMessage, LlmProviderError
from app.llm.session import LlmSession
from app.services.ranking.fuse import FusionResult

_PHRASES: dict[str, Callable[[float], str]] = {
    "semantic_doc": lambda v: f"strong document-level similarity to the seed ({v:.2f})",
    "semantic_chunk": lambda v: f"passage-level content overlap with the seed ({v:.2f})",
    "problem_sim": lambda v: f"addresses a closely related research problem ({v:.2f})",
    "method_sim": lambda v: f"uses related methods ({v:.2f})",
    "dataset_overlap": lambda v: f"shares datasets named in the seed's profile ({v:.2f})",
    "citation": lambda v: f"linked to the seed in the citation graph ({v:.2f})",
    "recency": lambda v: f"recent relative to the seed ({v:.2f})",
    "publisher": lambda v: "from a publisher you prefer",
}

_SYSTEM_PROMPT = (
    "Rewrite the given ranking reasons as ONE plain-English sentence. Do not "
    "add any fact, number, dataset, method, or claim that is not already in "
    "the reasons. Output only the sentence."
)


def contributions(fusion: FusionResult, signals: SignalScores) -> list[SignalContribution]:
    """What each computed signal added to the fused score, largest first
    (ties in signal order)."""
    available = signals.available()
    rows = [
        SignalContribution(
            signal=name,
            value=round(available[name], 4),
            weight=round(fusion.effective_weights.get(name, 0.0), 4),
            contribution=round(fusion.effective_weights.get(name, 0.0) * available[name], 4),
        )
        for name in fusion.used_signals
    ]
    return sorted(rows, key=lambda c: (-c.contribution, SIGNAL_NAMES.index(c.signal)))


def build_explanation(signals: SignalScores, *, threshold: float, fusion: FusionResult | None = None) -> RankingExplanation:
    available = signals.available()
    strong = sorted(
        ((name, value) for name, value in available.items() if value >= threshold),
        key=lambda item: (-item[1], SIGNAL_NAMES.index(item[0])),
    )

    if strong:
        bullets = [_PHRASES[name](value) for name, value in strong]
        signals_used = [name for name, _ in strong]
    elif available:
        top_name, top_value = max(available.items(), key=lambda item: (item[1], -SIGNAL_NAMES.index(item[0])))
        bullets = [f"ranked mainly on {top_name.replace('_', ' ')} ({top_value:.2f})"]
        signals_used = [top_name]
    else:
        bullets, signals_used = [], []

    prose = "; ".join(bullets) + "." if bullets else "No strong ranking signal; low-confidence match."
    return RankingExplanation(
        bullet_reasons=bullets,
        prose=prose,
        signals_used=signals_used,
        template_only=True,
        contributions=contributions(fusion, signals) if fusion is not None else [],
        missing_signals=list(fusion.missing_signals) if fusion is not None else [],
    )


async def add_llm_prose(explanation: RankingExplanation, *, session: LlmSession) -> RankingExplanation:
    if not explanation.bullet_reasons:
        return explanation
    messages = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content="Reasons: " + "; ".join(explanation.bullet_reasons)),
    ]
    try:
        result = await session.client.chat(api_key=session.api_key, model=session.model, messages=messages)
    except LlmProviderError:
        return explanation
    prose = result.content.strip()
    if not prose:
        return explanation
    return explanation.model_copy(update={"prose": prose, "template_only": False})
