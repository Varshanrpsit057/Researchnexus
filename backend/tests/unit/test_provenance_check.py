from __future__ import annotations

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.profile import ProvenanceStatus
from app.llm.prompts.profile_v1 import ExtractedField, ExtractedList
from app.services.profile.provenance_check import resolve_field, resolve_list


def _chunk(text: str, char_start: int = 0, section: str = "Abstract") -> PaperChunk:
    return PaperChunk(
        chunk_id=f"chk_{char_start}",
        paper_id="pap_1",
        section=section,
        section_order=0,
        page=1,
        char_start=char_start,
        char_end=char_start + len(text),
        kind=ChunkKind.ABSTRACT,
        text=text,
        token_count=len(text.split()),
    )


def test_exact_quote_match_is_verified_with_precise_offsets() -> None:
    chunk = _chunk("The problem addressed is catastrophic forgetting in continual learning.")
    field = resolve_field("pap_1", ExtractedField(value="catastrophic forgetting", quote="catastrophic forgetting"), [chunk])
    assert field.status == ProvenanceStatus.VERIFIED
    assert field.source_span is not None
    idx = chunk.text.find("catastrophic forgetting")
    assert field.source_span.char_start == chunk.char_start + idx
    assert field.source_span.char_end == chunk.char_start + idx + len("catastrophic forgetting")
    assert field.source_span.section == "Abstract"


def test_quote_with_extra_whitespace_still_matches_via_fuzzy_path() -> None:
    chunk = _chunk("We evaluate on the   SQuAD    dataset for question answering.")
    field = resolve_field("pap_1", ExtractedField(value="SQuAD", quote="SQuAD dataset for question answering"), [chunk])
    assert field.status == ProvenanceStatus.VERIFIED
    assert field.source_span is not None


def test_fabricated_quote_not_in_any_chunk_is_unverified() -> None:
    chunk = _chunk("This paper proposes a new transformer architecture.")
    field = resolve_field("pap_1", ExtractedField(value="quantum computing", quote="uses quantum computing hardware"), [chunk])
    assert field.status == ProvenanceStatus.UNVERIFIED
    assert field.source_span is None


def test_missing_quote_is_unverified_but_value_is_kept() -> None:
    chunk = _chunk("Some paper text.")
    field = resolve_field("pap_1", ExtractedField(value="a claim with no quote", quote=None), [chunk])
    assert field.status == ProvenanceStatus.UNVERIFIED
    assert field.value == "a claim with no quote"


def test_blank_quote_is_unverified() -> None:
    chunk = _chunk("Some paper text.")
    field = resolve_field("pap_1", ExtractedField(value="x", quote="   "), [chunk])
    assert field.status == ProvenanceStatus.UNVERIFIED


def test_quote_found_in_second_chunk_not_first() -> None:
    chunk1 = _chunk("Introductory remarks with nothing relevant.", char_start=0, section="Introduction")
    chunk2 = _chunk("We use the BERT model as our backbone.", char_start=100, section="Method")
    field = resolve_field("pap_1", ExtractedField(value="BERT", quote="BERT model as our backbone"), [chunk1, chunk2])
    assert field.status == ProvenanceStatus.VERIFIED
    assert field.source_span is not None
    assert field.source_span.section == "Method"


def test_resolve_list_maps_over_items_and_drops_blank_values() -> None:
    chunk = _chunk("We use BERT and RoBERTa in our experiments.")
    extracted = ExtractedList(
        items=[
            ExtractedField(value="BERT", quote="We use BERT"),
            ExtractedField(value="   ", quote=None),
            ExtractedField(value="RoBERTa", quote="RoBERTa"),
        ]
    )
    result = resolve_list("pap_1", extracted, [chunk])
    assert [f.value for f in result.items] == ["BERT", "RoBERTa"]
    assert all(f.status == ProvenanceStatus.VERIFIED for f in result.items)
