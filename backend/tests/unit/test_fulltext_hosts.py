"""Where full text may be downloaded from: any public HTTPS host a scholarly
API names as an open-access copy (the reader's decision, 2026-10-02; it was a
fixed list in remediation Phase 7) -- never the private network."""

from __future__ import annotations

import socket

import pytest

from app.external import allowlist
from app.external.allowlist import (
    DisallowedHost,
    assert_allowed,
    assert_fulltext_allowed,
    fulltext_host_allowed,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/pdf/2005.11401",
        "https://www.mdpi.com/2076-3417/13/5/3120/pdf",
        "https://bmcmedicine.biomedcentral.com/counter/pdf/10.1186/s12916-020-01.pdf",
        "https://doi.org/10.3390/app13053120",
        # open access on a university repository or a small journal: allowed now
        "https://jicet.org/index.php/article/download/1/2",
        "https://ir.uitm.edu.my/id/eprint/12345/1/paper.pdf",
        "https://core.ac.uk/download/pdf/123456.pdf",
    ],
)
def test_public_https_hosts_are_allowed(url: str) -> None:
    assert fulltext_host_allowed(url)
    assert_fulltext_allowed(url, resolve=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://arxiv.org/pdf/2005.11401",  # HTTPS only
        "https://localhost/secret.pdf",
        "https://intranet/paper.pdf",  # a bare name
        "https://files.corp/paper.pdf",
        "https://printer.local/paper.pdf",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://10.0.0.5/paper.pdf",
        "https://192.168.1.10/paper.pdf",
        "https://127.0.0.1/paper.pdf",
        "https://[::1]/paper.pdf",
    ],
)
def test_the_private_network_is_refused(url: str) -> None:
    assert not fulltext_host_allowed(url)
    with pytest.raises(DisallowedHost):
        assert_fulltext_allowed(url, resolve=False)


def test_a_public_name_that_resolves_to_a_private_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(host: str, *_a: object, **_k: object) -> list[tuple]:
        address = {"looks-public.example.org": "10.1.2.3", "really-public.example.org": "93.184.216.34"}[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(allowlist.socket, "getaddrinfo", resolve)
    with pytest.raises(DisallowedHost):
        assert_fulltext_allowed("https://looks-public.example.org/paper.pdf")
    assert_fulltext_allowed("https://really-public.example.org/paper.pdf")


def test_the_metadata_allowlist_is_not_widened() -> None:
    # search APIs stay a fixed list: only full-text downloads reach the public web
    with pytest.raises(DisallowedHost):
        assert_allowed("https://www.mdpi.com/2076-3417/13/5/3120/pdf")
    assert_allowed("https://api.unpaywall.org/v2/10.1/x")
    assert_allowed("https://api.core.ac.uk/v3/search/works")
