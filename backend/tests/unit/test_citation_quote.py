"""The passage shown for a claim is the part of its chunk that supports it,
verbatim, with the supporting sentence marked (remediation Phases 11/13)."""

from __future__ import annotations

from app.services.citations.quote import quote_window

FILLER = " ".join(f"Sentence {i} discusses the history of face detection research in general terms." for i in range(12))
SUPPORT = "State-of-the-art systems report accuracy rates of approximately 96% on classroom footage."
CHUNK = f"{FILLER} {SUPPORT} After that, the authors describe their data collection in detail."


def test_the_window_holds_the_sentence_the_claim_rests_on_even_past_the_old_cut() -> None:
    assert CHUNK.index(SUPPORT) > 700  # the first 700 characters never showed it
    w = quote_window(CHUNK, "Systems report accuracy of approximately 96%.", max_chars=700)
    assert SUPPORT in w.quote
    assert w.quote in CHUNK  # a contiguous, unedited slice
    assert len(w.quote) <= 700
    assert w.highlight is not None and w.quote[w.highlight[0] : w.highlight[1]] == SUPPORT
    assert w.cut_before is True and w.cut_after is False


def test_a_short_passage_is_shown_whole_with_its_supporting_sentence_marked() -> None:
    text = "We used BM25. Dense retrieval reached 58.6 F1 on LitSearch. Results improved."
    w = quote_window(text, "Dense retrieval scored 58.6 F1.", max_chars=700)
    assert w.quote == text and not w.cut_before and not w.cut_after
    assert w.highlight is not None and w.quote[w.highlight[0] : w.highlight[1]] == "Dense retrieval reached 58.6 F1 on LitSearch."


def test_figures_decide_between_otherwise_similar_sentences_and_decimals_do_not_split_them() -> None:
    text = "The model reached 91.2% accuracy on set A. The model reached 93.5% accuracy on set B."
    w = quote_window(text, "accuracy was 93.5%", max_chars=700)
    assert w.highlight is not None and w.quote[w.highlight[0] : w.highlight[1]] == "The model reached 93.5% accuracy on set B."


def test_with_nothing_in_common_the_passage_starts_at_its_beginning() -> None:
    w = quote_window(CHUNK, "zebras", max_chars=100)
    assert w.quote == CHUNK[:100] and w.highlight is None and w.cut_after and not w.cut_before
