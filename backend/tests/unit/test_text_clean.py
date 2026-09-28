"""Paper and API text cleaning (remediation Phase 6), on shapes taken from
the real dev database."""

from __future__ import annotations

import pytest

from app.services.normalize.text import clean_abstract, clean_text


@pytest.mark.parametrize(
    "raw",
    [
        "Abstract The MOVE UP behavioral activation program, consisting of 32 sessions.",
        "Abstract: Deep fake is a rapidly growing concern in society.",
        ":  Facial recognition has been exploited in solving problems.",
        "Abstract�In modern educational institutions, attendance tracking plays a role.",
        "ABSTRACT In modern educational environments, maintaining records is vital.",
        "Abstract\nThis paper investigates the effectiveness of face recognition.",
        "\n \n Artificial intelligence (AI) is reshaping marketing.\n",
    ],
)
def test_the_label_and_stray_punctuation_in_front_go(raw: str) -> None:
    cleaned = clean_abstract(raw)
    assert cleaned[0].isupper() and not cleaned.lower().startswith("abstract")
    assert "�" not in cleaned and "\n" not in cleaned and " " not in cleaned


def test_an_abstract_about_abstraction_keeps_its_first_word() -> None:
    assert clean_abstract("Abstract reasoning remains hard for language models.").startswith("Abstract reasoning")
    assert clean_abstract("Summary statistics of 40 cohorts are pooled here.").startswith("Summary statistics")
    assert clean_abstract("Abstract Meaning Representation parsing maps text to graphs.").startswith("Abstract Meaning")
    assert clean_abstract("Abstract Computational pathology has witnessed progress.").startswith("Computational pathology")


def test_the_publisher_block_and_its_garbled_copies_are_cut() -> None:
    # pap_d8c7ee81...: a PDF whose text layer printed the licence twice over
    raw = (
        "Abstract\nThis paper investigates face recognition for attendance. The ResNet-50 model achieved precision "
        "and recall rate of 96% and 93% respectively. This study suggests directions for enhancing system reliability "
        "and accuracy. © 2025 The Authors. Published by ELSEVIER B.V.\n�� 22002255 TThhee AAuutthhoorrss.. "
        "PPuubblliisshheedd bbyy EElLseSvEiVerI EBR.V .B.V.\nT h i s i s a n op e n a c ce s s a r t i c l e\n"
        "Peer-review under responsibility of the scientific committee\nKeywords: Automated attendance, face recognition"
    )
    assert clean_abstract(raw) == (
        "This paper investigates face recognition for attendance. The ResNet-50 model achieved precision and recall "
        "rate of 96% and 93% respectively. This study suggests directions for enhancing system reliability and accuracy."
    )


@pytest.mark.parametrize(
    ("raw", "ends"),
    [
        ("A system of Haar cascades detects faces and records attendance in class. Keywords: face detection, LBPH", "records attendance in class."),
        ("Imaging mass spectrometry maps molecules across tissue sections at scale. � 2019 The Authors. Mass Spectrometry Reviews", "at scale."),
        ("We study retrieval over long documents and report gains on three tasks. Copyright 2021 IEEE. All rights reserved.", "on three tasks."),
    ],
)
def test_keyword_lists_and_copyright_lines_end_the_abstract(raw: str, ends: str) -> None:
    assert clean_abstract(raw).endswith(ends)


def test_markup_and_entities_become_text() -> None:
    raw = "The front-end performs <inline-formula><tex-math>8x</tex-math></inline-formula> compression &amp; quantization."
    assert clean_abstract(raw) == "The front-end performs 8x compression & quantization."


def test_undecodable_characters_are_read_from_their_neighbours() -> None:
    assert clean_text("the proposed circuit�without retraining") == "the proposed circuit—without retraining"
    assert clean_text("have been developed [3�6]") == "have been developed [3–6]"
    assert clean_text("the model�s accuracy") == "the model’s accuracy"


def test_line_breaks_ligatures_and_hyphenation_are_repaired() -> None:
    assert clean_text("recog-\nnition of ﬁne-grained\n faces") == "recognition of fine-grained faces"
    assert clean_text("state-of-the-art") == "state-of-the-art"  # a real hyphen stays


def test_a_name_inside_a_sentence_loses_only_a_sentence_case_capital() -> None:
    from app.services.normalize.text import in_sentence

    assert in_sentence("Dense retrieval with reranking") == "dense retrieval with reranking"
    assert in_sentence("Principal component analysis (PCA)") == "principal component analysis (PCA)"
    assert in_sentence("Fine-tuning") == "fine-tuning"
    # written with capitals of its own, or a single word that may be a name: as written
    for name in ("ResNet-50", "BM25", "Python", "Transfer learning with BERT"):
        assert in_sentence(name) == name
