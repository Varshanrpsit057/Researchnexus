from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domain.candidate import CandidateSource
from app.external.arxiv_client import ArxivClient
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse
from app.services.normalize.canonical import to_normalized

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2005.11401v2</id>
    <published>2020-05-22T17:37:21Z</published>
    <title>Retrieval-Augmented Generation for
      Knowledge-Intensive NLP Tasks</title>
    <summary>  We propose RAG, a general-purpose fine-tuning recipe.  </summary>
    <author><name>Patrick Lewis</name></author>
    <author><name>Ethan Perez</name></author>
    <arxiv:doi>10.5555/abc.123</arxiv:doi>
    <arxiv:journal_ref>NeurIPS 2020</arxiv:journal_ref>
    <link href="http://arxiv.org/abs/2005.11401v2" rel="alternate" type="text/html"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <published>2021-01-01T00:00:00Z</published>
    <title>A Preprint Only Paper</title>
    <summary>No journal ref here.</summary>
    <author><name>Jane Doe</name></author>
    <link href="http://arxiv.org/abs/2101.00001v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

_EMPTY_ATOM = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def _client(text: str) -> ArxivClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "export.arxiv.org" in str(request.url)
        return httpx.Response(200, text=text)

    return ArxivClient(ExternalHttpClient(transport=httpx.MockTransport(handler)))


def test_parses_entries_into_raw_records() -> None:
    records = asyncio.run(_client(_ATOM).search("retrieval augmented generation", max_results=10))
    assert len(records) == 2
    first = records[0]
    assert first.source == CandidateSource.ARXIV
    assert first.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    assert first.abstract == "We propose RAG, a general-purpose fine-tuning recipe."
    assert first.authors == ["Patrick Lewis", "Ethan Perez"]
    assert first.year == 2020
    # the client returns the RAW id; canonicalisation strips prefix + version
    assert first.arxiv_id == "http://arxiv.org/abs/2005.11401v2"
    assert to_normalized(first).external_ids["arxiv"] == "2005.11401"
    assert first.doi == "10.5555/abc.123"
    assert first.venue == "NeurIPS 2020"
    assert first.is_preprint is False


def test_entry_without_journal_ref_is_a_preprint() -> None:
    records = asyncio.run(_client(_ATOM).search("q", max_results=10))
    assert records[1].is_preprint is True
    assert records[1].venue is None


def test_empty_feed_returns_empty_list() -> None:
    assert asyncio.run(_client(_EMPTY_ATOM).search("q", max_results=10)) == []


def test_malformed_xml_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client("<feed><entry></not-closed").search("q", max_results=10))
