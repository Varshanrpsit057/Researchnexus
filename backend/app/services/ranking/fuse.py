"""Deterministic weighted fusion (Data Model §4; Architecture §3 S9
`fuse.py`).

    fused = Σ_{i in available} (w_i / Σ_{j in available} w_j) * signal_i

Weights are renormalised over the signals that were actually computed, so a
paper with fewer signals is not silently penalised (Architecture §3 S9
failure handling). No LLM, no I/O; equality-comparable output for
reproducibility tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.ranking import SIGNAL_NAMES, RankingWeights, SignalScores

_ROUND = 9


@dataclass(frozen=True)
class FusionResult:
    fused_score: float
    used_signals: list[str]
    missing_signals: list[str]
    effective_weights: dict[str, float]  # renormalised; sums to 1.0 (or empty)


def fuse(signals: SignalScores, weights: RankingWeights) -> FusionResult:
    available = signals.available()
    raw_weights = {name: weights.as_dict()[name] for name in available}
    total_weight = sum(raw_weights.values())

    missing = [name for name in SIGNAL_NAMES if name not in available]

    if total_weight <= 0.0:
        return FusionResult(0.0, [], list(SIGNAL_NAMES), {})

    effective = {name: raw_weights[name] / total_weight for name in available}
    fused = sum(effective[name] * available[name] for name in available)

    return FusionResult(
        fused_score=round(fused, _ROUND),
        used_signals=[name for name in SIGNAL_NAMES if name in available],
        missing_signals=missing,
        effective_weights={name: round(effective[name], _ROUND) for name in available},
    )
