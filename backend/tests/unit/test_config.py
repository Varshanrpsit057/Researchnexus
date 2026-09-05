from app.config import Settings


def test_default_limits() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.max_pdf_mb == 30
    assert s.max_pages == 60
    assert s.max_page_chars == 500_000
    assert s.database_url.startswith("sqlite")


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCHNEXUS_MAX_PDF_MB", "5")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.max_pdf_mb == 5
