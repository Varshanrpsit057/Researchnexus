"""Writes N small, text-layer PDFs for the multi-upload spec.

Usage: make-upload-pdfs.py <out_dir> <count> <tag>

Each PDF's title carries <tag> and its index, so every run produces files
with new SHA-256 hashes -- the backend deduplicates uploads by hash, and a
reused file would skip the real parse this spec is meant to exercise.
Built with reportlab (the backend's test-only dependency), like the backend's
own ingestion fixtures in backend/tests/fixtures/make_fixtures.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_BODY = (
    "Dense retrieval encodes queries and passages into a shared vector space and "
    "retrieves by nearest-neighbour search. This synthetic paper exists to test "
    "uploading several PDFs into one research workspace at once. "
) * 6


def make_pdf(path: Path, title: str) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, title=title, author="Upload Fixture")
    story = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 12),
        Paragraph("Abstract", styles["Heading2"]),
        Paragraph(_BODY, styles["BodyText"]),
        Paragraph("1 Introduction", styles["Heading2"]),
        Paragraph(_BODY, styles["BodyText"]),
        Paragraph("2 Method", styles["Heading2"]),
        Paragraph(_BODY, styles["BodyText"]),
        Paragraph("References", styles["Heading2"]),
        Paragraph("[1] A. Author. A related paper. Conf. on Testing, 2020.", styles["BodyText"]),
    ]
    doc.build(story)


def main() -> None:
    out_dir, count, tag = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        title = f"Upload Fixture {tag} Paper {i}"
        make_pdf(out_dir / f"upload-fixture-{i}.pdf", title)
        print(out_dir / f"upload-fixture-{i}.pdf")


if __name__ == "__main__":
    main()
