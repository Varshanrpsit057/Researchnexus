"""Profile refinement (remediation Phase 6), on shapes from real profiles in
the dev database: never a claim the paper doesn't make."""

from __future__ import annotations

from app.domain.profile import (
    ProfileField,
    ProfileList,
    ProvenanceStatus,
    ReportedValue,
    ResearchProfile,
    SourceSpan,
)
from app.services.profile.refine import item_keys, refine_profile, reported_values, summarize

V = ProvenanceStatus.VERIFIED


def _f(value: str, quote: str | None = None, status: ProvenanceStatus = V, reported: ReportedValue | None = None) -> ProfileField:
    span = SourceSpan(paper_id="p", quote=quote) if quote else None
    return ProfileField(value=value, source_span=span, status=status if quote or status is not V else V, reported_value=reported)


def _profile(**kw: object) -> ResearchProfile:
    base: dict[str, object] = {
        "profile_id": "prof",
        "paper_id": "p",
        "title": "T",
        "abstract": "We propose a thing.",
        "domain": ProfileField(value=""),
        "research_problem": ProfileField(value=""),
    }
    return ResearchProfile.model_validate(base | kw)


def _metrics(*items: ProfileField) -> ProfileList:
    return ProfileList(items=list(items))


# --- metric values ---------------------------------------------------------------


def test_a_metric_gets_the_value_written_beside_it_in_its_evidence() -> None:
    p = refine_profile(_profile(evaluation_metrics=_metrics(_f("Recognition accuracy", "reveal an impressive recognition accuracy of 95.83%"))))
    [m] = p.evaluation_metrics.items
    assert m.reported_value == ReportedValue(text="95.83%", status=V)


def test_respectively_gives_each_metric_its_own_value() -> None:
    quote = "achieved precision and recall rate of 96% and 93% respectively"
    p = refine_profile(_profile(evaluation_metrics=_metrics(_f("precision", quote), _f("recall", quote))))
    assert [(m.value, m.reported_value.text if m.reported_value else None) for m in p.evaluation_metrics.items] == [
        ("Precision", "96%"),
        ("Recall", "93%"),
    ]


def test_an_ambiguous_or_missing_value_is_never_guessed() -> None:
    assert reported_values(["accuracy", "F1"], "accuracy and F1 improved to 91.2% and 0.88 over the baseline") == {}
    assert reported_values(["F1 score"], "we evaluate every model with the F1 score on held-out folds") == {}
    # a count or a model size is not a result
    assert reported_values(["accuracy"], "accuracy on 1200 images of 50 students") == {}
    p = refine_profile(_profile(evaluation_metrics=_metrics(_f("Accuracy", "accuracy of 91%", status=ProvenanceStatus.UNVERIFIED))))
    assert p.evaluation_metrics.items[0].reported_value is None  # evidence not found in the paper: no value either


def test_names_values_and_acronyms_are_matched_either_side() -> None:
    assert reported_values(["Top-1 accuracy"], "reaching 81.3% top-1 accuracy on ImageNet") == {"Top-1 accuracy": "81.3%"}
    assert reported_values(["Exact Match (EM)"], "improves EM of 44.5 to 47.1") == {}
    assert reported_values(["Exact Match (EM)"], "an EM of 44.5% on NQ") == {"Exact Match (EM)": "44.5%"}
    assert reported_values(["Latency"], "latency drops to 12 ms per frame") == {"Latency": "12 ms"}


def test_a_range_stays_a_range_and_a_series_has_no_single_value() -> None:
    # both from real profiles in the dev database
    assert reported_values(["Recognition accuracy"], "has high recognition accuracy (approximately 95%-97%)") == {
        "Recognition accuracy": "approximately 95%-97%"
    }
    series = "Completion of activity and diet logs followed a similar pattern (34.9%, 56.2%, and 72.7%, respectively)"
    assert reported_values(["Completion of activity and diet logs (%)"], series) == {}
    # a value followed by another metric's is not a series
    assert reported_values(["Accuracy"], "an accuracy of 91.2% and an F1 of 0.88") == {"Accuracy": "91.2%"}


def test_a_value_from_extraction_counts_only_when_its_evidence_says_it() -> None:
    claimed = _f("Accuracy", "the system reaches an accuracy of 95.8%", reported=ReportedValue(text="95.8 %", status=V))
    invented = _f("F1", "the system reaches an accuracy of 95.8%", reported=ReportedValue(text="0.93", status=V))
    p = refine_profile(_profile(evaluation_metrics=_metrics(claimed, invented)))
    assert [m.reported_value for m in p.evaluation_metrics.items] == [
        ReportedValue(text="95.8 %", status=V),
        ReportedValue(text="0.93", status=ProvenanceStatus.UNVERIFIED),
    ]
    # extraction records a value unchecked; its evidence decides
    fresh = _f("Recall", "with a recall of 93%", reported=ReportedValue(text="93%"))
    assert refine_profile(_profile(evaluation_metrics=_metrics(fresh))).evaluation_metrics.items[0].reported_value == ReportedValue(
        text="93%", status=V
    )


# --- how values read ---------------------------------------------------------------


