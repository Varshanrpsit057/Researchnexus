from __future__ import annotations

from app.services.trail.verify_span import find_span, verify_quote_in_text


def test_exact_substring_is_verified() -> None:
    text = "We show that our method reduces hallucination on open-domain QA."
    assert verify_quote_in_text("reduces hallucination on open-domain QA", text) is True


def test_whitespace_and_case_differences_still_verify() -> None:
    text = "We  show that   our method\nreduces hallucination."
    assert verify_quote_in_text("our method reduces hallucination", text) is True


def test_an_invented_quote_does_not_verify() -> None:
    text = "This paper studies retrieval-augmented generation."
    assert verify_quote_in_text("this paper achieves state of the art on ImageNet", text) is False


def test_empty_quote_or_text_does_not_verify() -> None:
    assert verify_quote_in_text("", "some text") is False
    assert verify_quote_in_text("some quote", "") is False


def test_find_span_returns_offsets_for_an_exact_hit() -> None:
    text = "Intro sentence. The dataset used is Natural Questions. More text."
    span = find_span("Natural Questions", text, paper_id="pap_x")
    assert span is not None
    assert span.paper_id == "pap_x"
    assert text[span.char_start : span.char_end] == "Natural Questions"
    assert span.quote == "Natural Questions"


def test_find_span_none_when_absent() -> None:
    assert find_span("absent phrase", "totally different text", paper_id="pap_x") is None
