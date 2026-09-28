"""Playwright test helper (remediation Phase 6): a paper found by discovery,
with a research profile stored the way the pipeline stored them before
refinement existed -- the abstract with its "Abstract" label and publisher
block, metric names without values, lowercase names, a repeated entity.
Everything the page then shows comes from the real backend reading it.

Usage:
  python seed-old-profile.py seed <paper_id>     # the paper and its profile
  python seed-old-profile.py paper <paper_id>    # the paper only, not analysed
  python seed-old-profile.py clean <paper_id>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine, delete  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import repository as repo  # noqa: E402
from app.db.models import PaperORM, ResearchProfileORM  # noqa: E402
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile, SourceSpan  # noqa: E402
from app.services.normalize.canonical import title_hash  # noqa: E402

mode, paper_id = sys.argv[1], sys.argv[2]
db = sessionmaker(bind=create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db"))()

if mode == "clean":
    db.execute(delete(ResearchProfileORM).where(ResearchProfileORM.paper_id == paper_id))
    db.execute(delete(PaperORM).where(PaperORM.id == paper_id))
    db.commit()
    print("cleaned")
    sys.exit(0)

ABSTRACT = (
    "Abstract\ufffdIn modern educational institutions, attendance tracking is slow and error-prone. This paper proposes "
    "a face recognition attendance system for classrooms. It detects faces in a single classroom photo and matches them "
    "with face-api.js. Experiments on 40 students reveal a precision and recall of 96% and 93% respectively. "
    "\u00a9 2025 The Authors. Published by ELSEVIER B.V. Keywords: attendance, face recognition"
)
QUOTE = "a precision and recall of 96% and 93% respectively"

repo.save_paper(
    db,
    PaperORM(
        id=paper_id, title="Classroom attendance by face recognition (fixture)", title_hash=title_hash(paper_id),
        abstract=ABSTRACT, has_full_text=False, source="discovery",
    ),
)
if mode == "seed":

    def verified(value: str, quote: str) -> ProfileField:
        return ProfileField(value=value, source_span=SourceSpan(paper_id=paper_id, quote=quote, page=None), status="verified")

    repo.upsert_profile(
        db,
        ResearchProfile(
            profile_id=f"prof_{paper_id}",
            paper_id=paper_id,
            grounding="abstract",
            title="Classroom attendance by face recognition (fixture)",
            abstract=ABSTRACT,
            domain=verified("education technology", "attendance tracking is slow"),
            research_problem=verified("attendance tracking is slow and error-prone", "attendance tracking is slow and error-prone"),
            methods=ProfileList(items=[verified("face detection", "It detects faces in a single classroom photo"), ProfileField(value="Guessed method.")]),
            models=ProfileList(items=[verified("face-api.js", "matches them with face-api.js")]),
            evaluation_metrics=ProfileList(items=[verified("precision", QUOTE), verified("recall", QUOTE), ProfileField(value="F1 score")]),
            important_entities=ProfileList(items=[verified("face-api.js", "matches them with face-api.js")]),
            keywords=["attendance", "face recognition"],
            extraction_confidence=Confidence.MEDIUM,
            extraction_model="playwright-fixture",
        ),
    )
db.commit()
print("seeded")