def test_names_read_in_sentence_case_without_a_full_stop_and_statements_end() -> None:
    p = refine_profile(
        _profile(
            domain=_f("modern educational environments / smart attendance systems", "x"),
            research_problem=_f("traditional attendance methods are often plagued by inefficiencies", "x"),
            methods=_metrics(_f("Student enrollment through multi-angle facial image captures.", "x"), _f("image\ndataset aug-\nmentation", "x")),
            models=_metrics(_f("face-api.js", "x"), _f("word2vec", "x"), _f("k-means clustering", "x")),
            findings=_metrics(_f("the proposed framework improves recognition accuracy", "x")),
        )
    )
    assert p.domain.value == "Modern educational environments / smart attendance systems"
    assert p.research_problem.value == "Traditional attendance methods are often plagued by inefficiencies."
    assert [m.value for m in p.methods.items] == ["Student enrollment through multi-angle facial image captures", "Image dataset augmentation"]
    assert [m.value for m in p.models.items] == ["face-api.js", "word2vec", "k-means clustering"]
    assert p.findings.items[0].value == "The proposed framework improves recognition accuracy."


def test_a_users_own_edits_stay_as_written() -> None:
    edited = ProfileField(value="lowercase on purpose.", status=ProvenanceStatus.USER_EDITED)
    p = refine_profile(_profile(methods=_metrics(edited), research_problem=edited))
    assert p.methods.items[0].value == p.research_problem.value == "lowercase on purpose."


# --- one thing, listed once ----------------------------------------------------------


def test_near_identical_items_merge_keeping_the_evidenced_one() -> None:
    assert item_keys("ResNet-50 model") & item_keys("ResNet-50")
    assert item_keys("Principal Component Analysis (PCA)") & item_keys("PCA")
    assert not item_keys("Face detection") & item_keys("Face recognition")
    assert item_keys("Long Short-Term Memory (LSTM)") & item_keys("LSTM")
    assert item_keys("Convolutional Neural Networks (CNNs)") & item_keys("CNN")
    # a bracketed qualifier is not another name for the thing
    assert not item_keys("Transfer learning (VGG16)") & item_keys("VGG16")
    assert not item_keys("Precision (ResNet-50)") & item_keys("ResNet-50")
    p = refine_profile(
        _profile(models=_metrics(_f("ResNet-50", status=ProvenanceStatus.UNVERIFIED), _f("ResNet-50 model", "the ResNet-50 model")))
    )
    [m] = p.models.items
    assert m.status is V and m.value == "ResNet-50 model"  # the copy with evidence


def test_an_item_under_a_specific_heading_leaves_the_vaguer_ones() -> None:
    p = refine_profile(
        _profile(
            keywords=["computer vision"],
            subdomains=_metrics(_f("Face recognition technology", "x")),
            models=_metrics(_f("face-api.js", "x")),
            algorithms=_metrics(_f("Face recognition", "x")),
            methods=_metrics(_f("face-api.js", "x"), _f("Real-time recognition in the browser", "x")),
            cited_methods=_metrics(_f("RFID", "x"), _f("Real-time recognition in the browser", "x")),
            important_entities=_metrics(_f("face-api.js", "x"), _f("RFID", "x"), _f("Computer Vision", "x"), _f("Excel file", "x")),
        )
    )
    assert [i.value for i in p.methods.items] == ["Real-time recognition in the browser"]
    assert [i.value for i in p.cited_methods.items] == ["RFID"]
    assert [i.value for i in p.important_entities.items] == ["Excel file"]
    # the field the paper is in isn't a thing it used: the subdomain stays
    assert [i.value for i in p.subdomains.items] == ["Face recognition technology"]


def test_the_same_metric_with_two_reported_results_is_two_results() -> None:
    q1, q2 = "an accuracy of 95.8% in daylight", "an accuracy of 81.0% under dim light"
    p = refine_profile(_profile(evaluation_metrics=_metrics(_f("Accuracy", q1), _f("Accuracy", q2), _f("accuracy", q1))))
    assert [m.reported_value.text for m in p.evaluation_metrics.items if m.reported_value] == ["95.8%", "81.0%"]


# --- the abstract and its summary -----------------------------------------------------

CLASSNET = (
    ":  Facial recognition has been exploited in solving problems in diverse sectors. In the education sector, "
    "traditional attendance procedures are often laborious and ineffective. This paper addresses these challenges by "
    "proposing a novel intelligent attendance system specifically designed for classrooms. The proposed system detects "
    "faces from the captured image and improves their quality through a super-resolution method. Experiments performed "
    "on a challenging dataset reveal an impressive recognition accuracy of 95.83%, a 16% enhancement over existing methods. "
    "These results highlight the effectiveness of the proposed system."
)


def test_the_summary_is_the_papers_own_sentences_on_what_it_does_and_found() -> None:
    p = refine_profile(_profile(abstract=CLASSNET))
    assert p.abstract.startswith("Facial recognition has been exploited")
    assert p.summary == (
        "This paper addresses these challenges by proposing a novel intelligent attendance system specifically designed "
        "for classrooms. Experiments performed on a challenging dataset reveal an impressive recognition accuracy of 95.83%, "
        "a 16% enhancement over existing methods."
    )
    assert all(sentence in p.abstract for sentence in p.summary.split(". "))  # verbatim
    assert summarize("We study X. It works.") == "We study X. It works."  # short: the abstract is its summary


def test_text_that_is_not_the_abstract_is_not_summarised_as_one() -> None:
    p = refine_profile(_profile(abstract="C. ORGANIZATIONOFTHEPAPER This paper discusses agentic AI."), abstract_found=False)
    assert p.abstract_found is False and p.summary == ""


def test_refining_twice_changes_nothing() -> None:
    quote = "achieved precision and recall rate of 96% and 93% respectively"
    once = refine_profile(
        _profile(
            abstract=CLASSNET,
            evaluation_metrics=_metrics(_f("precision", quote), _f("recall", quote)),
            methods=_metrics(_f("image dataset augmentation.", "x"), _f("Image dataset augmentation", "x")),
            findings=_metrics(_f("it works", "x")),
        )
    )
    assert refine_profile(once) == once
