"""Verbatim evidence selection for trail edges (app/services/trail/evidence.py)."""

from __future__ import annotations

import numpy as np

from app.services.trail.evidence import best_sentence, seed_reference_span, sentence_around

ABSTRACT = (
    "Agents are increasingly deployed in enterprise settings. "
    "We propose a planning framework that lets LLM agents decompose goals into tool calls. "
    "Experiments on three benchmarks show large gains. "
    "Code is available."
)


def test_seed_reference_is_found_even_when_the_pdf_squashed_its_spaces() -> None:
    refs = [
        {"raw_text": "[1] A.Turing,ComputingMachineryandIntelligence.Cham,Switzerland: Springer,2009."},
        {"raw_text": "[2] V.Karpukhin et al., DensePassageRetrievalforOpen-DomainQuestionAnswering, EMNLP 2020."},
    ]
    span = seed_reference_span("pap_seed", "Dense Passage Retrieval for Open-Domain Question Answering", refs)
    assert span is not None
    assert span.paper_id == "pap_seed"
    assert span.section == "References"
    assert span.quote == refs[1]["raw_text"]  # verbatim, exactly as the seed's PDF reads


def test_no_reference_match_for_an_unrelated_or_too_short_title() -> None:
    refs = [{"raw_text": "[1] Some Author. A Paper About Protein Folding. Nature, 2019."}]
    assert seed_reference_span("pap_seed", "Dense Passage Retrieval", refs) is None
    assert seed_reference_span("pap_seed", "Survey", [{"raw_text": "[1] A Survey of Everything, 2020."}]) is None
    assert seed_reference_span("pap_seed", "Anything at all here", []) is None


def test_best_sentence_is_a_verbatim_span_of_the_abstract() -> None:
    picked = best_sentence(ABSTRACT, ["LLM agents planning and tool calls"])
    assert picked is not None
    start, end = picked
    assert ABSTRACT[start:end] == "We propose a planning framework that lets LLM agents decompose goals into tool calls."


def test_best_sentence_skips_fragments_and_handles_empty_text() -> None:
    assert best_sentence("", ["anything"]) is None
    assert best_sentence("Code is available.", ["code"]) is None  # a fragment is not a claim


class _AxisEmbedder:
    """Maps a text to the unit axis of the first keyword it mentions."""

    name = "axis-stub"
    dimension = 3
    _KEYS = ("benchmark", "enterprise", "planning")

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), 3), dtype="float32")
        for i, t in enumerate(texts):
            hit = next((k for k, key in enumerate(self._KEYS) if key in t.lower()), None)
            if hit is not None:
                out[i, hit] = 1.0
        return out


def test_best_sentence_uses_the_embedder_when_given() -> None:
    picked = best_sentence(ABSTRACT, ["how well it does on benchmark suites"], embedder=_AxisEmbedder())
    assert picked is not None
    assert ABSTRACT[picked[0] : picked[1]] == "Experiments on three benchmarks show large gains."


def test_sentence_around_expands_a_match_to_its_sentence() -> None:
    idx = ABSTRACT.index("three benchmarks")
    start, end = sentence_around(ABSTRACT, idx, idx + len("three benchmarks"))
    assert ABSTRACT[start:end] == "Experiments on three benchmarks show large gains."
