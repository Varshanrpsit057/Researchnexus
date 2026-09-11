from __future__ import annotations

from app.domain.comparison import Comparison, ComparisonCell, ComparisonRow, ComparisonSchema
from app.domain.profile import SourceSpan


def test_cell_has_evidence_only_when_text_and_span_present() -> None:
    empty = ComparisonCell(column="method")
    assert empty.has_evidence is False
    grounded = ComparisonCell(
        column="method", text="dense retrieval",
        span=SourceSpan(paper_id="p1", quote="we use dense retrieval"), claim_id="clm_1",
    )
    assert grounded.has_evidence is True


def test_api_dict_flattens_schema_to_column_list() -> None:
    comp = Comparison(
        comparison_id="cmp_1",
        workspace_id="ws_1",
        column_schema=ComparisonSchema(columns=["method", "dataset"], generated_by="deterministic_union"),
        paper_ids=["p1"],
        rows=[
            ComparisonRow(
                paper_id="p1",
                cells={
                    "method": ComparisonCell(column="method", text="bm25", span=SourceSpan(paper_id="p1", quote="bm25"), claim_id="clm_1"),
                    "dataset": ComparisonCell(column="dataset"),
                },
            )
        ],
        coverage=0.5,
    )
    d = comp.api_dict()
    assert d["schema"] == ["method", "dataset"]
    assert d["generated_by"] == "deterministic_union"
    assert d["rows"][0]["cells"]["method"]["text"] == "bm25"
    assert d["rows"][0]["cells"]["dataset"]["text"] is None
    assert d["coverage"] == 0.5 and d["decontext_eval"] is None
