"""Europe PMC full-text XML (JATS) read into sections (remediation Phase 7)."""

from __future__ import annotations

import pytest

from app.services.fulltext.jats import NotAnArticle, jats_document

ARTICLE = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <abstract><p>We map every neuron in a larva brain.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Introduction</title><p>Brains are wired <xref ref-type="bibr">[1]</xref>in circuits.</p></sec>
    <sec><title>Results</title>
      <p>We found 3016 neurons.</p>
      <fig><label>Fig 1</label><caption><p>Not prose.</p></caption></fig>
      <sec><title>Connection types</title><p>Four types were seen.</p></sec>
    </sec>
  </body>
  <back><ref-list><ref><mixed-citation>Doe J. A study. 2020.</mixed-citation></ref></ref-list></back>
</article>"""


def test_the_article_is_read_section_by_section() -> None:
    text, sections = jats_document(ARTICLE)
    assert [s.title for s in sections] == ["Abstract", "Introduction", "Results", "Connection types", "References"]
    for s in sections:
        assert text[s.char_start : s.char_end].startswith(s.title)
    intro = text[sections[1].char_start : sections[1].char_end]
    assert "Brains are wired in circuits." in intro  # a citation marker is not prose
    assert "Not prose" not in text  # nor is a figure
    assert "Doe J. A study. 2020." in text


def test_xml_without_a_body_is_not_an_article() -> None:
    with pytest.raises(NotAnArticle):
        jats_document("<article><front><abstract><p>Only this.</p></abstract></front></article>")


def test_entity_tricks_are_refused() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "xxxx"><!ENTITY y "&x;&x;&x;">]><article><body>&y;</body></article>'
    with pytest.raises(Exception):  # noqa: B017 - defusedxml refuses entity declarations outright
        jats_document(bomb)
