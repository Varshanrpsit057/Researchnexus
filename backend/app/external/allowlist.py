"""SSRF control for the external scholarly-API layer (Architecture §1.1 row
H, §7, §22): the backend only ever reaches this fixed set of hosts over
HTTPS, never a user- or document-supplied URL. Every outbound request in
app/external/* passes through `assert_allowed` first.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_HOSTS = frozenset(
    {
        "export.arxiv.org",
        "arxiv.org",
        "api.openalex.org",
        "api.semanticscholar.org",
        "api.crossref.org",
        "api.unpaywall.org",
        "api.core.ac.uk",
        "dblp.org",
        "www.ebi.ac.uk",  # Europe PMC REST API
    }
)


class DisallowedHost(Exception):
    """Raised when a URL's scheme is not HTTPS or its host is not in the
    fixed allowlist. This is a hard security boundary -- never widened at
    runtime or from configuration."""

    def __init__(self, message: str, host: str | None = None) -> None:
        super().__init__(message)
        self.host = host


def assert_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise DisallowedHost(f"scheme not allowed (HTTPS only): {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise DisallowedHost(f"host not in allowlist: {host!r}")


# Full text may be downloaded from any public HTTPS host that a scholarly
# API names as an open-access copy of a paper (the reader's decision,
# 2026-10-02 -- a fixed list of hosts left most papers without their text:
# their open copies sit on university repositories and small journals'
# sites). What stays refused is anything that isn't the public web: plain
# HTTP, a bare name, a private or reserved address, and a name that resolves
# to one (checked again on every redirect hop). The download itself is
# bounded elsewhere: a size cap, and it must really be a PDF.
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".intranet", ".lan", ".home", ".corp", ".arpa")

# hosts known to serve open-access copies (kept for the record of where full
# text usually comes from; every public host is now allowed)
_FULLTEXT_HOSTS = frozenset(
    {
        "arxiv.org",
        "export.arxiv.org",
        "europepmc.org",
        "www.ebi.ac.uk",
        "core.ac.uk",
        "doi.org",
    }
)


def _public_name(host: str) -> bool:
    if not host or host == "localhost" or "." not in host or host.endswith(_PRIVATE_SUFFIXES):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a name, not an address: resolved when it is fetched


def fulltext_host_allowed(url: str) -> bool:
    """A URL full text may be fetched from, by its form: HTTPS, and a public
    host (not a bare name, a private name or a non-public address)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    return _public_name((parsed.hostname or "").lower())


def _resolves_publicly(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addresses = {str(info[4][0]).split("%", 1)[0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


def assert_fulltext_allowed(url: str, *, resolve: bool = True) -> None:
    """Refuse a URL that isn't public. `resolve` also checks every address
    the name resolves to (a public-looking name for a private address is
    refused); it is skipped only when no real network is used."""
    host = (urlparse(url).hostname or "").lower() or None
    if not fulltext_host_allowed(url) or (resolve and host is not None and not _resolves_publicly(host)):
        raise DisallowedHost(f"not a public full-text host: {host!r}", host=host)


