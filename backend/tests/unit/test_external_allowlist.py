from __future__ import annotations

import pytest

from app.external.allowlist import DisallowedHost, assert_allowed


@pytest.mark.parametrize(
    "url",
    [
        "https://export.arxiv.org/api/query?search_query=all:rag",
        "https://arxiv.org/abs/2301.00001",
        "https://api.openalex.org/works?search=rag",
        "https://api.semanticscholar.org/graph/v1/paper/search?query=rag",
        "https://api.crossref.org/works/10.1109/BigData62323.2024.10825310",
        "https://API.OpenAlex.ORG/works",  # host match is case-insensitive
    ],
)
def test_allowed_hosts_pass(url: str) -> None:
    assert_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/steal",
        "https://openalex.org.evil.com/works",  # suffix trick
        "https://api.openalex.com/works",  # wrong TLD
        "https://semanticscholar.org/paper",  # bare host not in list
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF target
        "https://localhost:8000/",
    ],
)
def test_disallowed_hosts_raise(url: str) -> None:
    with pytest.raises(DisallowedHost):
        assert_allowed(url)


def test_non_https_scheme_is_rejected() -> None:
    with pytest.raises(DisallowedHost):
        assert_allowed("http://api.openalex.org/works")


def test_url_without_host_is_rejected() -> None:
    with pytest.raises(DisallowedHost):
        assert_allowed("not-a-url")
