"""SSRF control for the external scholarly-API layer (Architecture §1.1 row
H, §7, §22): the backend only ever reaches this fixed set of hosts over
HTTPS, never a user- or document-supplied URL. Every outbound request in
app/external/* passes through `assert_allowed` first.
"""

from __future__ import annotations

from urllib.parse import urlparse

_ALLOWED_HOSTS = frozenset(
    {
        "export.arxiv.org",
        "arxiv.org",
        "api.openalex.org",
        "api.semanticscholar.org",
        "api.crossref.org",
        "www.ebi.ac.uk",  # Europe PMC REST API
    }
)


class DisallowedHost(Exception):
    """Raised when a URL's scheme is not HTTPS or its host is not in the
    fixed allowlist. This is a hard security boundary -- never widened at
    runtime or from configuration."""


def assert_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise DisallowedHost(f"scheme not allowed (HTTPS only): {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise DisallowedHost(f"host not in allowlist: {host!r}")
