from __future__ import annotations

from app.domain.citation import NOT_AVAILABLE
from app.services.citations.formatter import build_formatted, csl_key

_CSL_CONF = {
    "type": "paper-conference",
    "title": "Empowering Meta-Analysis: Leveraging Large Language Models for Scientific Synthesis",
    "author": [
        {"family": "Ahad", "given": "Jawad Ibn"},
        {"family": "Sultan", "given": "Rifat Mahmud"},
        {"family": "Kaikobad", "given": "Abrar"},
    ],
    "issued": {"date-parts": [[2024]]},
    "container-title": "2024 IEEE International Conference on Big Data (BigData)",
    "DOI": "10.1109/BigData62323.2024.10825310",
}

_CSL_ARXIV = {
    "type": "article",
    "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "author": [{"family": "Lewis", "given": "Patrick"}, {"family": "Perez", "given": "Ethan"}],
    "issued": {"date-parts": [[2020]]},
    "container-title": "arXiv",
    "URL": "https://arxiv.org/abs/2005.11401",
}


def test_apa_two_and_three_authors() -> None:
    apa = build_formatted(_CSL_ARXIV)["apa"]
    assert apa == (
        "Lewis, P., & Perez, E. (2020). Retrieval-Augmented Generation for "
        "Knowledge-Intensive NLP Tasks. arXiv. https://arxiv.org/abs/2005.11401"
    )
    apa3 = build_formatted(_CSL_CONF)["apa"]
    assert apa3 == (
        "Ahad, J. I., Sultan, R. M., & Kaikobad, A. (2024). Empowering "
        "Meta-Analysis: Leveraging Large Language Models for Scientific "
        "Synthesis. 2024 IEEE International Conference on Big Data (BigData). "
        "https://doi.org/10.1109/BigData62323.2024.10825310"
    )


def test_ieee_uses_initials_first_and_optional_number() -> None:
    ieee = build_formatted(_CSL_CONF, number=3)["ieee"]
    assert ieee == (
        '[3] J. I. Ahad, R. M. Sultan, and A. Kaikobad, "Empowering '
        'Meta-Analysis: Leveraging Large Language Models for Scientific '
        'Synthesis," in 2024 IEEE International Conference on Big Data '
        '(BigData), 2024, doi: 10.1109/BigData62323.2024.10825310.'
    )
    # no number -> no leading marker
    assert build_formatted(_CSL_ARXIV)["ieee"].startswith('P. Lewis and E. Perez, "Retrieval-Augmented')


def test_bibtex_key_is_deterministic_and_wellformed() -> None:
    key = csl_key(_CSL_CONF)
    assert key == "ahad2024empowering"
    bib = build_formatted(_CSL_CONF)["bibtex"]
    assert bib.startswith("@inproceedings{ahad2024empowering,")
    assert "  title = {Empowering Meta-Analysis: Leveraging Large Language Models for Scientific Synthesis}," in bib
    assert "  author = {Ahad, Jawad Ibn and Sultan, Rifat Mahmud and Kaikobad, Abrar}," in bib
    assert "  year = {2024}," in bib
    assert "  doi = {10.1109/BigData62323.2024.10825310}," in bib
    assert bib.rstrip().endswith("}")


def test_bibtex_article_type_for_arxiv() -> None:
    bib = build_formatted(_CSL_ARXIV)["bibtex"]
    assert bib.startswith("@article{lewis2020retrieval,")
    assert "journal = {arXiv}," in bib


def test_unresolved_metadata_is_never_guessed() -> None:
    formatted = build_formatted({"type": "article", "title": ""})
    assert formatted == {"apa": NOT_AVAILABLE, "ieee": NOT_AVAILABLE, "bibtex": NOT_AVAILABLE}
    assert build_formatted({}) == {"apa": NOT_AVAILABLE, "ieee": NOT_AVAILABLE, "bibtex": NOT_AVAILABLE}


def test_single_author_and_missing_year() -> None:
    csl = {"type": "article", "title": "A Solo Work", "author": [{"family": "Kim", "given": "Sang"}],
           "container-title": "Journal X"}
    out = build_formatted(csl)
    assert out["apa"] == "Kim, S. (n.d.). A Solo Work. Journal X."
    assert out["ieee"] == 'S. Kim, "A Solo Work," in Journal X.'


def test_formatting_is_deterministic_across_calls() -> None:
    a = build_formatted(_CSL_CONF, number=1)
    b = build_formatted(_CSL_CONF, number=1)
    assert a == b
