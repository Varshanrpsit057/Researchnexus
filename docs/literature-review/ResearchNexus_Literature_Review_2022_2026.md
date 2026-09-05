# ResearchNexus — Literature Review (2022–2026)

### Agentic AI Platform for Intelligent Research Paper Retrieval — with Seed-Paper → Related-Paper Discovery → Research Trail → Multi-Paper Workflow

**Scope note.** This review concerns *ResearchNexus* only — an agentic research-paper assistant. It contains no material from any facial-recognition, CCTV, or attendance system, and none was consulted.

**Status.** Phases 3–8 of the agreed workflow. The paper set was verified in Phase 2 and approved. 25 primary papers (2022–2026) + 5 foundational (pre-2022) + 4 background surveys, with a 12-item verified reserve pool. Every metric, DOI, venue and dataset below is either (a) confirmed against an authoritative source (arXiv, ACL Anthology, NeurIPS/ICLR/OpenReview, Nature, Springer, Wiley, ACM) during Phase 1–3 verification, or (b) explicitly marked *"Not clearly stated in the sources reviewed"*. Nothing is invented. Where a number could only be seen in a secondary index, it is flagged.

**Companion files**
- `docs/literature-review/paper-metadata.csv` — machine-readable metadata for all 46 verified works.
- `docs/architecture/ResearchNexus_Seed_Paper_Research_Trail.md` — design of the new seed-paper capability.

---

## 1. Executive Summary

Between 2022 and 2026 the "AI research assistant" moved from *retrieval benchmarks and summarisation datasets* to *deployed, citation-grounded, increasingly agentic systems* that retrieve over tens of millions of papers and synthesise cited answers. The strongest evidence points are: **OpenScholar** (retrieval over 45M papers; citation accuracy on par with human experts; published in *Nature*), **PaperQA2** (matches PhD/postdoc experts on literature retrieval; adds contradiction detection), **Ai2 Scholar QA** (organized synthesis + per-subtopic comparison tables + attribution), and **PaSa** (a two-agent, RL-trained academic-search agent that expands citations and beats Google Scholar + GPT-4o on recall).

Read against the ResearchNexus feature list, the literature shows a consistent pattern:

- **Individually, every ResearchNexus component is established or well studied.** Scientific RAG QA, dense scholarly retrieval, PDF parsing, LLM summarisation, citation-grounded generation, comparison-table synthesis, survey generation, and even agentic paper search each have a mature 2023–2025 reference implementation and, usually, a benchmark.
- **The *combination* ResearchNexus proposes is only partially covered.** The specific pipeline — **one uploaded seed paper → structured research profile → multi-strategy automatic related-paper discovery → typed, explained, ranked *research trail* → multi-paper workspace → RAG + comparison + evidence-grounded research-gap + research directions + citation + presentation, in a single user-facing agentic loop** — is not demonstrated end-to-end by any single reviewed system.
- **The nearest neighbours each cover a slice.** PaSa (agentic discovery, no synthesis), ResearchAgent (core-paper → academic-graph → ideas, no user workspace/RAG), OpenScholar / PaperQA2 / Ai2 Scholar QA (query → synthesis, but *query*-seeded, not *paper*-seeded, and without an explicit typed trail), LitLLM / "Are we there yet?" (abstract → related-work, no multi-paper QA workspace), AutoSurvey / SurveyForge (topic → survey, not seed-paper → workspace).
- **Four capabilities are repeatedly identified as weak across the corpus** and are where ResearchNexus can make a defensible research contribution: (1) **evidence-grounded, confidence-labelled research-gap statements** (most systems detect contradictions or write "future work" prose, not structured gaps with supporting papers and a confidence score); (2) **typed relationship discovery** (similar / foundational / competing / method-extension / dataset-related / contradictory) rather than a flat ranked list; (3) **transparent, auditable related-paper ranking** that fuses semantic, method, problem, citation, recency and dataset signals with a stated methodology; and (4) **an integrated evaluation** of the *whole* workflow rather than of one stage.

The honest framing for any ResearchNexus paper is therefore **integration + the four weak capabilities**, stated as: *"Existing studies commonly address scientific RAG, scholarly retrieval and survey generation in isolation, and a few recent agents automate paper discovery; comparatively few integrate seed-paper profiling, typed multi-strategy discovery, an explained research trail, and evidence-grounded gap analysis into one interactive workflow, and none evaluate that workflow as a whole."*

---

## 2. ResearchNexus Problem Definition

**User problem.** A researcher beginning a literature review faces (i) discovery cost — finding the right papers across arXiv and publisher sites; (ii) reading cost — extracting problem, method, data, results, limitations from long PDFs; (iii) synthesis cost — comparing papers, spotting contradictions and gaps, and framing new directions; (iv) writing cost — citations and presentation material. These are sequential and today require several disjoint tools (Google Scholar, a PDF reader, a chatbot, a reference manager, slides).

**ResearchNexus target capability.** A single agentic web application (Python, Streamlit/web frontend, LangChain, FAISS, arXiv API, user-selected LLMs, RAG) that supports:

1. arXiv search and PDF upload;
2. **Seed-paper analysis** → a structured **research profile** (problem, domain, subtopics, keywords, methods, models, datasets, research questions, limitations, future work);
3. **Search-concept generation** from that profile;
4. **Automatic related-paper discovery** using *multiple* strategies — semantic similarity, keyword search, query expansion, arXiv search, citation relationships, method similarity, topic similarity, research-question similarity;
5. **Ranking** of discovered papers and a **relevance explanation** per paper;
6. **Typed categorisation** — similar / recent / foundational / competing / methodological-extension / dataset-related / potentially-contradictory — assembled into a **research trail**;
7. user selection → a **multi-paper workspace**;
8. multi-paper **RAG**, summarisation, key-point extraction, Q&A, **paper comparison**, **evidence-grounded research-gap identification**, **future research directions**, **citation generation**, **presentation-outline generation**;
9. an **agentic orchestrator** coordinating the above with tool use, filtering, evidence verification and synthesis;
10. multi-provider / bring-your-own-key LLM support.

**Target workflow.** Seed Paper → Understand → Research Profile → Discover Related Papers → Rank → Research Trail → Multi-Paper Workspace → RAG → Compare → Research Gap → Research Directions → Citation → Presentation.

**What "success" means for the review.** For each stage we need: which reviewed papers address it, the dominant approach, the recurring weakness, and the recommended approach for ResearchNexus (§9–§18, §24).

---

## 3. Literature Search Methodology

- **Discovery (Phase 1, already completed).** ~55 candidates were gathered from targeted searches across: scientific RAG / PDF-RAG; agentic and semantic academic search; scientific document embeddings; long-document and multi-document scientific QA; scientific summarisation (extreme, faceted, multi-document); automated literature-review / related-work / survey generation; multi-paper comparison and table synthesis; research-gap and idea generation; citation-grounded generation, attribution and citation-hallucination; RAG evaluation methodology; scientific PDF parsing; and agentic-AI-for-science framing. Google Scholar, Semantic Scholar, arXiv listings and publisher search were used for *discovery and cross-verification only*.
- **Verification (Phase 2).** Each candidate was checked against an authoritative record — arXiv abstract pages, **ACL Anthology** (DOIs `10.18653/v1/...`), **NeurIPS** and **ICLR/OpenReview** proceedings, **Nature**, **Springer Link**, **Wiley Online Library**, **ACM Digital Library**. Fields verified: exact title, author list, year, venue, publisher, DOI/identifier, peer-review status, paper type, and, where visible, dataset, methodology, models, retrieval/RAG approach, agentic capability, evaluation, metrics, results, limitations. Four candidates that could not be pinned to a stable record were removed ("synergistic multi-stage RAG" — PII only; HiReview — no stable ID; SPAR — unverified/redundant; Scholar Inbox — unverified/tangential).
- **Selection (Phase 2).** The verified pool was cut to 25 primary papers (2022–2026, prioritising 2024–2026), 5 pre-2022 foundational works listed separately, and 4 background surveys for positioning. A 12-item reserve pool was retained for swap-in.
- **Deep analysis (Phase 3).** Supplementary fetches of full-text / proceedings pages were run to strengthen the *evaluation / metrics / limitations* fields. Where a precise figure could not be confirmed from an authoritative page it is reported qualitatively and flagged.

**Source-quality distribution of the 25 primary papers:** ACL Anthology venues (ACL/EMNLP/NAACL/EACL/COLING) 14; NeurIPS 1; ICLR 1; *Nature* 1; *Scientometrics* (Springer) 1; arXiv preprints 7 (PaperQA, PaperQA2, PaperHelper, RA-FSM, GraphRAG, LitLLM, "Are we there yet?" — the last is TMLR-bound). The reserve pool adds ACM (Scim) and Wiley (SciAgents).

---

## 4. Inclusion Criteria

A work was included if **all** of the following held:

1. **Domain fit** — it concerns intelligent research-paper understanding, retrieval, literature review, scientific QA, scholarly search, scientific summarisation, multi-paper synthesis, citation grounding/verification, research-gap or research-idea generation, agentic research workflows, or scientific document processing.
2. **Technical substance** — it presents a system, method, benchmark or dataset with a described pipeline (not an opinion piece or a shallow survey page).
3. **Measurable evaluation** — it reports experiments with quantitative or structured human evaluation (datasets and metrics named), *or* it is a benchmark/dataset paper whose contribution *is* the evaluation resource.
4. **Comparability to ResearchNexus** — at least one component (retrieval, RAG, embeddings, summarisation, QA, comparison, gap analysis, citation, agentic orchestration, seed-paper discovery) can be directly compared with a ResearchNexus component.
5. **Venue credibility** — a reputable peer-reviewed conference/journal (IEEE, ACM, Springer, Elsevier, Wiley, ACL/*ACL, NeurIPS, ICLR, AAAI, *Nature*), or arXiv **only** where the work is a field-defining recent AI/LLM system with wide independent uptake (PaperQA/PaperQA2, GraphRAG).
6. **Recency** — published 2022–2026 for the primary list; a small number of 2020–2021 works are admitted **separately** as "Foundational / Background Works" because they define a task, dataset or metric ResearchNexus depends on.

## 5. Exclusion Criteria

A work was excluded if **any** of the following held:

1. **Out of domain** — general RAG with no scientific-literature angle beyond a passing mention; generic agent surveys; enterprise-document QA unrelated to papers.
2. **No verifiable record** — title, authors, venue or DOI could not be confirmed on an authoritative page (removed in Phase 2: "synergistic multi-stage RAG", HiReview, SPAR, Scholar Inbox).
3. **Non-primary evidence** — blog posts, Medium articles, vendor pages, or press releases used as the *primary* source for a claim (they were allowed only to locate the underlying paper).
4. **Redundancy** — a weaker duplicate of a stronger included paper covering the same contribution (e.g. SPAR vs PaSa).
5. **Pre-2022 and non-foundational** — older work not needed to define a task/metric/dataset ResearchNexus uses.
6. **Any facial-recognition / attendance / surveillance content** — categorically out of scope for this project.

---

## 6. Selected Papers

### 6.1 Primary list — 25 papers (2022–2026)

| # | Short name | Title (verified) | Year | Venue | Peer-reviewed |
|---|---|---|---|---|---|
| 1 | PaperQA | PaperQA: Retrieval-Augmented Generative Agent for Scientific Research | 2023 | arXiv preprint | No (preprint) |
| 2 | PaperQA2 | Language agents achieve superhuman synthesis of scientific knowledge | 2024 | arXiv preprint (FutureHouse) | No (preprint) |
| 3 | OpenScholar | Synthesizing scientific literature with retrieval-augmented language models | 2024→2026 | arXiv → *Nature* | **Yes (Nature)** |
| 4 | Ai2 Scholar QA | Ai2 Scholar QA: Organized Literature Synthesis with Attribution | 2025 | ACL 2025 (Demo) | Yes |
| 5 | PaperHelper | PaperHelper: Knowledge-Based LLM QA Paper Reading Assistant | 2025 | arXiv preprint | No (preprint) |
| 6 | RA-FSM | Hallucination-Resistant, Domain-Specific Research Assistant with Self-Evaluation and Vector-Grounded Retrieval | 2025 | arXiv preprint | No (preprint) |
| 7 | PaSa | PaSa: An LLM Agent for Comprehensive Academic Paper Search | 2025 | ACL 2025 (Long) | **Yes** |
| 8 | LitLLM | LitLLM: A Toolkit for Scientific Literature Review | 2024 | arXiv preprint (toolkit) | Partial |
| 9 | LitLLMs "Are we there yet?" | LitLLMs, LLMs for Literature Review: Are we there yet? | 2024 | arXiv → TMLR 2025 | Likely (TMLR) |
| 10 | LitSearch | LitSearch: A Retrieval Benchmark for Scientific Literature Search | 2024 | EMNLP 2024 (Main) | **Yes** |
| 11 | SciRepEval / SPECTER2 | SciRepEval: A Multi-Format Benchmark for Scientific Document Representations | 2023 | EMNLP 2023 (Main) | **Yes** |
| 12 | ResearchAgent | ResearchAgent: Iterative Research Idea Generation over Scientific Literature with LLMs | 2025 | NAACL 2025 (Long) | **Yes** |
| 13 | CitationNet-LLM | Academic literature recommendation in large-scale citation networks enhanced by LLMs | 2025 | *Scientometrics* (Springer) | **Yes** |
| 14 | ArxivDIGESTables | ArxivDIGESTables: Synthesizing Scientific Literature into Tables using Language Models | 2024 | EMNLP 2024 (Main) | **Yes** |
| 15 | CHIME | CHIME: LLM-Assisted Hierarchical Organization of Scientific Studies for Literature Review Support | 2024 | ACL 2024 (Findings) | **Yes** |
| 16 | AutoSurvey | AutoSurvey: Large Language Models Can Automatically Write Surveys | 2024 | NeurIPS 2024 | **Yes** |
| 17 | SurveyForge | SurveyForge: Outline Heuristics, Memory-Driven Generation, and Multi-dimensional Evaluation for Automated Survey Writing | 2025 | ACL 2025 (Long) | **Yes** |
| 18 | STORM | Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models | 2024 | NAACL 2024 (Long) | **Yes** |
| 19 | ChatCite | ChatCite: LLM Agent with Human Workflow Guidance for Comparative Literature Summary | 2025 | COLING 2025 (Main) | **Yes** |
| 20 | GraphRAG | From Local to Global: A Graph RAG Approach to Query-Focused Summarization | 2024 | arXiv preprint (Microsoft) | No (preprint) |
| 21 | PDFTriage | PDFTriage: Question Answering over Long, Structured Documents | 2024 | EMNLP 2024 (Industry) | **Yes** |
| 22 | M3SciQA | M3SciQA: A Multi-Modal Multi-Document Scientific QA Benchmark | 2024 | EMNLP 2024 (Findings) | **Yes** |
| 23 | ALCE | Enabling Large Language Models to Generate Text with Citations | 2023 | EMNLP 2023 (Main) | **Yes** |
| 24 | Self-RAG | Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection | 2023/24 | ICLR 2024 (Oral) | **Yes** |
| 25 | RAGAs | RAGAs: Automated Evaluation of Retrieval Augmented Generation | 2024 | EACL 2024 (Demo) | Yes |

### 6.2 Foundational / Background Works (pre-2022) — not counted in the primary 25

| # | Short name | Title | Year | Venue |
|---|---|---|---|---|
| F1 | QASPER | A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers | 2021 | NAACL 2021 |
| F2 | Multi-XScience | Multi-XScience: A Large-scale Dataset for Extreme Multi-document Summarization of Scientific Articles | 2020 | EMNLP 2020 |
| F3 | SciTLDR | TLDR: Extreme Summarization of Scientific Documents | 2020 | EMNLP 2020 (Findings) |
| F4 | FacetSum | Bringing Structure into Summaries: a Faceted Summarization Dataset for Long Scientific Documents | 2021 | ACL-IJCNLP 2021 |
| F5 | SciFact | Fact or Fiction: Verifying Scientific Claims | 2020 | EMNLP 2020 |

### 6.3 Background surveys (positioning only)

| # | Short name | Title | Year | Venue |
|---|---|---|---|---|
| B1 | RAG-Survey | Retrieval-Augmented Generation for Large Language Models: A Survey | 2023 | arXiv |
| B2 | LLM4SR | LLM4SR: A Survey on Large Language Models for Scientific Research | 2025 | arXiv |
| B3 | HypToPub | From Hypothesis to Publication: A Comprehensive Survey of AI-Driven Research Support Systems | 2025 | EMNLP 2025 (Findings) |
| B4 | AgenticRAG-Survey | Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG | 2025 | arXiv |

### 6.4 Reserve pool (verified; swap-in candidates)

Scim (IUI 2023, ACM) · Nougat (2023) · MinerU (2024) · SciLitLLM (ICLR 2025) · The AI Scientist (2024) · SciAgents (*Advanced Materials*, Wiley) · Can LLMs Generate Novel Research Ideas? (2024) · SciReviewGen (ACL 2023 Findings) · SPIQA (NeurIPS 2024) · RAG for Academic Literature Navigation in Data Science (2024) · Arxiv Copilot (EMNLP 2024 Demo) · Do LMs Know When They're Hallucinating References? (2023).

---

## 7. Paper-by-Paper Analysis

Each entry uses the same template. "Agentic classification" applies a strict test: **LLM application** = single prompt/response, no retrieval; **RAG application** = retrieve-then-generate, fixed control flow; **Agentic (tool-use)** = the model decides which tool to call and when, and may iterate; **Agentic (multi-agent)** = ≥2 coordinated LLM roles. A chatbot is *not* called agentic unless the paper demonstrates planning, tool selection, iteration, or self-critique.

### P1 — PaperQA (2023, arXiv:2312.07559)
- **Problem / domain:** answer scientific questions from full-text papers with reliable citations; reduce hallucination in science QA.
- **Method:** an agent with three tools — `search` (find papers), `gather_evidence` (collect and rank relevant chunks into a context library), `answer_question` (generate from accumulated evidence). The agent decides how many times to search/gather before answering.
- **Retrieval:** dense retrieval over chunked full text; relevance assessed per passage; top evidence assembled dynamically. Embedding model / vector store: **not clearly stated in the sources reviewed** (uses an external embedding service).
- **Document processing:** full-text ingestion and chunking (chunk size not stated).
- **RAG:** iterative, agent-controlled; context library built across multiple retrieval rounds; citations attached to claims.
- **LLM:** GPT-4 / GPT-3.5 class, prompted (no fine-tuning).
- **Agentic classification:** **Agentic (tool-use)** — the loop chooses tools and iterates.
- **Evaluation & metrics:** introduces **LitQA** (questions requiring retrieval + synthesis across the literature); also PubMedQA and other science QA; accuracy and comparison to expert humans.
- **Main results:** matches expert human researchers on LitQA and exceeds contemporary LLMs / LLM-agents on existing science-QA benchmarks (exact percentages not confirmed from an authoritative page here).
- **Limitations:** multi-step agent cost and latency; retrieval quality bounded by access to full text; no user-facing multi-paper workspace or typed trail.
- **Relevance to ResearchNexus:** the canonical architecture for RN's RAG QA loop (search → gather-evidence → answer) and for attaching citations to claims.
- **Research gap it exposes:** starts from a *question*, not a *seed paper*; no research-profile extraction, no typed related-paper discovery, no gap/direction output.

### P2 — PaperQA2 / "Language agents achieve superhuman synthesis of scientific knowledge" (2024, arXiv:2409.13740)
- **Problem / domain:** high-accuracy retrieval, summarisation and **contradiction detection** over the scientific literature; measure against domain experts.
- **Method:** an optimised PaperQA-style agent; paper chunks ranked by top-k dense retrieval, then **re-ranked and contextually summarised by an LLM** before entering the generation context (a key precision step). A derived agent, **ContraCrow**, checks each claim in a paper against the literature for disagreement.
- **Retrieval:** top-k dense retrieval + LLM re-ranking + LLM chunk summarisation; multi-document.
- **Document processing:** PDFs, text, Office, source code; chunking + per-chunk contextual summaries.
- **RAG:** multi-stage (retrieve → rerank → summarise → generate) with citations.
- **LLM:** multiple frontier models, prompted.
- **Agentic classification:** **Agentic (tool-use)**; ContraCrow adds a specialised verification agent.
- **Evaluation & metrics:** LitQA2; WikiCrow (Wikipedia-style topic articles); expert comparison; contradictions/paper with human validation.
- **Main results:** matches or exceeds PhD/postdoc biologists at retrieving information from the literature; writes cited topic summaries more accurate than existing human-written Wikipedia articles; ≈ 2.34 ± 1.99 contradictions/paper in biology, ~70 % validated by experts.
- **Limitations:** preprint; heavy API cost; biology-centric evaluation; contradiction detection ≠ structured research-gap statements.
- **Relevance to ResearchNexus:** the rerank-then-summarise-then-generate pattern is the recommended RN retrieval refinement; ContraCrow is the closest published analogue to RN's "potentially contradictory" trail category and to evidence-grounded gap analysis.
- **Research gap it exposes:** contradictions are found pairwise against a corpus, not surfaced as *gap statements with supporting papers, evidence, confidence and a proposed direction*; still query-seeded.

### P3 — OpenScholar / "Synthesizing scientific literature with retrieval-augmented language models" (2024 arXiv:2411.14199 → *Nature* 2026, DOI 10.1038/s41586-025-10072-4)
- **Problem / domain:** answer scientific queries with citation-backed, synthesised long-form responses over a very large open-access corpus.
- **Method:** a purpose-built retrieval pipeline over **45M open-access papers** with a passage index; a trained 8B synthesis model (**OpenScholar-8B**) plus a GPT-4o variant; **iterative self-feedback** generation that refines the answer and its retrieval.
- **Retrieval:** trained scientific retriever + trained reranker over a passage datastore; iterative.
- **Document processing:** passage/snippet indexing of full text.
- **Embeddings / vector store:** custom trained retriever; datastore/passage index (specific ANN library not stated).
- **RAG:** retrieve → generate → self-feedback → re-retrieve; citation attached to each claim.
- **LLM:** OpenScholar-8B (trained on synthesised scientific-synthesis data) and OpenScholar-GPT4o.
- **Agentic classification:** **Agentic (tool-use)** — iterative retrieve/generate/refine with self-feedback.
- **Evaluation & metrics:** **ScholarQABench** (2,967 expert queries; 208 long-form answers; CS, physics, neuroscience, biomedicine); correctness, citation accuracy, expert preference.
- **Main results:** OpenScholar-8B beats GPT-4o by ~5 % and PaperQA2 by ~7 % on correctness; **citation accuracy on par with human experts**, versus GPT-4o hallucinating citations 78–90 % of the time; experts preferred OpenScholar answers to expert-written ones in a large fraction of cases.
- **Limitations:** the 8B model still trails the largest proprietary models on some axes; building/refreshing a 45M-paper datastore is heavy; query-seeded, not paper-seeded.
- **Relevance to ResearchNexus:** the reference standard for *citation-grounded synthesis* and for the evaluation ResearchNexus should adopt (ScholarQABench-style expert queries + citation accuracy). Also the strongest peer-reviewed anchor in the set (*Nature*).
- **Research gap it exposes:** no seed-paper profiling, no typed research trail, no explicit gap/direction module, no user workspace for iterative multi-paper work.

### P4 — Ai2 Scholar QA (2025, ACL 2025 Demo, DOI 10.18653/v1/2025.acl-demo.49)
- **Problem / domain:** organized, attributed literature synthesis for scientific questions; a deployed free app + open-source library.
- **Method:** hybrid **BM25 + dense** retrieval over ~8M full-text papers (108M+ abstracts) on a Vespa cluster; transformer **reranker**, top-50 kept; **3-step generation** — (1) quote extraction, (2) answer outline + clustering into sections, (3) section-by-section report conditioned on earlier sections. For "list"-type sections it generates a **literature-review comparison table** via schema generation then value generation.
- **Retrieval:** hybrid sparse+dense + neural rerank; top-k≈50 after rerank.
- **Document processing:** snippet extraction from full text.
- **Embeddings / vector store:** dense passage embeddings in Vespa (BM25 + dense).
- **RAG:** multi-step, section-structured, with per-claim attribution and paper excerpts for verification.
- **LLM:** Claude Sonnet 3.5 / 3.7 (closed).
- **Agentic classification:** **RAG application** with structured multi-step generation (not autonomous tool selection).
- **Evaluation & metrics:** outperforms competing scientific-QA systems on a recent benchmark; table quality assessed with an ArxivDIGESTables-style set (specific numbers not confirmed here).
- **Main results:** organized reports with inline attribution + auto-generated comparison tables per subtopic; strong benchmark standing.
- **Limitations:** closed LLM; corpus limited to indexed open access; table evaluation preliminary; query-seeded.
- **Relevance to ResearchNexus:** the closest published match to RN's *answer + comparison-table + attribution* output; its schema-then-value table method is directly reusable for RN's comparison feature.
- **Research gap it exposes:** no seed-paper → profile → discovery front end; tables are generated inside an answer, not as a persistent, user-editable multi-paper workspace; no gap/direction module.

### P5 — PaperHelper (2025, arXiv:2502.14271)
- **Problem / domain:** help a researcher read and query a specific paper (or small set) with reliable references.
- **Method:** RAG framework using **RAG-Fusion** (multi-query retrieval with reciprocal-rank fusion) and **RAFT** (retrieval-augmented fine-tuning) on a domain corpus; tools for search, evidence gathering, answer.
- **Retrieval:** multi-query dense retrieval + fusion; top-k not stated.
- **Document processing:** PDF ingestion + chunking (parameters not stated); batch download; Mermaid diagrams of document relationships.
- **Embeddings / vector store:** not stated.
- **RAG:** fine-tuned (RAFT) RAG with fusion retrieval.
- **LLM:** fine-tuned GPT-4 API.
- **Agentic classification:** **RAG application** (fine-tuned) with fixed tool sequence.
- **Evaluation & metrics:** F1 and latency on a QA set; comparison to basic RAG.
- **Main results:** F1 60.04 at 5.8 s latency; ~7 % F1 over basic RAG; RAFT + fusion measurably help.
- **Limitations:** preprint; fine-tuned on ML-domain papers only; absolute F1 modest; single-paper scope.
- **Relevance to ResearchNexus:** shows concrete, cheap upgrades to a vanilla RN RAG (multi-query fusion; optional RAFT) and gives a latency reference point (~6 s) for the "ask this PDF" path.
- **Research gap it exposes:** no discovery, no multi-paper synthesis, no gap analysis; fine-tuning ties it to one domain (RN's BYOK/multi-provider model favours prompt-only).

### P6 — RA-FSM: Hallucination-Resistant Domain-Specific Research Assistant (2025, arXiv:2510.02326)
- **Problem / domain:** a *trustworthy* research assistant that refuses out-of-scope questions and never fabricates citations (demonstrated in photonics).
- **Method:** a **finite-state control loop — Relevance → Confidence → Knowledge** — that filters out-of-scope queries, **scores answerability**, decomposes the question, and triggers retrieval *only when needed*; **dual store** (dense vector index for prose + relational table for normalised numeric/spec fields); **deterministic citation pipeline** over an in-corpus, de-duplicated reference set with confidence labels; "I don't know" fallback.
- **Retrieval:** dense retrieval gated by self-evaluation; ranked-tier ingestion (journals, conferences, indices, preprints, patents).
- **Document processing:** tiered ingestion; metric extraction into a relational store.
- **Embeddings / vector store:** dense vector index + relational store (library not stated).
- **RAG:** conditional RAG with a claim→evidence table for audit.
- **LLM:** GPT-class (baselines: Notebook LM, vanilla GPT).
- **Agentic classification:** **Agentic (tool-use)** — an explicit state machine with self-evaluation and conditional actions.
- **Evaluation & metrics:** blinded expert A/B preference; **citation fidelity** (fabrication rate, DOI-match, claim coverage); calibration (ECE, AURC); quality-vs-budget curves.
- **Main results:** experts prefer RA-FSM over Notebook LM and vanilla GPT; **fabricated references near zero**; better boundary-condition handling.
- **Limitations:** preprint; single narrow domain (photonics); adds tunable latency/cost.
- **Relevance to ResearchNexus:** the best available template for making RN's agentic loop *safe and auditable* — answerability scoring, deterministic (non-LLM) citations, claim→evidence tables, "I don't know". Directly informs RN's gap-confidence and citation modules.
- **Research gap it exposes:** no discovery/trail/workspace; the finite-state design is hand-built for one domain and one Q&A task, not a general multi-paper research workflow.

### P7 — PaSa (2025, ACL 2025 Long, DOI 10.18653/v1/2025.acl-long.572)
- **Problem / domain:** comprehensive **academic paper search** for complex scholarly queries — the discovery stage itself.
- **Method:** two LLM agents. **Crawler** processes the query, calls a search tool, reads papers from a queue, **expands citations** of promising papers, and decides when to stop; every collected paper is appended to the queue. **Selector** judges each queued paper's relevance. Trained with **reinforcement learning** on synthetic data.
- **Retrieval:** agent-driven search-tool calls + **citation-graph expansion** (multi-hop); Selector re-scores.
- **Document processing:** reads paper text to decide citation expansion (details not stated).
- **Embeddings / vector store:** not the focus; external search index.
- **RAG:** no answer generation — discovery + selection only.
- **LLM:** GPT-4o baseline; **PaSa-7B** RL-trained.
- **Agentic classification:** **Agentic (multi-agent)** — Crawler + Selector, iterative, multi-hop, with a stop policy.
- **Evaluation & metrics:** **AutoScholarQuery** (35k queries from top-AI-conference papers) for training; **RealScholarQuery** for evaluation; recall@20/@50, precision.
- **Main results:** PaSa-7B beats Google + GPT-4o by **+37.78 % recall@20** and **+39.90 % recall@50**, and beats PaSa-GPT-4o by ~30 % recall / ~4 % precision.
- **Limitations:** trained on synthetic queries; AI-conference domain bias; **no downstream profiling, synthesis, gap or citation** — discovery only.
- **Relevance to ResearchNexus:** the reference design for RN's *automatic related-paper discovery* — especially the Crawler's citation expansion + a Selector that scores relevance, and the recall@k evaluation RN should reuse.
- **Research gap it exposes:** PaSa stops at a ranked paper list; it does not build a *typed* trail (similar/foundational/competing/…), does not explain relevance per paper in user terms, and does not continue into a workspace.

### P8 — LitLLM: A Toolkit for Scientific Literature Review (2024, arXiv:2402.01788)
- **Problem / domain:** help an author draft the related-work section from a **user-provided abstract**.
- **Method:** LLM summarises the abstract into search keywords → web/API search for candidate papers → **re-rank candidates conditioned on the user abstract** → **plan** the related-work structure → **generate** with citations. The user can inject known papers/keywords.
- **Retrieval:** keyword search over an external index + abstract-conditioned LLM re-ranking; "abstract-first".
- **Document processing:** operates on abstracts/metadata, not full PDFs.
- **Embeddings / vector store:** not central (search API).
- **RAG:** retrieve → rerank → plan → generate.
- **LLM:** off-the-shelf (GPT-3.5/4 class).
- **Agentic classification:** **RAG application** (fixed plan-then-generate; not autonomous).
- **Evaluation & metrics:** qualitative reduction in time/effort; rerank quality (limited quantitative reporting in the toolkit paper).
- **Main results:** RAG + reranking + plan-then-generate produce more grounded, current related-work than a plain LLM.
- **Limitations:** no autonomous/multi-hop search; hallucination still possible; thin quantitative evaluation (addressed in P9).
- **Relevance to ResearchNexus:** LitLLM's **abstract → keywords → retrieve → rerank** is essentially RN's *search-concept generation + first-pass discovery*; the "inject known papers" affordance maps to RN's user-selection step.
- **Research gap it exposes:** seeded by an abstract the user *writes*, not a *paper they upload*; no research profile beyond keywords; no typed trail; no QA workspace.

### P9 — LitLLMs, "LLMs for Literature Review: Are We There Yet?" (2024, arXiv:2412.15249; TMLR 2025)
- **Problem / domain:** systematically test whether decomposed LLM pipelines can write literature reviews from an abstract.
- **Method:** two-step **retrieval** (LLM keyword extraction from the abstract → query an external knowledge base) and two-step **generation** (plan the review → execute the plan). Careful contamination controls for zero-shot evaluation.
- **Retrieval:** keyword-based external search + LLM **re-ranking** ("sentence-transformer/LLM rerank").
- **RAG:** retrieve → rerank → plan → generate.
- **LLM:** GPT-4 class, zero-shot.
- **Agentic classification:** **RAG application** (decomposed, not autonomous).
- **Evaluation & metrics:** **normalized recall** for retrieval; generation quality by LLM + human; contamination-controlled arXiv test set.
- **Main results:** the **re-ranking step doubles normalized recall** vs naive search; plan-then-generate improves review quality; LLMs are "promising" but not yet reliable unaided.
- **Limitations:** zero-shot only; retrieval bounded by the external KB; no multi-hop or citation-graph discovery; no full-text reasoning.
- **Relevance to ResearchNexus:** direct evidence that RN should (a) generate search concepts with an LLM, (b) **always re-rank** retrieved candidates, (c) decompose synthesis into plan → generate. The "doubles recall" result is a concrete argument for RN's rerank stage.
- **Research gap it exposes:** same as P8 plus — the study itself concludes the field is "not there yet" for unaided review, i.e. **the human-in-the-loop, workspace-centric design ResearchNexus proposes is under-explored**.

### P10 — LitSearch (2024, EMNLP 2024 Main, DOI 10.18653/v1/2024.emnlp-main.840)
- **Problem / domain:** a realistic retrieval benchmark for **scientific literature search**.
- **Method:** 597 queries about recent ML/NLP papers — GPT-4-generated from inline-citation paragraphs + author-written questions about their own papers; manual quality review.
- **Retrieval:** compares **BM25** vs multiple **dense retrievers**; adds **LLM reranking**.
- **RAG:** none (retrieval benchmark).
- **LLM:** GPT-4 for query generation and reranking.
- **Evaluation & metrics:** recall@5, recall@20; reranking gain.
- **Main results:** dense retrievers beat BM25 by **24.8 absolute recall@5**; LLM reranking adds **+4.4 %**; commercial tools (Google Search) trail the best dense retriever by ~32 points.
- **Limitations:** recent-ML/NLP domain; 597 queries; tests retrieval only, not reasoning.
- **Relevance to ResearchNexus:** the benchmark and protocol RN should use to justify its embedding + rerank choices for discovery; quantifies why **semantic > keyword** for scholarly search.
- **Research gap it exposes:** even the best retriever leaves large recall gaps on realistic queries → RN's **multi-strategy** discovery (semantic + keyword + citation + query-expansion) is warranted rather than redundant.

### P11 — SciRepEval / SPECTER2 (2023, EMNLP 2023 Main, DOI 10.18653/v1/2023.emnlp-main.338)
- **Problem / domain:** general-purpose **scientific document embeddings** and a benchmark to evaluate them across task formats.
- **Method:** **SPECTER2** learns multiple embeddings per document via **task-format-specific adapters + control codes** (classification, regression, proximity/similarity, ad-hoc search). **SciRepEval** = 24 tasks across 4 formats (16 held out for generalisation).
- **Retrieval:** embedding similarity + ad-hoc search task format.
- **Embeddings / vector store:** SPECTER2 (transformer encoder + adapters; base 768-dim); benchmark, not a served index.
- **RAG:** none.
- **LLM:** n/a (encoder models).
- **Evaluation & metrics:** nDCG / MAP / F1 across 24 tasks.
- **Main results:** format-specific adapters beat the single-embedding SOTA by **>2 points absolute**; naive multi-task training does not.
- **Limitations:** must run the right adapter per task; English scientific text; encoder (not generative).
- **Relevance to ResearchNexus:** SPECTER2 (or SciNCL) is the recommended **"similar paper" backbone** for RN's semantic-similarity discovery — a scientifically-tuned alternative/complement to RN's local MiniLM chunk embeddings, which were tuned for QA passages, not document-level similarity.
- **Research gap it exposes:** document-level similarity ≠ *method* similarity or *research-question* similarity; RN needs additional signals beyond a single embedding space to populate a typed trail.

### P12 — ResearchAgent (2025, NAACL 2025 Long, DOI 10.18653/v1/2025.naacl-long.342)
- **Problem / domain:** generate research **problems, methods and experiment designs** starting from a **core paper**, and iteratively refine them.
- **Method:** core paper → augment with neighbours over an **academic (citation) graph** + entities retrieved from an **entity-centric knowledge store** built from concepts mined across many papers → generate ideas → **multiple ReviewingAgents** (human-preference-aligned) critique and drive iterative revision.
- **Retrieval:** citation-graph neighbourhood + concept/entity store lookup (not passage RAG).
- **Embeddings / vector store:** concept/entity store (representation not detailed).
- **RAG:** light — retrieval feeds idea generation, not a QA answer.
- **LLM:** GPT-4 class; reviewer criteria elicited from human judgements.
- **Agentic classification:** **Agentic (multi-agent)** — generator + several reviewing agents, iterative.
- **Evaluation & metrics:** human + model-based ratings on novelty / clarity / validity across disciplines.
- **Main results:** produces ideas rated novel/clear/valid; iterative peer-review-style refinement improves them.
- **Limitations:** no experiment execution; idea validity unverified in the world; academic-graph coverage bias; no user workspace or RAG QA.
- **Relevance to ResearchNexus:** the closest published analogue to RN's **seed-paper → (profile via concepts/entities) → academic-graph expansion → research directions** path; ReviewingAgents ≈ RN's evidence-verification/critique step for gap statements.
- **Research gap it exposes:** ResearchAgent jumps from a paper to *ideas* and skips the parts RN centres on — a *typed* trail, a *multi-paper workspace*, RAG QA, comparison tables, and **evidence-grounded gap statements with confidence**.

### P13 — CitationNet-LLM: "Academic literature recommendation in large-scale citation networks enhanced by LLMs" (2025, *Scientometrics* 130:5143–5169, DOI 10.1007/s11192-025-05420-0)
- **Problem / domain:** recommend relevant papers in a large **citation network**.
- **Method:** hybrid — **network-based** citation proximity + **content-based** semantic similarity from LLM embeddings; designed for incremental updates on dynamic databases.
- **Retrieval:** approximate nearest neighbour over abstract embeddings + citation-graph features.
- **Embeddings / vector store:** OpenAI **text-embedding-3-small** on abstracts; ANN index (library not stated).
- **RAG:** none (recommendation).
- **LLM:** used only for semantic embedding enhancement.
- **Evaluation & metrics:** precision / recall / nDCG / MRR on citation-network recommendation.
- **Main results:** the hybrid beats network-only and content-only baselines; embedding stability matters for incremental updates.
- **Limitations:** cold start for brand-new papers with no citations; dependence on a commercial embedding API; recommendation only.
- **Relevance to ResearchNexus:** the reference for RN's **citation-relationship discovery strategy** and for **fusing** citation-graph signal with semantic similarity in ranking; also a peer-reviewed journal data point.
- **Research gap it exposes:** citation-based recommendation inherits **popularity and recency bias** and needs a semantic complement — motivating RN's *multi-strategy* discovery and a *transparent fusion* ranking rather than a single score.

### P14 — ArxivDIGESTables (2024, EMNLP 2024 Main, DOI 10.18653/v1/2024.emnlp-main.538)
- **Problem / domain:** automatically generate **literature-review comparison tables** (rows = papers, columns = comparison aspects).
- **Method:** decompose into **schema generation** (choose aspects/columns) then **value generation** (fill cells), grounded by table captions and in-text references.
- **Retrieval:** uses in-text references + caption as grounding context (RAG for cell values).
- **LLM:** GPT-4 / open LLMs.
- **Agentic classification:** **RAG application** (structured two-step generation).
- **Evaluation & metrics:** **DecontextEval** aligns generated vs reference table elements despite surface differences; recall of reference columns/values.
- **Main results:** LLMs partially reconstruct expert tables; caption + in-text grounding improves fidelity; **novel aspects the model proposes are often still useful** even when reconstruction is incomplete.
- **Limitations:** full reconstruction remains hard; hallucinated cell values; needs grounding context that RN may not have for uploaded PDFs.
- **Relevance to ResearchNexus:** the method and evaluation for RN's **paper-comparison** feature; the schema/value split is directly reusable, and DecontextEval is the right metric.
- **Research gap it exposes:** tables are built from an already-chosen paper set with rich context; RN must *first* discover and type the papers and often works from a single uploaded PDF plus abstracts of the rest.

### P15 — CHIME (2024, ACL 2024 Findings, DOI 10.18653/v1/2024.findings-acl.8)
- **Problem / domain:** organise a set of studies into a **hierarchical topic tree** for literature-review support.
- **Method:** LLM generates category hierarchies and assigns studies to nodes; a **corrector model trained on expert feedback** fixes category links and study assignments.
- **Retrieval:** none (study set assumed given).
- **LLM:** GPT-4 class + trained corrector.
- **Agentic classification:** **LLM application** with a learned corrector (human-in-the-loop).
- **Evaluation & metrics:** **CHIME** dataset — 2,174 LLM-generated hierarchies, 472 topics, 100 expert-corrected; F1 on links and assignments.
- **Main results:** LLMs generate good categories but weaker assignments; the corrector improves study assignment by **+12.6 F1**.
- **Limitations:** requires a curated study set as input; assignment errors without correction; no discovery, no synthesis.
- **Relevance to ResearchNexus:** the method for turning RN's discovered paper set into a **structured research trail** (topic hierarchy) rather than a flat list; the corrector idea supports RN keeping a human-in-the-loop confirmation step.
- **Research gap it exposes:** CHIME organises *by topic only*; RN's trail also needs *relationship-type* edges (foundational / competing / extension / dataset / contradictory) that a topic tree does not express.

### P16 — AutoSurvey (2024, NeurIPS 2024)
- **Problem / domain:** automatically write a full survey on a fast-moving topic.
- **Method:** initial retrieval → **outline generation** → **parallel subsection drafting by multiple LLMs** → integration and refinement → iterative evaluation.
- **Retrieval:** initial retrieval of topic-relevant papers (method not detailed here).
- **RAG:** retrieval-grounded multi-section generation with citations.
- **LLM:** multiple LLMs concurrently (specific models not confirmed from an authoritative page here).
- **Agentic classification:** **RAG application** with parallel drafting (not autonomous agents).
- **Evaluation & metrics:** citation **recall/precision**; content coverage / structure / relevance scored by experts + LLM.
- **Main results:** for an 8k-token survey, citation recall **82.48** / precision **77.42** vs naive RAG 78.14 / 71.92; content quality approaches human.
- **Limitations:** long-context limits; parametric-knowledge staleness; automatic-evaluation bias; topic-seeded, not paper-seeded.
- **Relevance to ResearchNexus:** the **outline → parallel section drafting → refine** pattern for RN's synthesis and presentation-outline features; citation recall/precision is the metric RN should report for synthesised text.
- **Research gap it exposes:** AutoSurvey assumes a topic and produces a document; RN starts from a *paper*, keeps a *workspace*, and must produce *comparisons and gaps*, not only prose.

### P17 — SurveyForge (2025, ACL 2025 Long, DOI 10.18653/v1/2025.acl-long.609)
- **Problem / domain:** close the quality gap between LLM surveys and human surveys, especially outline and citation quality.
- **Method:** **outline heuristics** learned from the structure of human survey outlines + retrieved domain papers; a **memory-driven Scholar Navigation Agent (SANA)** retrieves high-quality references per subsection during writing.
- **Retrieval:** SANA per-subsection retrieval from a memory store.
- **Agentic classification:** **Agentic (tool-use)** — SANA is a retrieval agent invoked during generation.
- **Evaluation & metrics:** **SurveyBench** (100 human surveys; reference / outline / content dimensions); win-rate vs AutoSurvey.
- **Main results:** outperforms AutoSurvey on outline quality and citation accuracy.
- **Limitations:** still below human surveys; evaluation partly LLM-based; topic-seeded.
- **Relevance to ResearchNexus:** per-section retrieval (SANA) is the right pattern for RN's synthesis so each section of an answer/outline pulls its own evidence; outline heuristics inform RN's presentation-outline generator.
- **Research gap it exposes:** same topic-seeded, document-output framing as AutoSurvey; no discovery/trail/workspace/gap.

### P18 — STORM (2024, NAACL 2024 Long, DOI 10.18653/v1/2024.naacl-long.347)
- **Problem / domain:** write a grounded, Wikipedia-like article from scratch — the *pre-writing* (research) stage in particular.
- **Method:** (1) discover diverse **perspectives** on the topic; (2) simulate **conversations** where perspective-driven agents ask a topic expert questions grounded in retrieved sources; (3) curate answers into an **outline**; then write.
- **Retrieval:** internet search grounding the simulated Q&A.
- **Agentic classification:** **Agentic (multi-agent)** — perspective agents + expert agent in simulated dialogue.
- **Evaluation & metrics:** **FreshWiki** dataset; outline organization and coverage vs an outline-driven RAG baseline; expert feedback.
- **Main results:** **+25 %** organized, **+10 %** broad coverage over the baseline; identifies failure modes — **source-bias transfer** and **over-association of unrelated facts**.
- **Limitations:** not scientific-domain-specific; factuality gaps remain; general web sources.
- **Relevance to ResearchNexus:** the **multi-perspective question-asking** idea is a strong way for RN to generate *search concepts* and *comparison dimensions* from a seed paper; STORM's named failure modes are risks RN must test for.
- **Research gap it exposes:** STORM's "research" is question-asking over the open web, not profiling a specific paper or building a typed trail of related papers.

### P19 — ChatCite (2025, COLING 2025 Main)
- **Problem / domain:** produce a **comparative** literature summary (not just a list of paper summaries).
- **Method:** a **Key-Element Extractor** pulls structured elements (problem, method, results …) from each relevant paper, then a **Reflective Incremental Generator** builds the comparative summary paper-by-paper, reflecting and revising as it adds each one.
- **Retrieval:** operates over a provided set of relevant papers (RAG over that set).
- **Agentic classification:** **Agentic (tool-use)** — a workflow-guided agent with an explicit reflection loop.
- **Evaluation & metrics:** **G-Score** (LLM metric aligned to human criteria) + ROUGE; baselines include vanilla chain-of-thought and prior summarisers.
- **Main results:** outperforms CoT and prior methods on comparative-summary dimensions; the incremental+reflective mechanism is the key driver.
- **Limitations:** depends on the quality of the provided paper set; limited human evaluation; no discovery.
- **Relevance to ResearchNexus:** ChatCite's **extract-key-elements-then-compare-incrementally** loop is essentially RN's *research profile per paper → comparison → gap* pipeline; the reflection step is reusable for RN's gap-confidence.
- **Research gap it exposes:** ChatCite is handed the papers; it does not discover, type, or rank them, and it stops at a comparative summary (no explicit gap statements, directions, or presentation).

### P20 — GraphRAG: "From Local to Global" (2024, arXiv:2404.16130, Microsoft Research)
- **Problem / domain:** answer **corpus-level** ("global") questions — "what are the main themes / tensions / gaps?" — that top-k RAG cannot, because they are query-focused *summarisation*, not retrieval.
- **Method:** LLM builds an **entity–relation knowledge graph** from the corpus → **community detection** → LLM writes **community summaries** at several levels → for a query, generate partial answers from each community summary and **map-reduce** into a global answer.
- **Retrieval:** graph/community index rather than flat vector search.
- **Embeddings / vector store:** graph index over LLM-extracted entities/relations.
- **Agentic classification:** **RAG application** (graph-structured; not agentic).
- **Evaluation & metrics:** LLM head-to-head **win-rate** on comprehensiveness / diversity / empowerment over two ~1M-token corpora; baseline = naive/vector RAG.
- **Main results:** substantial win-rate gains over vector RAG on global questions; **root-level community summaries** give competitive quality at **a fraction of the token cost** of full-graph methods.
- **Limitations:** graph construction cost; preprint; not scientific-paper-specific; quality depends on entity extraction.
- **Relevance to ResearchNexus:** the mechanism RN needs for **research-gap and cross-cutting-theme** questions over the multi-paper workspace — vanilla FAISS top-k will fail on "what has nobody done?". A lightweight per-workspace graph (methods, datasets, claims as nodes) is the recommended RN design (§24).
- **Research gap it exposes:** GraphRAG answers global questions as *prose*; it does not emit *structured gap objects* (statement + supporting papers + evidence + confidence + direction) — the specific artefact RN targets.

### P21 — PDFTriage (2024, EMNLP 2024 Industry, DOI 10.18653/v1/2024.emnlp-industry.13)
- **Problem / domain:** QA over long, **structured** documents (PDFs with sections, tables, figures) that exceed context windows.
- **Method:** build a **structured metadata representation** (section text, headers, figure captions, tables); given a query, an LLM **triage** step selects the relevant document frame by *structure or content* and fetches it directly.
- **Retrieval:** structure-aware selection (e.g. "fetch Table 3", "fetch the Methods section") rather than pure embedding similarity.
- **Document processing:** section / header / table / figure-caption extraction — the core contribution.
- **LLM:** GPT-3.5-turbo for triage; GPT-4 comparison.
- **Agentic classification:** **Agentic (tool-use)** — the model calls structure-aware retrieval functions.
- **Evaluation & metrics:** 900+ questions over 80 structured documents, 10 categories; **human preference** vs plain retrieval-augmented LLM.
- **Main results:** better on structure questions and table reasoning; **weaker on simple textual/classification questions**; net human preference for the structured approach.
- **Limitations:** GPT-3.5 triage errors; depends on reliable structure extraction; not paper-specific.
- **Relevance to ResearchNexus:** RN ingests academic PDFs with exactly this structure. PDFTriage argues for **section-aware chunking + a structure index** (not just recursive character chunks), so RN can answer "what dataset did they use?" by going to the right table.
- **Research gap it exposes:** structure extraction from real academic PDFs (multi-column, equations, scanned) is itself unsolved (see reserve: Nougat, MinerU); PDFTriage assumes it works.

### P22 — M3SciQA (2024, EMNLP 2024 Findings, DOI 10.18653/v1/2024.findings-emnlp.904)
- **Problem / domain:** benchmark **multi-modal, multi-document** scientific QA that mimics real research workflows.
- **Method:** each of 70 NLP **paper clusters** = an anchor paper + all its cited documents; 1,452 expert questions. A question typically starts with a **locality-specific** cue (a figure/table in the anchor) that identes a reference paper, then asks a **detailed multi-document** question.
- **Retrieval:** anchor-paper retrieval stage (measured, e.g. by MRR) + cross-document reasoning.
- **LLM:** 18 foundation models (GPT-4o, GPT-4V, Gemini, open MLLMs).
- **Evaluation & metrics:** retrieval MRR; detailed-QA accuracy; human comparison.
- **Main results:** the best models are **far below human experts** on both cross-document retrieval and figure/table reasoning.
- **Limitations:** NLP-domain clusters only; static; multi-modal (RN is text-first).
- **Relevance to ResearchNexus:** the benchmark for RN's **multi-paper QA** and a realistic ceiling; the anchor + cited-docs structure *is* RN's seed-paper + trail structure, so M3SciQA is a natural evaluation set for the discovery + QA pipeline.
- **Research gap it exposes:** current models cannot reliably reason across an anchor and its references — so RN must not over-promise multi-paper QA quality, and should lean on retrieval transparency + citations rather than model reasoning alone.

### P23 — ALCE: "Enabling LLMs to Generate Text with Citations" (2023, EMNLP 2023 Main, DOI 10.18653/v1/2023.emnlp-main.398)
- **Problem / domain:** make long-form LLM answers **verifiable** by citing retrieved evidence, and **measure** citation quality automatically.
- **Method:** end-to-end systems retrieve evidence and generate answers with inline citations; **ALCE** scores three axes — **fluency, correctness, citation quality** (citation precision/recall via NLI between each sentence and its cited passages).
- **Datasets:** ASQA, QAMPARI, ELI5 with associated retrieval corpora.
- **LLM:** GPT / LLaMA-class with various prompting strategies.
- **Evaluation & metrics:** automatic fluency/correctness/citation metrics validated against human judgement.
- **Main results:** even the best systems **lack complete citation support ~50 % of the time** on ELI5; large headroom; retrieval quality and long-context synthesis are the bottlenecks.
- **Limitations:** automatic citation NLI is imperfect; English; general-domain QA.
- **Relevance to ResearchNexus:** ALCE's **citation precision/recall** is exactly how RN should score every generated answer, summary, comparison and gap statement; the framework operationalises "citation-grounded".
- **Research gap it exposes:** citation *support* is unreliable in general LLM generation → RN needs deterministic citation construction (cf. RA-FSM) plus ALCE-style automatic checks, not just prompt instructions.

### P24 — Self-RAG (2023/2024, ICLR 2024 Oral, arXiv:2310.11511)
- **Problem / domain:** improve factuality and citation accuracy by letting the model decide *when* to retrieve and *criticise* its own output.
- **Method:** a single LM trained to emit **reflection tokens** — `Retrieve?`, `IsRelevant?`, `IsSupported?`, `IsUseful?` — so it retrieves on demand (possibly multiple times, or not at all) and self-scores each segment against evidence.
- **Retrieval:** on-demand, triggered by reflection tokens; off-the-shelf retriever.
- **LLM:** trained Llama2 7B / 13B (Self-RAG).
- **Agentic classification:** **Agentic (self-reflection)** — adaptive retrieval + self-critique in one model.
- **Evaluation & metrics:** open-domain QA, reasoning, fact verification, long-form generation (ASQA, bio); accuracy, citation precision/recall, factuality.
- **Main results:** outperforms ChatGPT and retrieval-augmented Llama2-chat; **large gains in citation accuracy** for long-form generation.
- **Limitations:** needs training with reflection tokens (RN's BYOK/prompt-only setup can approximate this with prompting, not training); retriever-quality bound.
- **Relevance to ResearchNexus:** the mechanism for RN's **evidence-verification** step — before finalising an answer/gap, check `IsSupported?` per claim and drop or flag unsupported ones. Approximable via a verification prompt over (claim, retrieved chunks).
- **Research gap it exposes:** Self-RAG verifies *support* of a claim, not *novelty* or *absence* of a claim in the corpus — the harder judgement RN's research-gap feature needs.

### P25 — RAGAs (2024, EACL 2024 Demo, DOI 10.18653/v1/2024.eacl-demo.16)
- **Problem / domain:** evaluate a RAG pipeline **without reference answers**.
- **Method:** LLM-computed metrics — **faithfulness** (answer entailed by retrieved context), **answer relevance** (answer addresses the question), **context relevance** (retrieved context is on-point and concise). Answers are decomposed into atomic statements and each is checked against context.
- **Evaluation & metrics:** validated for correlation with human judgement on WikiEval (small validation set).
- **Main results:** reference-free metrics track human judgement well enough to drive iteration.
- **Limitations:** LLM-judge cost and bias; small validation set; not scientific-specific.
- **Relevance to ResearchNexus:** the practical eval harness RN should wire in from day one — run faithfulness / answer-relevance / context-relevance on every RAG output during development and in a monitoring dashboard.
- **Research gap it exposes:** RAGAs scores a *single* answer; it does not evaluate a *workflow* (discovery recall, trail-typing accuracy, gap quality) — RN needs a composite evaluation (§19, §25).

### Foundational works (F1–F5) — compact analysis

- **F1 QASPER (NAACL 2021).** 5,049 questions over 1,585 NLP papers; extractive/abstractive/yes-no/unanswerable, with evidence spans. Longformer-era baselines trail humans by **>27 F1** on full-paper QA. *Relevance:* the reference benchmark for RN's single-paper chat; use for retrieval-grounded QA accuracy + evidence-selection F1. *Gap:* single-paper, pre-LLM, no multi-document or citation dimension.
- **F2 Multi-XScience (EMNLP 2020).** Related-work-paragraph generation from an abstract + cited-paper abstracts; 40k+ instances; abstractive-favouring; ROUGE. *Relevance:* the canonical *cross-paper synthesis* task and a training/eval set for RN's comparison/related-work; also the base for LitLLM-style evaluation. *Gap:* abstract-only inputs, ROUGE-only, pre-LLM.
- **F3 SciTLDR (EMNLP 2020 Findings).** 5.4k extreme one-sentence summaries over 3.2k papers; CATTS uses titles as auxiliary signal; ROUGE + human. *Relevance:* target length + evaluation reference for RN's "concise summary"; SciTLDR is a ready human-written gold set. *Gap:* one sentence only; no faithfulness metric.
- **F4 FacetSum (ACL-IJCNLP 2021).** 60k+ Emerald articles with purpose/method/findings/value facets. *Relevance:* the template for RN's **structured key-point extraction** — extract *typed* points, not a flat bullet list — which also feeds comparison columns and profile fields. *Gap:* structured-abstract dependency; one publisher's domain.
- **F5 SciFact (EMNLP 2020).** 1.4k expert claims vs 5,183 abstracts with SUPPORT/REFUTE + rationales; domain adaptation helps. *Relevance:* the lineage behind RN's **evidence grounding and contradiction handling**; SciFact-style claim→evidence→label is the mechanism for "potentially contradictory" trail edges and for gap-evidence. *Gap:* biomedical, small, pre-LLM; verifies given claims rather than discovering gaps.

### Background surveys (B1–B4) — how each is used

- **B1 RAG Survey (Gao et al., 2023).** Naive → Advanced → Modular RAG taxonomy; retrieval/generation/augmentation + evaluation. *Use:* classify RN's pipeline as "Modular RAG" (routing across discovery strategies, rerank, structured generation) and frame design choices.
- **B2 LLM4SR (2025).** LLMs across hypothesis discovery / experiment / writing / review, with task-specific methods and benchmarks. *Use:* position RN in the "hypothesis discovery + writing" band and borrow its benchmark catalogue.
- **B3 From Hypothesis to Publication (EMNLP 2025 Findings).** Peer-reviewed map of AI research-support systems (formulation / validation / publication) + benchmarks/tools. *Use:* the citable positioning survey; shows RN spans "knowledge synthesis" (formulation) and "manuscript writing".
- **B4 Agentic RAG Survey (2025).** Taxonomy by agent cardinality, control structure, autonomy, knowledge representation. *Use:* vocabulary and design constraints for RN's orchestrator (§24) — keep it single-orchestrator + typed tools, not a swarm.

---

## 8. Literature Comparison Tables

Legend: **✓** supported / demonstrated · **△** partial / implicit · **✗** not supported · **NR** not reported. S1–S25 map to P1–P25.

### TABLE 1 — General Literature Review

| S.No. | Paper / Year | Problem Domain | Retrieval Method | LLM / AI Method | RAG | Agentic | Multi-Paper | Main Contribution |
|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA / 2023 | Scientific QA, research assistance | Agent-controlled dense retrieval, full text | GPT-4/3.5 prompted | ✓ | ✓ tool-use | △ | Agent (search/gather/answer) matches experts on LitQA |
| S2 | PaperQA2 / 2024 | Literature synthesis, contradiction detection | Dense top-k + LLM rerank + LLM chunk-summary | Frontier LLMs prompted | ✓ | ✓ tool-use + ContraCrow | ✓ | Superhuman literature retrieval; contradiction agent |
| S3 | OpenScholar / 2024→2026 | Citation-grounded synthesis over 45M papers | Trained retriever+reranker, iterative self-feedback | OpenScholar-8B (trained) + GPT-4o | ✓ | ✓ iterative | ✓ | Human-level citation accuracy; ScholarQABench; *Nature* |
| S4 | Ai2 Scholar QA / 2025 | Organized literature synthesis w/ attribution | Hybrid BM25+dense (Vespa) + rerank, top-50 | Claude 3.5/3.7 | ✓ | △ structured | ✓ | Report + per-subtopic comparison tables + attribution |
| S5 | PaperHelper / 2025 | Single-paper reading assistant | RAG-Fusion multi-query + RAFT | Fine-tuned GPT-4 | ✓ | △ | ✗ | RAFT+fusion +7% F1 over basic RAG |
| S6 | RA-FSM / 2025 | Trustworthy domain assistant (photonics) | Self-eval-gated dense retrieval + relational store | GPT-class | ✓ | ✓ finite-state | △ | Answerability scoring + deterministic citations, ~0 fabrication |
| S7 | PaSa / 2025 | Agentic academic paper search | Agent search-calls + citation-graph expansion, multi-hop | GPT-4o / PaSa-7B (RL) | ✗ (no gen) | ✓ multi-agent | ✓ (discovery) | Crawler+Selector; +37.8% recall@20 vs Google+GPT-4o |
| S8 | LitLLM / 2024 | Related-work drafting from an abstract | Keyword search + abstract-conditioned rerank | Off-the-shelf LLM | ✓ | ✗ | ✓ | abstract→keywords→retrieve→rerank→plan→generate toolkit |
| S9 | LitLLMs "there yet?" / 2024 | Decomposed literature-review generation | 2-step keyword search + LLM rerank | GPT-4 class zero-shot | ✓ | ✗ | ✓ | Rerank doubles normalized recall; plan-then-generate |
| S10 | LitSearch / 2024 | Scientific literature search benchmark | BM25 vs dense + LLM rerank | GPT-4 (query gen/rerank) | ✗ | ✗ | ✗ | 597-query benchmark; dense +24.8 R@5 over BM25 |
| S11 | SciRepEval/SPECTER2 / 2023 | Scientific document representation | Embedding similarity + ad-hoc search | Encoder + adapters | ✗ | ✗ | △ | Multi-format embeddings; 24-task benchmark; +2 pts |
| S12 | ResearchAgent / 2025 | Research-idea generation from a core paper | Citation graph + entity-concept store | GPT-4 class | △ | ✓ multi-agent | ✓ | Core paper→graph→ideas + ReviewingAgents refinement |
| S13 | CitationNet-LLM / 2025 | Citation-network paper recommendation | Network proximity + embedding similarity (hybrid) | text-embedding-3-small | ✗ | ✗ | ✓ | Hybrid citation+LLM-embedding recsys beats single-signal |
| S14 | ArxivDIGESTables / 2024 | Literature comparison-table generation | In-text refs + caption grounding | GPT-4 / open LLMs | ✓ | ✗ | ✓ | schema+value table generation; DecontextEval; 2,228 tables |
| S15 | CHIME / 2024 | Hierarchical organization of studies | none (study set given) | GPT-4 class + corrector | ✗ | △ HITL | ✓ | LLM topic hierarchies + trained corrector (+12.6 F1) |
| S16 | AutoSurvey / 2024 | Automated survey writing | Initial retrieval + outline | Multiple LLMs parallel | ✓ | △ | ✓ | retrieval→outline→parallel drafting→refine; cit. R 82.5/P 77.4 |
| S17 | SurveyForge / 2025 | Automated survey writing (better outlines) | SANA per-subsection retrieval | GPT-4 class | ✓ | ✓ SANA agent | ✓ | Outline heuristics + memory agent; beats AutoSurvey |
| S18 | STORM / 2024 | Grounded long-form writing from scratch | Web search grounding simulated Q&A | GPT-3.5/4 class | ✓ | ✓ multi-agent | ✓ | Multi-perspective question-asking → outline; +25% org. |
| S19 | ChatCite / 2025 | Comparative multi-paper summary | RAG over provided paper set | GPT-4 class | ✓ | ✓ reflection | ✓ | Key-element extract + reflective incremental compare; G-Score |
| S20 | GraphRAG / 2024 | Corpus-level query-focused summarisation | Entity KG + community summaries + map-reduce | GPT-4 class | ✓ | ✗ | ✓ | Global "themes/gaps" answers vector RAG can't; low token cost |
| S21 | PDFTriage / 2024 | QA over long structured PDFs | Structure-aware triage (sections/tables/figs) | GPT-3.5 triage / GPT-4 | ✓ | ✓ tool-use | △ | Structured metadata + triage beats flat retrieval on structure Qs |
| S22 | M3SciQA / 2024 | Multi-modal multi-document scientific QA | Anchor retrieval (MRR) + cross-doc reasoning | 18 foundation models | ✓ | ✗ | ✓ | Anchor+cited-docs benchmark; models ≪ humans |
| S23 | ALCE / 2023 | Citation-grounded generation + evaluation | Dense retrieval + cite-while-generate | GPT/LLaMA prompted | ✓ | ✗ | △ | First automatic citation-quality benchmark (ASQA/QAMPARI/ELI5) |
| S24 | Self-RAG / 2024 | Adaptive retrieval + self-critique | On-demand retrieval via reflection tokens | Trained Llama2 7B/13B | ✓ | ✓ self-reflection | △ | Reflection tokens; large citation-accuracy gains |
| S25 | RAGAs / 2024 | Reference-free RAG evaluation | n/a (evaluates pipelines) | LLM-as-judge | n/a | ✗ | ✗ | Faithfulness / answer-rel / context-rel metrics |

### TABLE 2 — Academic Retrieval & Search

| S.No. | Paper | Search Type | Retrieval Method | Embedding Model | Vector DB / Index | Reranking | Citation Search | Top-K | Main Limitation |
|---|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA | Semantic | Dense over full-text chunks | NR (external service) | NR | △ (relevance scoring) | ✗ | NR | Retrieval bound by full-text access |
| S2 | PaperQA2 | Semantic + rerank | Dense top-k + LLM rerank + summary | NR | NR | ✓ LLM | △ (contradiction lookup) | top-k (NR) | API cost of rerank+summary per chunk |
| S3 | OpenScholar | Semantic (trained) | Trained retriever, iterative | Trained scientific retriever | Passage datastore (45M) | ✓ trained | ✓ | NR | Datastore build/refresh cost |
| S4 | Ai2 Scholar QA | Hybrid | BM25 + dense on Vespa | Dense passage emb. | Vespa | ✓ transformer | ✓ | ~50 after rerank | Corpus limited to indexed OA |
| S5 | PaperHelper | Semantic | RAG-Fusion multi-query | NR | NR | △ (RRF) | ✓ (references tool) | NR | Embeddings/store unspecified |
| S6 | RA-FSM | Semantic (gated) | Retrieval only if self-eval requires | NR | Dense index + relational store | ✗ | ✓ deterministic | NR | Narrow domain; latency overhead |
| S7 | PaSa | Agentic keyword + citation | Search-tool calls + citation expansion | NR | External search index | ✓ Selector agent | ✓ (citation graph) | recall@20/@50 eval | Synthetic-query training bias |
| S8 | LitLLM | Keyword→semantic rerank | External search + abstract-conditioned rerank | NR | Search API | ✓ LLM | △ | NR | No autonomous/multi-hop search |
| S9 | LitLLMs "there yet?" | Keyword | LLM keyword extraction + KB query | Sentence-transformer/LLM rerank | External KB | ✓ | △ | NR | Zero-shot; KB-bounded |
| S10 | LitSearch | Both (benchmark) | BM25 vs dense retrievers | GTR / others | none | ✓ LLM (+4.4%) | ✗ | R@5, R@20 | 597 queries; recent ML/NLP only |
| S11 | SciRepEval/SPECTER2 | Ad-hoc search format | Embedding kNN | SPECTER2 (768-d, adapters) | none (benchmark) | ✗ | △ (citation-proximity task) | task-dependent | Adapter per task format |
| S12 | ResearchAgent | Citation graph + concepts | Graph neighbourhood + entity store | NR | Entity store + academic graph | ✗ | ✓ | NR | Graph coverage bias |
| S13 | CitationNet-LLM | Hybrid | Citation proximity + embedding kNN | text-embedding-3-small | ANN (NR) | △ (score fusion) | ✓ | ranking eval | Cold start; API dependency |
| S14 | ArxivDIGESTables | n/a (set given) | in-text ref + caption context | NR | none | ✗ | ✓ | n/a | Needs rich grounding context |
| S15 | CHIME | n/a | none | NR | none | ✗ | ✗ | n/a | Requires curated study set |
| S16 | AutoSurvey | Semantic | Initial topic retrieval | NR | NR | △ | ✓ | NR | Retrieval method under-described |
| S17 | SurveyForge | Semantic (per-section) | SANA memory retrieval | NR | Memory store | ✓ SANA | ✓ | per-subsection | Still trails human surveys |
| S18 | STORM | Web search | Search grounding simulated Q&A | NR | none (web) | ✗ | △ | NR | General web, not scholarly index |
| S19 | ChatCite | n/a (set given) | RAG over provided papers | NR | none | ✗ | ✓ | n/a | Depends on input set quality |
| S20 | GraphRAG | Graph/community | Community-summary map-reduce | LLM entity/relation emb. | Community graph index | ✗ | △ | community levels | Graph build cost |
| S21 | PDFTriage | Structure + content | LLM triage over doc structure | NR | Structured metadata index | △ | ✗ | frame-level | Relies on structure extraction |
| S22 | M3SciQA | Semantic (anchor) | Anchor retrieval + cross-doc | Multimodal (models) | none (benchmark) | ✗ | ✓ | MRR eval | NLP clusters only |
| S23 | ALCE | Semantic | Dense retrieval from corpus | GTR/DPR variants | none (benchmark) | △ | ✓ (evaluates) | k per dataset | Automatic citation NLI imperfect |
| S24 | Self-RAG | On-demand semantic | Reflection-token-triggered retrieval | Contriever/others | none | △ (IsRelevant token) | ✓ | adaptive | Needs reflection-token training |
| S25 | RAGAs | n/a | n/a | n/a | n/a | n/a | △ (evaluates) | n/a | LLM-judge cost/bias |

### TABLE 3 — Seed Paper → Related Papers

| S.No. | Paper | Seed = single paper input | Discovery Method | Semantic sim. | Citation graph | Query expansion | Ranking | Relevance explanation | Automatic continuation into synthesis |
|---|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA | ✗ (question-seeded) | agent search | ✓ | ✗ | △ | △ | ✗ | ✓ (into QA) |
| S2 | PaperQA2 | ✗ | agent search + contradiction | ✓ | △ | △ | △ | ✗ | ✓ (QA + contradictions) |
| S3 | OpenScholar | ✗ (query-seeded) | trained retrieval + self-feedback | ✓ | ✗ | ✓ (iterative) | ✓ (reranker) | △ (citations) | ✓ (into synthesis) |
| S4 | Ai2 Scholar QA | ✗ (query-seeded) | hybrid retrieval | ✓ | ✗ | △ | ✓ | △ (excerpts) | ✓ (report + tables) |
| S7 | **PaSa** | △ (query, can be a paper's topic) | **agent search + citation expansion (multi-hop)** | ✓ | **✓** | ✓ | **✓ (Selector)** | △ (relevance score, not typed) | ✗ (stops at list) |
| S8 | LitLLM | △ (abstract the user writes) | keyword + rerank | ✓ | ✗ | ✓ | ✓ | △ | ✓ (related-work text) |
| S9 | LitLLMs "there yet?" | △ (abstract) | 2-step keyword search | ✓ | ✗ | ✓ | ✓ | ✗ | ✓ (review text) |
| S11 | SPECTER2 | ✓ (doc embedding) | **document-level similarity** | ✓ | △ (citation-proximity task) | ✗ | △ | ✗ | ✗ |
| S12 | **ResearchAgent** | **✓ (core paper)** | **citation/academic graph + concept store** | △ | **✓** | ✗ | △ | △ (concept links) | ✓ (into ideas, not workspace) |
| S13 | CitationNet-LLM | ✓ (a paper node) | **citation network + embedding hybrid** | ✓ | **✓** | ✗ | ✓ | ✗ | ✗ (recommendation only) |
| S15 | CHIME | ✗ (set given) | none | ✗ | ✗ | ✗ | ✗ (organises) | △ (topic labels) | ✓ (into hierarchy) |
| S16–S18 | AutoSurvey / SurveyForge / STORM | ✗ (topic-seeded) | topic retrieval / web | ✓ | ✗ | ✓ | ✓ | △ | ✓ (into survey) |
| S20 | GraphRAG | ✗ (corpus given) | KG communities | ✓ | △ (entity co-occurrence) | ✗ | ✗ | ✗ | ✓ (global summary) |
| S22 | M3SciQA | **✓ (anchor paper)** in the benchmark | anchor→cited-doc retrieval | ✓ | ✓ (cited docs) | ✗ | △ (MRR) | ✗ | ✓ (into multi-doc QA) — as a benchmark, not a system |
| — | **ResearchNexus (target)** | **✓** | **semantic + keyword + query-expansion + arXiv + citation + method/topic/RQ similarity** | ✓ | ✓ | ✓ | **✓ (transparent fusion)** | **✓ (typed, per-paper reason)** | **✓ (into workspace → RAG → compare → gap → directions → citation → slides)** |

(Rows S5, S6, S10, S14, S19, S21, S23, S24, S25 are ✗ for seed-paper discovery and are omitted from Table 3.)

### TABLE 4 — Document & RAG Pipeline

| S.No. | Paper | PDF Processing | Chunking | Embedding | Vector Store | RAG Strategy | Citation Grounding | QA |
|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA | full-text ingest | ✓ (size NR) | NR | NR | agentic iterative | ✓ per claim | ✓ single/multi |
| S2 | PaperQA2 | PDF/office/code | ✓ + per-chunk summary | NR | NR | retrieve→rerank→summarise→gen | ✓ | ✓ multi |
| S3 | OpenScholar | passage index | passage-level | trained retriever | passage datastore | iterative self-feedback | ✓ | ✓ multi |
| S4 | Ai2 Scholar QA | snippet extraction | snippet-level | dense | Vespa | quote→outline→section report | ✓ + excerpts | ✓ multi |
| S5 | PaperHelper | PDF ingest | ✓ (NR) | NR | NR | RAFT + RAG-Fusion | ✓ references | ✓ single |
| S6 | RA-FSM | tiered ingest + metric extraction | ✓ (NR) | NR | dense + relational | conditional RAG + claim/evidence table | ✓ deterministic | ✓ single |
| S7 | PaSa | reads paper text for expansion | n/a | NR | external | no generation | ✓ (citation graph) | ✗ |
| S8 | LitLLM | abstracts/metadata | n/a | NR | search API | retrieve→rerank→plan→gen | ✓ | ✗ (writes RW) |
| S9 | LitLLMs "there yet?" | abstracts | n/a | NR | external KB | retrieve→rerank→plan→gen | ✓ | ✗ |
| S10 | LitSearch | title+abstract corpus | n/a | GTR/others | none | n/a | ✗ | ✗ |
| S11 | SPECTER2 | title+abstract (+cites) | doc-level | SPECTER2 | none | n/a | △ | ✗ |
| S12 | ResearchAgent | paper + graph | n/a | NR | entity store + graph | retrieval feeds ideation | ✓ | ✗ |
| S13 | CitationNet-LLM | abstracts | doc-level | text-embedding-3-small | ANN | n/a (recsys) | ✓ (citations as signal) | ✗ |
| S14 | ArxivDIGESTables | abstracts + captions + in-text | n/a | NR | none | schema→value grounded gen | ✓ | ✗ (tables) |
| S15 | CHIME | study metadata | n/a | NR | none | n/a | ✗ | ✗ |
| S16 | AutoSurvey | retrieved papers | section-level | NR | NR | outline→parallel sections→refine | ✓ | ✗ |
| S17 | SurveyForge | retrieved papers | subsection-level | NR | memory store | outline heuristics + SANA per-section | ✓ | ✗ |
| S18 | STORM | web pages | passage-level | NR | none | perspective Q&A→outline→write | △ | ✗ |
| S19 | ChatCite | provided papers | key-element level | NR | none | extract→reflective incremental compare | ✓ | ✗ |
| S20 | GraphRAG | corpus chunks | ✓ + entities | LLM entity emb. | community graph | community summaries + map-reduce | △ | ✓ global |
| S21 | PDFTriage | **section/table/figure extraction** | structure-aware | NR | structured metadata | LLM triage → fetch frame | △ | ✓ single |
| S22 | M3SciQA | anchor + cited PDFs | NR | multimodal | none | anchor retrieval + cross-doc | ✓ | ✓ multi |
| S23 | ALCE | corpus passages | passage-level | GTR/DPR | none | retrieve + cite-while-gen | ✓ (evaluates) | ✓ |
| S24 | Self-RAG | corpus passages | passage-level | Contriever | none | on-demand + self-critique | ✓ | ✓ |
| S25 | RAGAs | n/a | n/a | n/a | n/a | evaluates any | △ | evaluates |

### TABLE 5 — LLM & Agent

| S.No. | Paper | LLM | RAG | Tool Use | Planning | Agentic | Multi-Agent | Reflection | Verification |
|---|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA | GPT-4/3.5 | ✓ | ✓ | △ | ✓ | ✗ | ✗ | △ |
| S2 | PaperQA2 | frontier | ✓ | ✓ | △ | ✓ | △ (ContraCrow) | ✗ | ✓ (contradiction) |
| S3 | OpenScholar | 8B trained + GPT-4o | ✓ | ✓ | △ | ✓ | ✗ | ✓ (self-feedback) | ✓ |
| S4 | Ai2 Scholar QA | Claude 3.5/3.7 | ✓ | △ | ✓ (outline) | △ | ✗ | ✗ | △ (excerpts) |
| S5 | PaperHelper | fine-tuned GPT-4 | ✓ | ✓ | ✗ | △ | ✗ | ✗ | △ |
| S6 | RA-FSM | GPT-class | ✓ | ✓ | ✓ (decompose) | ✓ | ✗ | ✓ (self-eval) | ✓ (deterministic cite) |
| S7 | PaSa | GPT-4o / 7B RL | ✗ | ✓ | ✓ (stop policy) | ✓ | ✓ (Crawler+Selector) | ✗ | ✓ (Selector) |
| S8 | LitLLM | off-the-shelf | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✗ |
| S9 | LitLLMs "there yet?" | GPT-4 class | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✗ |
| S10 | LitSearch | GPT-4 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| S11 | SPECTER2 | encoder | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| S12 | ResearchAgent | GPT-4 class | △ | ✓ | ✓ | ✓ | ✓ (ReviewingAgents) | ✓ | ✓ (review) |
| S13 | CitationNet-LLM | embedding only | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| S14 | ArxivDIGESTables | GPT-4/open | ✓ | ✗ | ✓ (schema) | ✗ | ✗ | ✗ | △ |
| S15 | CHIME | GPT-4 + corrector | ✗ | ✗ | ✓ (hierarchy) | △ | ✗ | ✗ | ✓ (corrector) |
| S16 | AutoSurvey | multiple parallel | ✓ | ✗ | ✓ (outline) | △ | △ (parallel writers) | ✓ (iterate) | △ |
| S17 | SurveyForge | GPT-4 class | ✓ | ✓ (SANA) | ✓ | ✓ | ✗ | ✗ | △ |
| S18 | STORM | GPT-3.5/4 | ✓ | ✓ (search) | ✓ (outline) | ✓ | ✓ (perspective agents) | ✗ | ✗ |
| S19 | ChatCite | GPT-4 class | ✓ | ✗ | ✓ (workflow) | ✓ | ✗ | ✓ (reflective) | △ |
| S20 | GraphRAG | GPT-4 class | ✓ | ✗ | ✓ (map-reduce) | ✗ | ✗ | ✗ | ✗ |
| S21 | PDFTriage | GPT-3.5/4 | ✓ | ✓ (triage fns) | △ | ✓ | ✗ | ✗ | ✗ |
| S22 | M3SciQA | 18 models | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| S23 | ALCE | GPT/LLaMA | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (evaluates cites) |
| S24 | Self-RAG | trained Llama2 | ✓ | △ | ✗ | ✓ | ✗ | ✓ (tokens) | ✓ (IsSupported) |
| S25 | RAGAs | LLM-judge | n/a | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (metrics) |

### TABLE 6 — Research Features

| S.No. | Paper | Summarization | Key-Point Extraction | QA | Paper Comparison | Research Gap | Research Ideas | Citation Generation | Presentation / Other |
|---|---|---|---|---|---|---|---|---|---|
| S1 | PaperQA | △ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| S2 | PaperQA2 | ✓ | ✗ | ✓ | △ | △ (contradictions) | ✗ | ✓ | ✗ |
| S3 | OpenScholar | ✓ | ✗ | ✓ | △ | △ | ✗ | ✓ | ✗ |
| S4 | Ai2 Scholar QA | ✓ | △ | ✓ | ✓ (tables) | ✗ | ✗ | ✓ | ✗ |
| S5 | PaperHelper | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✓ | Mermaid diagrams |
| S6 | RA-FSM | △ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ deterministic | ✗ |
| S7 | PaSa | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | △ | ✗ |
| S8 | LitLLM | ✓ (RW) | ✗ | ✗ | △ | ✗ | ✗ | ✓ | ✗ |
| S9 | LitLLMs "there yet?" | ✓ (review) | ✗ | ✗ | △ | ✗ | ✗ | ✓ | ✗ |
| S10 | LitSearch | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | retrieval benchmark |
| S11 | SPECTER2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | embeddings |
| S12 | ResearchAgent | ✗ | △ (entities) | ✗ | ✗ | △ (implied) | ✓ | ✓ | experiment design |
| S13 | CitationNet-LLM | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | recommendation |
| S14 | ArxivDIGESTables | ✗ | ✓ (aspects) | ✗ | ✓ | ✗ | ✗ | ✓ | comparison tables |
| S15 | CHIME | ✗ | ✗ | ✗ | △ | △ (via structure) | ✗ | ✗ | topic hierarchy |
| S16 | AutoSurvey | ✓ | ✗ | ✗ | △ | △ | ✗ | ✓ | full survey |
| S17 | SurveyForge | ✓ | ✗ | ✗ | △ | △ | ✗ | ✓ | full survey |
| S18 | STORM | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | △ | outline + article |
| S19 | ChatCite | ✓ | ✓ | ✗ | ✓ | △ | ✗ | ✓ | comparative summary |
| S20 | GraphRAG | ✓ (global) | ✗ | ✓ (global) | △ | △ (themes) | ✗ | △ | ✗ |
| S21 | PDFTriage | △ | ✗ | ✓ | ✗ | ✗ | ✗ | △ | table reasoning |
| S22 | M3SciQA | ✗ | ✗ | ✓ | △ | ✗ | ✗ | ✓ | benchmark |
| S23 | ALCE | ✓ (long-form) | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ (evaluates) | benchmark |
| S24 | Self-RAG | ✓ (long-form) | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| S25 | RAGAs | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | evaluation |

### TABLE 7 — Dataset & Evaluation

| S.No. | Paper | Dataset(s) | Size | Evaluation Method | Metrics | Main Results | Human Eval |
|---|---|---|---|---|---|---|---|
| S1 | PaperQA | LitQA (new); PubMedQA; sci-QA | LitQA ~50 hard Qs (per sources) | accuracy vs humans + LLM baselines | accuracy | matches experts on LitQA (exact % not confirmed) | ✓ |
| S2 | PaperQA2 | LitQA2; WikiCrow; biology corpus | NR | expert comparison; contradiction validation | accuracy; contradictions/paper | ≥ expert on retrieval; ~2.34 contradictions/paper (70% validated) | ✓ |
| S3 | OpenScholar | ScholarQABench | 2,967 queries; 208 long-form | correctness; citation accuracy; expert preference | correctness Δ; citation accuracy | +5% vs GPT-4o, +7% vs PaperQA2; citation ≈ human | ✓ |
| S4 | Ai2 Scholar QA | recent sci-QA benchmark; table set | NR | system comparison; table quality | correctness; table quality | outperforms competing systems | ✓ |
| S5 | PaperHelper | ML-domain QA set | 52k papers for RAFT | vs basic RAG | F1; latency | F1 60.04; 5.8s; +7% F1 | NR |
| S6 | RA-FSM | photonics corpus | NR | blinded A/B; calibration | preference; fabrication rate; ECE/AURC | preferred over Notebook LM & GPT; ~0 fabrication | ✓ |
| S7 | PaSa | AutoScholarQuery; RealScholarQuery | 35k train queries | retrieval recall/precision | recall@20/@50; precision | +37.8% R@20, +39.9% R@50 vs Google+GPT-4o | △ |
| S8 | LitLLM | user abstracts | NR | qualitative + rerank quality | time/effort; rerank | grounded RW vs plain LLM | △ |
| S9 | LitLLMs "there yet?" | arXiv-derived, contamination-controlled | NR | retrieval + generation | normalized recall; LLM/human quality | rerank doubles recall | ✓ |
| S10 | LitSearch | LitSearch | 597 queries | retrieval | recall@5/@20 | dense +24.8 R@5; rerank +4.4% | ✓ (query curation) |
| S11 | SciRepEval | SciRepEval | 24 tasks; 16 held-out | multi-task | nDCG/MAP/F1 | +2 pts over single-embedding SOTA | ✗ |
| S12 | ResearchAgent | multi-discipline papers | NR | human + model rating | novelty/clarity/validity | ideas rated novel/clear/valid | ✓ |
| S13 | CitationNet-LLM | citation networks | large-scale | recsys ranking | precision/recall/nDCG/MRR | hybrid beats single-signal baselines | ✗ |
| S14 | ArxivDIGESTables | arxivDIGESTables | 2,228 tables; 7,542 papers | DecontextEval | column/value recall | partial reconstruction; grounding helps | △ |
| S15 | CHIME | CHIME | 2,174 hierarchies; 472 topics; 100 corrected | F1 on links/assignments | F1 | corrector +12.6 F1 assignment | ✓ (expert correction) |
| S16 | AutoSurvey | AI/ML survey topics | NR | expert + LLM | citation recall/precision; quality | recall 82.48 / precision 77.42 (8k) | ✓ |
| S17 | SurveyForge | SurveyBench | 100 human surveys | win-rate; 3 dimensions | reference/outline/content | beats AutoSurvey | ✓ |
| S18 | STORM | FreshWiki | recent Wikipedia articles | vs RAG baseline; expert | organization; coverage | +25% org; +10% coverage | ✓ |
| S19 | ChatCite | comparative-summary set | NR | vs CoT & summarisers | G-Score; ROUGE | outperforms baselines | ✓ (criteria) |
| S20 | GraphRAG | two ~1M-token corpora | ~1M tokens each | LLM head-to-head win-rate | comprehensiveness/diversity | substantial gains over vector RAG | ✗ (LLM judge) |
| S21 | PDFTriage | PDFTriage set | 900+ Qs; 80 docs; 10 types | human preference | preference | wins on structure/table Qs | ✓ |
| S22 | M3SciQA | M3SciQA | 1,452 Qs; 70 clusters | retrieval + QA | MRR; accuracy | models ≪ humans | ✓ (annotation) |
| S23 | ALCE | ASQA + QAMPARI + ELI5 | 3 datasets | automatic + human | fluency; correctness; citation P/R | best lack full citation support ~50% (ELI5) | ✓ (validation) |
| S24 | Self-RAG | PopQA/PubHealth/ASQA/bio etc. | multiple | task metrics | accuracy; citation P/R; factuality | beats ChatGPT & RA-Llama2-chat | ✗ |
| S25 | RAGAs | WikiEval | small | correlation w/ human | faithfulness/answer-rel/context-rel | metrics track human judgement | ✓ (WikiEval) |

### TABLE 8 — Limitations & Research Gaps

| S.No. | Paper | Major Limitation | Missing Capability | Technical Gap | ResearchNexus Opportunity |
|---|---|---|---|---|---|
| S1 | PaperQA | question-seeded; cost/latency | seed-paper profiling; typed trail | agent step budgeting | build the paper→profile→discovery front end PaperQA lacks |
| S2 | PaperQA2 | biology-centric; preprint | structured gap objects | contradiction ≠ gap statement | convert contradiction signal into gap statement + confidence + direction |
| S3 | OpenScholar | 45M datastore cost; query-seeded | seed-paper trail; gap module | large-corpus infra | reuse ScholarQABench eval; add seed-paper front end and typed trail |
| S4 | Ai2 Scholar QA | closed LLM; tables inside answers | persistent multi-paper workspace | table grounding for uploads | make comparison tables a first-class, editable workspace artefact |
| S5 | PaperHelper | domain-fine-tuned; single-paper | discovery; multi-paper synthesis | store/embeddings unspecified | prompt-only RAG-Fusion for BYOK; extend to workspace |
| S6 | RA-FSM | one narrow domain; latency | general multi-paper workflow | hand-built FSM | generalise answerability + deterministic citation to RN's whole loop |
| S7 | PaSa | discovery only; synthetic-query bias | profiling; typed edges; explanation | RL data realism | add profile-conditioned queries, typed classification, per-paper reasons, continuation |
| S8 | LitLLM | abstract-seeded; no multi-hop | QA workspace; typed trail | shallow eval | seed on an uploaded paper; keep multi-strategy discovery |
| S9 | LitLLMs "there yet?" | zero-shot; KB-bounded | full-text reasoning; workspace | contamination control at scale | adopt "always rerank"; add human-in-the-loop workspace |
| S10 | LitSearch | 597 queries; ML/NLP | reasoning eval | broader domains | use as discovery-recall benchmark; extend queries to RN domains |
| S11 | SPECTER2 | one embedding per format | method/RQ similarity | multi-signal similarity | fuse SPECTER2 doc-similarity with method/problem/RQ signals |
| S12 | ResearchAgent | no execution; graph bias | workspace; RAG QA; gap objects | idea validity | keep graph expansion; add workspace, QA, evidence-grounded gaps |
| S13 | CitationNet-LLM | cold start; API dependency | typed edges; explanation | popularity/recency bias | fuse citation signal transparently with semantics; expose weights |
| S14 | ArxivDIGESTables | needs grounding context | discovery; typing | hallucinated cells | run after discovery+typing; cite every cell; DecontextEval in CI |
| S15 | CHIME | needs curated set; topic-only | relationship-type edges | assignment errors | add typed edges (foundational/competing/…) beyond topic tree |
| S16 | AutoSurvey | long-context; staleness | seed-paper start; gap objects | eval bias | reuse outline→parallel→refine for synthesis/slides only |
| S17 | SurveyForge | trails humans; LLM eval | discovery/trail/workspace | outline heuristics narrow | reuse SANA per-section retrieval pattern |
| S18 | STORM | general web; factuality | scholarly profiling; typed trail | source-bias transfer | use multi-perspective questioning for search-concepts + compare dimensions |
| S19 | ChatCite | input set given; small human eval | discovery; gap/direction/slides | reflection cost | extend extract→compare loop into gap + directions + presentation |
| S20 | GraphRAG | graph build cost; prose output | structured gap objects | entity-extraction quality | build a lightweight per-workspace graph; emit structured gaps |
| S21 | PDFTriage | assumes structure extraction | paper-specific parsing | multi-column/equations/scans | pair with Nougat/MinerU; section-aware chunking + structure index |
| S22 | M3SciQA | NLP clusters; multimodal | text-first system | model reasoning ceiling | use as anchor+trail QA benchmark; lean on retrieval transparency |
| S23 | ALCE | citation NLI imperfect; general | scientific-domain citations | long-context synthesis | adopt citation P/R for every RN generation; deterministic cite build |
| S24 | Self-RAG | needs token training | novelty/absence judgement | reflection via prompt only | approximate IsSupported? as a verification prompt over claims |
| S25 | RAGAs | single-answer; LLM-judge | workflow-level evaluation | validation set size | wrap RAGAs + add discovery-recall + trail-accuracy + gap-quality |

### TABLE 9 — Master Comparison (vs ResearchNexus)

| Paper | Retrieval | Semantic Search | Seed-Paper Discovery | RAG | LLM | Agents | Summary | QA | Related-Paper Typing | Comparison | Gap Detection | Citation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PaperQA | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✓ |
| PaperQA2 | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | △ | △ | ✓ |
| OpenScholar | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | △ | △ | ✓ |
| Ai2 Scholar QA | ✓ | ✓ | ✗ | ✓ | ✓ | △ | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ |
| PaperHelper | ✓ | ✓ | ✗ | ✓ | ✓ | △ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| RA-FSM | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✓ |
| PaSa | ✓ | ✓ | △ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | △ |
| LitLLM | ✓ | ✓ | △ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | △ | ✗ | ✓ |
| LitLLMs "there yet?" | ✓ | ✓ | △ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | △ | ✗ | ✓ |
| LitSearch | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| SPECTER2 | ✓ | ✓ | △ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| ResearchAgent | △ | △ | ✓ | △ | ✓ | ✓ | ✗ | ✗ | △ | ✗ | △ | ✓ |
| CitationNet-LLM | ✓ | ✓ | ✓ | ✗ | △ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| ArxivDIGESTables | △ | △ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | △ | ✓ | ✗ | ✓ |
| CHIME | ✗ | ✗ | ✗ | ✗ | ✓ | △ | ✗ | ✗ | △ | △ | △ | ✗ |
| AutoSurvey | ✓ | ✓ | ✗ | ✓ | ✓ | △ | ✓ | ✗ | ✗ | △ | △ | ✓ |
| SurveyForge | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | △ | △ | ✓ |
| STORM | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | △ |
| ChatCite | △ | △ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | △ | ✓ |
| GraphRAG | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ | △ | △ | △ | △ |
| PDFTriage | ✓ | △ | ✗ | ✓ | ✓ | ✓ | △ | ✓ | ✗ | ✗ | ✗ | △ |
| M3SciQA | ✓ | ✓ | ✓ (bench) | ✓ | ✓ | ✗ | ✗ | ✓ | △ | △ | ✗ | ✓ |
| ALCE | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| Self-RAG | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| RAGAs | n/a | n/a | ✗ | eval | n/a | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | △ |
| **ResearchNexus (target)** | **✓** | **✓** | **✓** | **✓** | **✓ (BYOK/multi)** | **✓ (orchestrator)** | **✓** | **✓ (multi-paper)** | **✓ (typed trail)** | **✓** | **✓ (evidence-grounded)** | **✓ (deterministic + checked)** |

**Reading of Table 9.** No existing system has ✓ across *Seed-Paper Discovery + Related-Paper Typing + Multi-paper QA + Comparison + Gap Detection + Citation* simultaneously. The best-covered rows (OpenScholar, PaperQA2, Ai2 Scholar QA) are strong on RAG/QA/Summary/Citation but ✗ on seed-paper discovery and typed trail; PaSa and ResearchAgent are the only ones touching seed/graph discovery and both are ✗ on the synthesis half.

---

## 9. Academic Search Analysis

**Dominant approaches (2022–2026).**
- **Dense retrieval has decisively beaten keyword search for scholarly queries.** LitSearch (S10) measures a 24.8-point absolute recall@5 gap in favour of dense retrievers, and shows commercial search (Google) trailing the best dense retriever by ~32 points. SciRepEval/SPECTER2 (S11) provides the scientifically-tuned embedding backbone.
- **Hybrid (sparse + dense) is the deployed default.** Ai2 Scholar QA (S4) runs BM25 + dense on Vespa; the data-science RAG reserve paper adds GROBID + fine-tuned embeddings. Hybrid buys robustness to exact-term queries (author names, dataset names, equation symbols) that pure dense misses.
- **LLM reranking is a cheap, reliable gain.** LitSearch (+4.4 %), LitLLMs "Are we there yet?" (rerank *doubles* normalized recall), PaperQA2 (LLM rerank + chunk summarisation before generation). Every strong system reranks.
- **Agentic, multi-hop search is the 2025 frontier.** PaSa (S7) turns search into a policy — issue a query, read results, expand citations, decide to stop — and beats Google + GPT-4o by ~38 points recall@20. ResearchAgent (S12) walks the citation/academic graph from a core paper.
- **Query generation is now an LLM job.** LitLLM / "Are we there yet?" summarise an abstract into keywords; STORM generates perspective-driven questions; OpenScholar iteratively reformulates.

**Weaknesses that recur.**
- Benchmarks are narrow (LitSearch, M3SciQA, LitQA = recent ML/NLP/biology); cross-domain generalisation is untested.
- Recall is still incomplete on realistic queries even for the best retrievers — a single strategy is not enough.
- Citation-graph search inherits **popularity and recency bias** (CitationNet-LLM notes cold-start; ResearchArena in the reserve found LLM agents *lose* to keyword baselines on discovery).
- Almost no system explains *why* a retrieved paper is relevant in user terms.

**Recommended for ResearchNexus.** Multi-strategy retrieval with transparent fusion: (1) local dense embeddings for chunk-level RAG (MiniLM is acceptable for QA passages); (2) **SPECTER2/SciNCL document embeddings** for "similar paper" discovery; (3) BM25/keyword over titles+abstracts for exact-term robustness; (4) arXiv API category/date filters; (5) **citation edges** (OpenAlex/Semantic Scholar) for foundational/derivative discovery; (6) LLM query expansion from the research profile; (7) **always rerank** the union with an LLM or cross-encoder. Report recall@k against a LitSearch-style RN benchmark (§25).

## 10. Seed-Paper Discovery Analysis (Phase 3A/3B)

### 10.1 Research-profile extraction (Phase 3B) — is a structured paper representation supported by the literature?

**Yes, in pieces.** No reviewed system extracts the full ResearchNexus profile (domain, subtopics, keywords, problem, research questions, methods, models, datasets, evaluation, limitations, future work) as one object, but every field has precedent:

| Profile field | Precedent in the reviewed literature |
|---|---|
| Domain / subtopics | CHIME (topic hierarchies over studies); SciRepEval field-of-study task |
| Keywords / search concepts | LitLLM & "Are we there yet?" (LLM keyword extraction from an abstract); STORM (perspective→question generation) |
| Problem / research questions | ChatCite Key-Element Extractor (problem/method/results per paper); ResearchAgent (problem generation) |
| Methods / models | ArxivDIGESTables (aspect/schema columns are exactly method/model/dataset facets); FacetSum "method" facet |
| Datasets | ArxivDIGESTables value generation; PDFTriage table extraction (dataset tables) |
| Evaluation | FacetSum "findings" facet; SciTLDR |
| Limitations / future work | Multi-XScience related-work framing; ResearchAgent uses "future work" as an idea seed; PaperQA2 contradictions ≈ limitations |

**Recommended for RN.** Extract the profile with a **single structured-output LLM call over section-aware chunks** (abstract, intro, method, experiments, conclusion, "limitations"/"future work" if present), returning strict JSON. Ground every field with a source span (page + offset) so the profile is auditable (RA-FSM's claim→evidence discipline). Use FacetSum-style *typed* fields, not free text. This representation is *emerging* — used implicitly by ChatCite/ArxivDIGESTables, not published as a named artefact.

### 10.2 Discovery strategies — coverage in the literature

| Strategy | Who does it | Maturity |
|---|---|---|
| Semantic similarity (chunk) | PaperQA, PaperQA2, OpenScholar, PaperHelper, ALCE, Self-RAG | Established |
| Semantic similarity (document) | SPECTER2/SciRepEval, CitationNet-LLM | Established |
| Keyword / BM25 | LitSearch, Ai2 Scholar QA (hybrid), LitLLM | Established |
| LLM query expansion | LitLLM, "Are we there yet?", OpenScholar, STORM | Well studied |
| arXiv / API search | LitLLM, Arxiv Copilot, PaSa (search tool) | Established |
| Citation relationships | **PaSa** (expansion), **ResearchAgent** (academic graph), **CitationNet-LLM** (network) | Well studied |
| Method similarity | ArxivDIGESTables (schema aspects) — implicit only | **Less explored** |
| Topic similarity | CHIME, SciRepEval field-of-study | Well studied |
| Research-question similarity | ChatCite key-elements — implicit only | **Potential research opportunity** |
| Multi-hop discovery | PaSa (citation expansion), ResearchAgent (graph walk) | Emerging |

### 10.3 The 14-question seed-paper matrix

For the systems that touch seed/graph discovery (PaSa, ResearchAgent, CitationNet-LLM, SPECTER2, plus the M3SciQA *benchmark* structure and LitLLM/"there yet?" as abstract-seeded proxies):

| # | Capability | PaSa | ResearchAgent | CitationNet-LLM | SPECTER2 | LitLLM(+) | RN target |
|---|---|---|---|---|---|---|---|
| 1 | Start from a single paper | △ (topic) | ✓ | ✓ | ✓ | △ (abstract) | ✓ |
| 2 | Discover related papers automatically | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 3 | Semantic similarity | ✓ | △ | ✓ | ✓ | ✓ | ✓ |
| 4 | Keyword search | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 5 | Citation graph | ✓ | ✓ | ✓ | △ | ✗ | ✓ |
| 6 | LLM-generated search queries | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| 7 | Query expansion | ✓ | △ | ✗ | ✗ | ✓ | ✓ |
| 8 | Academic search agent | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| 9 | Rank related papers | ✓ | △ | ✓ | △ | ✓ | ✓ |
| 10 | Explain relevance per paper | ✗ | △ (concept link) | ✗ | ✗ | ✗ | ✓ |
| 11 | Prioritise recent work | △ | ✗ | △ | ✗ | △ | ✓ |
| 12 | Identify competing approaches | ✗ | △ | ✗ | ✗ | ✗ | ✓ |
| 13 | Multi-hop discovery | ✓ | ✓ | △ | ✗ | ✗ | ✓ |
| 14 | Auto-continue discovery → synthesis | ✗ | ✓ (→ ideas) | ✗ | ✗ | ✓ (→ RW) | ✓ (→ full workspace) |

**Conclusion.** Rows 1–9, 13 are covered somewhere. **Rows 10 (per-paper relevance explanation), 12 (competing-approach identification), and 14 (continuation into a *full* multi-paper workspace with RAG + comparison + gap + directions + citation + slides)** are where ResearchNexus is doing something the reviewed systems do not. Row 11 (recency weighting) is trivially addable and only partially done today.

## 11. Related-Paper Ranking (Phase 3C)

**How the literature ranks candidates.**
- **Single embedding-similarity score:** SPECTER2 (cosine over document embeddings), PaperQA/OpenScholar (chunk similarity). Simple, transparent, but conflates "about the same topic" with "uses the same method".
- **Learned reranker / cross-encoder:** Ai2 Scholar QA (transformer reranker, top-50), LitSearch (LLM rerank +4.4 %). Higher precision, less interpretable.
- **RL-trained relevance policy:** PaSa Selector — a learned judgement of "does this paper answer the query", trained on synthetic labels.
- **Hybrid signal fusion:** CitationNet-LLM combines citation-network proximity with embedding similarity; reported to beat either signal alone on precision/recall/nDCG/MRR.
- **No system publishes calibrated per-signal weights or a per-paper rationale.** "Are we there yet?" reports *normalized recall*; ArxivDIGESTables reports column/value recall; none decompose the ranking.

**Do not invent relevance percentages.** Where a system reports numbers they are retrieval metrics (recall@k, MRR, nDCG) over a labelled set, not confidence scores. ResearchNexus should either (a) surface the underlying retrieval/rerank scores with their provenance, or (b) present **High / Medium / Low** bands defined by score thresholds fixed on a validation set — never a fabricated "87 % relevant".

**Recommended ranking for RN.** A transparent linear (or shallow learned) fusion over normalised sub-scores, each independently displayable:
- `semantic_doc` — SPECTER2 cosine(seed, candidate)
- `semantic_chunk` — max chunk-level similarity (method/results sections weighted)
- `problem_sim` — similarity of profile.`research_problem`/`research_questions` embeddings
- `method_sim` — similarity over profile.`methods`/`models` (a distinct embedding view)
- `citation` — 1/2-hop citation distance (in/out), normalised
- `recency` — monotone function of year (tunable half-life)
- `dataset_overlap` — Jaccard over extracted dataset names
Weights fixed on an RN validation set; the tuple is stored per candidate so the UI can render "*related because: same problem (0.81), shares BEIR benchmark, cites the seed*". This **auditable multi-signal fusion is the less-explored contribution** — CitationNet-LLM fuses two signals opaquely; nobody fuses six and explains them.

## 12. Research Trail Analysis (Phase 3D)

**What a "research trail" needs:** typed edges from the seed — *earlier/foundational*, *similar*, *recent*, *competing*, *method-extension*, *dataset-related*, *potentially-contradictory* — each with supporting evidence.

**Literature coverage of each edge type:**

| Trail edge | Nearest capability in the reviewed set | Status |
|---|---|---|
| Earlier / foundational | Citation graph (in-edges, high age + citation count) — PaSa, ResearchAgent, CitationNet-LLM | Well studied (as citation traversal, not labelled "foundational") |
| Similar | Document embedding similarity — SPECTER2 | Established |
| Recent | Date-filtered search — LitLLM, arXiv API | Established (trivial) |
| Competing | ChatCite comparative summary, ArxivDIGESTables (same task/dataset, different method rows) | **Less explored as an explicit label** |
| Method extension | ArxivDIGESTables schema aspects; ResearchAgent "method" generation | **Less explored** |
| Dataset-related | ArxivDIGESTables value generation; extracted dataset names | Emerging |
| Potentially contradictory | **PaperQA2 / ContraCrow**; SciFact (F5) claim verification | Emerging (contradiction *detection* exists; labelled *trail edge* does not) |

**Gap.** Every reviewed system produces a **flat ranked list** (PaSa, CitationNet-LLM, LitSearch) or a **topic hierarchy** (CHIME). None assigns a **relationship type** between the seed and each discovered paper. The building blocks exist — citation direction+age for "foundational", same-dataset-different-method for "competing", NLI/claim-check for "contradictory", schema-aspect diff for "method extension" — but assembling them into a **typed, evidence-carrying trail** is not demonstrated. This is a concrete, testable ResearchNexus contribution (§21, §22).

**Recommended for RN.** Compute the edge type with a deterministic rules layer first (citation direction + year → foundational/derivative; shared dataset + different method section → competing; year within N months → recent; high `method_sim` + cites seed → method-extension), then an LLM confirmation pass that must cite spans from both papers, then a confidence label. Keep the human-in-the-loop confirm step (CHIME's corrector lesson).

## 13. RAG Analysis

**Consensus pipeline across the strong systems (PaperQA2, OpenScholar, Ai2 Scholar QA, SurveyForge):**
1. **Retrieve** top-k dense (k typically small; exact k rarely reported);
2. **Rerank** with an LLM or cross-encoder;
3. **Contextualise** — LLM summarises/filters each retained chunk to remove distractors (PaperQA2's explicit step);
4. **Generate section-by-section**, each section conditioned on prior sections and pulling its own evidence (SurveyForge SANA, Ai2 Scholar QA);
5. **Attach citations per claim**;
6. optionally **self-feedback / re-retrieve** (OpenScholar, Self-RAG).

**Structure-aware and graph-aware variants.** PDFTriage retrieves by document *structure* (go to Table 3), not just similarity — important for "what dataset / what hyper-parameters". GraphRAG retrieves over an entity/community *graph* for corpus-level questions ("what's missing?") that top-k cannot serve.

**Chunking.** No reviewed paper converges on a single chunk size; the consensus is that **fixed-size character chunking fragments scientific context** and that **section-aware / semantic chunking** helps (PDFTriage, data-science RAG reserve, and the reserve chunking-strategies study). ResearchNexus's stated ~800-token / 120-overlap recursive chunking is a reasonable default but should be A/B-tested against section-aware chunking (§25).

**Recommended RN RAG.** Section-aware chunking + a small structure index (sections, tables, dataset mentions); top-k dense (start k≈8) → cross-encoder rerank → per-chunk contextual filter → structured generation with per-claim citations → Self-RAG-style `IsSupported?` verification prompt → RAGAs faithfulness gate before display. For research-gap and "themes" questions, route to a lightweight per-workspace GraphRAG instead of flat top-k.

## 14. LLM Analysis

- **Prompted frontier models dominate.** PaperQA, PaperQA2, Ai2 Scholar QA (Claude 3.5/3.7), ArxivDIGESTables, ChatCite, GraphRAG, ResearchAgent, STORM all use prompted GPT-4 / Claude-class models with no fine-tuning. This matches ResearchNexus's BYOK / multi-provider design.
- **Fine-tuning is used where a capability must be *cheap and reliable*:** OpenScholar-8B (trained synthesiser + retriever), Self-RAG (reflection-token training), PaperHelper (RAFT), PaSa-7B (RL), SciLitLLM (CPT+SFT). All show a small open model can match or beat a large prompted model on the *specific* task — but each needs a training pipeline RN will not have per user.
- **Model choice materially changes citation behaviour.** OpenScholar reports GPT-4o hallucinating citations 78–90 % of the time on scientific synthesis; "Do LMs Know When They're Hallucinating References?" shows models are internally inconsistent on fabricated refs. Implication: RN must **not** rely on the LLM to produce citations — build them deterministically from retrieved metadata and *check* them.
- **Known limitations across the corpus:** long-context degradation on full papers (AutoSurvey, ALCE), parametric-knowledge staleness (LitLLM's motivation), weak cross-document reasoning (M3SciQA: 18 models ≪ humans), unreliable self-evaluation (Si et al. reserve; ResearchAgent).

**Recommended RN LLM policy.** Provider-agnostic prompts; a capability probe on connect (structured-output support, context length, streaming); deterministic citation construction; verification prompts rather than trust; per-feature temperature (≈0.2 extraction/compare, ≈0.3 chat, ≈0.2 gap with mandatory evidence). Document that quality varies by chosen provider and report it.

## 15. Agentic AI Analysis

**Applying the strict test (LLM app / RAG app / Agentic tool-use / Agentic multi-agent):**

| Class | Reviewed systems | Notes |
|---|---|---|
| LLM application | CHIME (+ trained corrector) | single structured call; corrector is a separate model |
| RAG application (fixed flow) | Ai2 Scholar QA, PaperHelper, LitLLM, "Are we there yet?", ArxivDIGESTables, AutoSurvey, GraphRAG, ALCE, M3SciQA setups | retrieve→(rerank)→generate; no tool *selection* |
| Agentic — tool-use / iteration / self-critique | PaperQA, PaperQA2, OpenScholar, RA-FSM, SurveyForge (SANA), PDFTriage (triage fns), Self-RAG (reflection), ChatCite (reflection loop) | model decides to retrieve/expand/stop; may iterate |
| Agentic — multi-agent | PaSa (Crawler+Selector), ResearchAgent (generator+ReviewingAgents), STORM (perspective+expert), SciAgents (reserve) | ≥2 coordinated roles |

**Findings.**
- "Agentic" in this corpus almost always means **one model with tools + a stop policy** (PaperQA line) or **2–3 fixed roles** (PaSa, ResearchAgent). No reviewed system runs a large open-ended agent swarm, and the Agentic-RAG survey (B4) recommends against it.
- The genuinely agentic behaviours demonstrated are: **iterative retrieval / citation expansion** (PaperQA2, PaSa), **self-evaluation / answerability gating** (RA-FSM, Self-RAG), **reflective incremental synthesis** (ChatCite), **per-section retrieval agents** (SurveyForge), **review-and-revise loops** (ResearchAgent).
- **Chatbot ≠ agent:** Arxiv Copilot (reserve) and many "chat with your paper" tools are RAG apps with memory, not agents.

**Recommended RN agent design.** A **single Research Orchestrator** that owns a typed tool set (parse_pdf, extract_profile, plan_search, search_* , dedupe_filter, verify_evidence, rank, type_edges, rag_answer, compare, find_gaps, gen_directions, gen_citations, gen_outline) and a bounded plan; deterministic code for parsing/dedup/citation formatting/FAISS; LLM calls for extraction/synthesis/typing/gap; a Self-RAG-style verification pass; RA-FSM-style answerability gating and "I don't know". No multi-agent swarm. This is "minimal meaningful agentic" per the brief and matches what actually works in the literature (§24, architecture doc).

---

## 16. Multi-Paper Analysis (Phase 3E)

| Capability | Reviewed support | Status |
|---|---|---|
| Multi-paper retrieval | PaperQA2, OpenScholar, Ai2 Scholar QA, GraphRAG, M3SciQA | Established |
| Multi-paper QA | M3SciQA (benchmark), PaperQA2, OpenScholar, GraphRAG (global) | Well studied — but **models ≪ humans** (M3SciQA) |
| Cross-paper synthesis | AutoSurvey, SurveyForge, STORM, SciReviewGen, Multi-XScience | Established (as survey/related-work generation) |
| Paper comparison | **Ai2 Scholar QA, ArxivDIGESTables, ChatCite** | Well studied (tables + comparative summary) |
| Method / dataset / result comparison | ArxivDIGESTables (schema aspects), FacetSum facets | Emerging |
| Contradiction detection | **PaperQA2 / ContraCrow**, SciFact (F5) | Emerging |
| Research-trend analysis | CHIME (hierarchies), GraphRAG (themes), survey generators | Emerging |
| Persistent, user-editable multi-paper workspace | — | **Not demonstrated** |

**What is missing from existing systems.**
1. **A persistent workspace.** Comparisons and syntheses are produced *inside a single answer* (Ai2 Scholar QA) or *as a one-shot artefact* (ArxivDIGESTables). No reviewed system keeps a user-curated set of papers with per-paper profiles that persists across summarise / compare / QA / gap operations.
2. **Comparison grounded in extracted profiles, not raw text.** ChatCite extracts key elements then compares — the right idea — but does not expose the per-paper profile as a first-class object the user can inspect/correct.
3. **Comparison + gap in one flow.** Comparison outputs (Ai2 Scholar QA, ArxivDIGESTables) and gap/idea outputs (ResearchAgent, PaperQA2) come from different systems; nothing turns "these 5 papers all use dataset X but none report latency" *directly* into a gap statement.
4. **Uploaded-PDF + discovered-abstracts asymmetry.** RN's realistic case is one full-text seed + many abstract-only related papers; reviewed comparison work assumes uniform (usually abstract-level) inputs.

**Recommended for RN.** A workspace object = {seed profile (full-text-grounded), related-paper profiles (abstract-grounded, flagged as such), typed edges, chat history, generated artefacts}. Comparison operates over the *profiles*; every cell cites a span; DecontextEval-style checking in CI.

## 17. Citation Analysis

**Capabilities in the literature.**
- **Citation-grounded generation:** ALCE (S23) defines the benchmark and metrics (citation precision/recall via NLI); OpenScholar and Self-RAG show it is *learnable* to near-human accuracy; PaperQA/PaperQA2 attach citations per claim.
- **Citation *evaluation*:** ALCE, RAGAs (faithfulness ≈ grounding), OpenScholar's citation-accuracy metric, "Do LMs Know When They're Hallucinating References?" (reserve) as a hallucination probe.
- **Deterministic citation construction:** RA-FSM (S6) builds citations from an in-corpus, de-duplicated reference set with confidence labels — *not* from the LLM.
- **Citation as a *retrieval* signal:** CitationNet-LLM, PaSa (expansion), ResearchAgent (graph).

**The consistent finding:** letting an LLM *write* bibliographic references is unsafe — GPT-4o hallucinates citations 78–90 % of the time on scientific synthesis (OpenScholar); models are internally inconsistent on fabricated refs (reserve R12). Citation *placement* (which retrieved passage supports this sentence) is reliable when constrained to retrieved context (ALCE, Self-RAG).

**Recommended for RN.**
1. **Never** let the LLM emit reference strings. Build APA/IEEE/BibTeX **deterministically** from arXiv / Crossref / OpenAlex metadata for papers actually in the workspace (RA-FSM pattern; matches RN's existing plan).
2. For every generated sentence in a summary / answer / comparison / gap, attach the **retrieved chunk id(s)** it is grounded in; run an ALCE-style citation-precision/recall check and a Self-RAG `IsSupported?` pass; drop or visibly flag unsupported sentences.
3. Show the supporting excerpt on hover (Ai2 Scholar QA pattern) for traceability.
4. Report citation precision/recall and hallucinated-reference rate (target ~0) as headline metrics (§25).

## 18. Research-Gap Analysis (Phase 3F)

**What the literature actually does under "gap / future work / ideas":**
- **Contradiction detection** — PaperQA2 / ContraCrow: for each claim, find papers that disagree. Closest to an evidence-grounded gap, but pairwise and not framed as an opportunity.
- **Idea generation** — ResearchAgent (problems/methods/experiments from a core paper + graph; ReviewingAgents refine); Si et al. (reserve) show LLM ideas are rated *more novel* than experts' but *less feasible*, and LLM self-evaluation of ideas is unreliable.
- **Theme / tension surfacing** — GraphRAG global queries ("what are the main tensions?"), CHIME hierarchies (sparse branches ≈ under-studied areas).
- **"Future work" extraction** — implicit in Multi-XScience / SciReviewGen related-work framing.
- **Claim verification** — SciFact (F5): SUPPORT/REFUTE with rationales — the mechanism for *evidence* behind a gap.

**None produce the ResearchNexus gap object:** *{gap statement; supporting papers; evidence spans; why existing work does not address it; confidence; proposed research direction}*.

**Recommended RN research-gap procedure (evidence-grounded, hallucination-resistant):**
1. **Structured inputs, not free reasoning.** Build a matrix over the workspace: rows = papers, columns = {problem, method, dataset, metric reported, limitation stated, future-work stated} (ArxivDIGESTables method; FacetSum facets).
2. **Candidate gaps from the matrix by rule:** e.g. "≥3 papers target problem P; none report metric M / none evaluate on dataset D / all share limitation L".
3. **Evidence assembly:** for each candidate, attach the exact rows/spans (SciFact-style rationale); require ≥2 supporting papers or the candidate is dropped.
4. **LLM articulation, constrained:** the model may only phrase the gap and propose a direction; it may not introduce claims without a cited span (RA-FSM discipline).
5. **Confidence label** from: number of supporting papers, agreement of their limitations, recency, and a Self-RAG `IsSupported?` check on the gap statement itself. Bands High/Medium/Low — **no invented percentages**.
6. **Contradiction gaps** via a ContraCrow-style pass: claims in the seed that other workspace papers refute.
7. **Human-in-the-loop:** present gaps as *candidates* for the user to accept/reject (CHIME corrector lesson).

This structured, evidence-first, confidence-labelled gap object is the **strongest single novelty candidate** for ResearchNexus — the components exist but the artefact does not.

## 19. Evaluation Comparison

**How the field evaluates each capability (what RN should adopt):**

| Capability | Standard datasets | Standard metrics | RN adoption |
|---|---|---|---|
| Scholarly retrieval / discovery | LitSearch; AutoScholarQuery/RealScholarQuery (PaSa); SciRepEval search tasks | recall@k, nDCG, MRR | Build an RN discovery set (seed→relevant) ; report recall@k, MRR |
| Single-paper QA | QASPER (F1); QASPER-evidence | answer F1, evidence F1 | Use QASPER + an RN uploaded-PDF set |
| Multi-paper QA | M3SciQA; ScholarQABench | accuracy, MRR (anchor) | Evaluate the seed+trail QA path on M3SciQA-style clusters |
| RAG faithfulness | WikiEval (RAGAs); ALCE | faithfulness, answer/context relevance, citation P/R | RAGAs + ALCE-style citation P/R on every generation |
| Summarisation | SciTLDR, Multi-XScience, FacetSum, SciReviewGen | ROUGE, BERTScore, human, faithfulness | ROUGE/BERTScore + human + RAGAs faithfulness |
| Comparison tables | arxivDIGESTables | DecontextEval, column/value recall | DecontextEval in CI on RN comparison output |
| Survey / synthesis | SurveyBench (SurveyForge); AutoSurvey protocol | citation recall/precision; coverage/structure/relevance | citation recall/precision + expert rubric |
| Idea / gap quality | ResearchAgent protocol; Si et al. blind review | expert novelty/validity/feasibility; agreement | blind expert review of RN gaps + evidence-support check |
| Citation integrity | ALCE; OpenScholar citation accuracy; R12 probe | citation P/R; fabricated-ref rate | fabricated-ref rate (target ~0); citation P/R |
| Efficiency | (rarely reported — PaperHelper latency; GraphRAG token cost) | latency, tokens, cost | report per stage — RN differentiator (few papers do) |

**Observation.** The field evaluates *stages*, never the *whole workflow*. ResearchNexus should define a **composite workflow score** (§25) — discovery recall × trail-typing accuracy × QA faithfulness × comparison DecontextEval × gap expert-rating × citation integrity — as a methodological contribution in its own right.

## 20. Limitations of Existing Work (cross-cutting)

Recurring across the 25 primary papers:

1. **Query-seeded, not paper-seeded.** The strongest synthesis systems (OpenScholar, PaperQA2, Ai2 Scholar QA, AutoSurvey, SurveyForge) start from a question or topic. Seed-*paper* profiling is only in ResearchAgent (→ ideas) and, loosely, LitLLM (→ related-work).
2. **Flat lists, not typed trails.** Discovery output is a ranked list (PaSa, CitationNet-LLM, LitSearch) or a topic tree (CHIME). No relationship typing (foundational/competing/extension/contradictory).
3. **No per-paper relevance explanation.** Users get a score or rank, not a reason.
4. **Gaps are prose or contradictions, not structured objects.** No {statement + support + evidence + confidence + direction}.
5. **Stage evaluation only.** No end-to-end workflow evaluation; efficiency (latency/tokens/cost) rarely reported.
6. **Domain-narrow benchmarks.** Recent ML/NLP (LitSearch, M3SciQA, LitQA) or biology (PaperQA2) — generalisation untested.
7. **Citation hallucination remains the dominant risk.** 78–90 % for GPT-4o on scientific synthesis (OpenScholar); mitigations (deterministic build, ALCE checks, Self-RAG verification) are known but not standard.
8. **PDF structure extraction is assumed, not solved.** PDFTriage relies on it; scanned/multi-column/equation-heavy PDFs still break parsers (Nougat, MinerU are partial fixes).
9. **Cross-document reasoning is weak.** M3SciQA: 18 foundation models far below humans.
10. **Fine-tuned systems don't transfer to a BYOK setting.** OpenScholar-8B, Self-RAG, PaSa-7B, PaperHelper each need a training pipeline RN cannot run per user.
11. **Persistent multi-paper workspaces are absent.** Everything is one-shot.
12. **Reproducibility varies.** Preprints with closed corpora (PaperQA2 datastore, Ai2 corpus) are hard to reproduce exactly; benchmarks (QASPER, LitSearch, ArxivDIGESTables, M3SciQA, SciRepEval) are the reproducible core.

## 21. ResearchNexus Research Gap (Phase 6)

**The proposed workflow:** Seed Paper → Understand → Research Profile → Discover Related Papers → Rank → Research Trail → Multi-Paper Workspace → RAG → Compare → Research Gap → Research Directions → Citation → Presentation.

**Is this complete workflow already provided by existing research? No — not as one system.** Component-by-component:

| Stage | Individually established? | By whom | Integrated with the rest? |
|---|---|---|---|
| Seed-paper understanding / profile | **Emerging** (implicit) | ChatCite (key elements), ArxivDIGESTables (aspects), ResearchAgent | Not as a named, auditable artefact |
| Search-concept generation | **Established** | LitLLM, "there yet?", STORM, OpenScholar | Yes, within those tools |
| Related-paper discovery (multi-strategy) | **Established per strategy; well studied combined** | PaSa (agent+citation), CitationNet-LLM (citation+semantic), LitSearch (dense) | Partially — PaSa combines search+citation but not semantic-doc + method + RQ |
| Ranking | **Established** | Ai2 Scholar QA reranker, PaSa Selector, CitationNet-LLM fusion | Yes, but opaque / single-view |
| Per-paper relevance explanation | **Less explored** | — (concept links in ResearchAgent) | No |
| Typed research trail | **Less explored** | CHIME (topic only); contradiction detection (PaperQA2) | No |
| Multi-paper workspace (persistent) | **Not demonstrated** | — | No |
| Multi-paper RAG / QA | **Well studied** | PaperQA2, OpenScholar, M3SciQA, GraphRAG | Yes (query-seeded) |
| Summarisation / key points | **Established** | AutoSurvey, SciTLDR, FacetSum, ChatCite | Yes |
| Comparison | **Well studied** | ArxivDIGESTables, Ai2 Scholar QA, ChatCite | Yes, one-shot |
| Research-gap (evidence-grounded, confidence-labelled) | **Potential research opportunity** | ContraCrow (contradictions), ResearchAgent (ideas), GraphRAG (themes) | No |
| Research directions | **Emerging** | ResearchAgent, Si et al. | Not from an evidence matrix |
| Citation generation | **Established** (deterministic) + **well studied** (grounding) | RA-FSM, ALCE, OpenScholar | Yes |
| Presentation outline | **Established** (as outline generation) | AutoSurvey, SurveyForge, STORM | Not as slides from a workspace |
| **End-to-end agentic workflow** | **Not demonstrated** | closest: ResearchAgent (paper→ideas), PaSa (query→papers) | **No** |

**Evidence-based statement of the gap** (per the brief's required framing):

> *"Existing studies commonly address scientific RAG and QA (PaperQA/PaperQA2, OpenScholar, M3SciQA), citation-grounded synthesis (OpenScholar, ALCE, Self-RAG), scholarly retrieval (LitSearch, SPECTER2), automated survey and related-work generation (AutoSurvey, SurveyForge, STORM, LitLLM), and comparison-table synthesis (ArxivDIGESTables, Ai2 Scholar QA) as separate capabilities, and a few recent agents automate paper discovery from a query or a core paper (PaSa, ResearchAgent). Comparatively few studies integrate seed-paper research-profile extraction, multi-strategy discovery, transparent multi-signal ranking with per-paper relevance explanations, a typed research trail, a persistent multi-paper workspace, and evidence-grounded confidence-labelled research-gap identification into one interactive agentic workflow, and — to our knowledge — none evaluate such a workflow end-to-end rather than stage-by-stage."*

**What is NOT novel (must be stated plainly):** RAG QA over papers, FAISS, local embeddings, LLM summarisation, dense scholarly retrieval, comparison tables, citation grounding, outline generation, and even agentic paper search are all established or well studied. ResearchNexus is **not** novel for using these.

**Where a defensible contribution exists (integration + four capabilities):**
1. **Auditable multi-signal related-paper ranking** with per-paper, per-signal relevance explanations (vs opaque single-score / two-signal ranking).
2. **Typed research trail** (foundational / similar / recent / competing / method-extension / dataset-related / contradictory) with evidence, vs flat lists / topic trees.
3. **Evidence-grounded, confidence-labelled research-gap objects** built from a structured cross-paper matrix, vs contradiction detection / free-text "future work".
4. **End-to-end, human-in-the-loop workflow from one uploaded paper to slides, evaluated as a whole** — with a composite metric — vs stage-wise systems and stage-wise evaluation.

## 22. Novelty Assessment (Phase 7)

Classification: **Established** (mature, many implementations) · **Well studied** (multiple strong 2023–2025 works) · **Emerging** (appears 2024–2025, not yet standard) · **Less explored** (isolated attempts) · **Potential research opportunity** (components exist, artefact/combination does not).

| # | ResearchNexus feature | Classification | Evidence |
|---|---|---|---|
| 1 | Academic paper search (arXiv/API) | **Established** | LitLLM, Arxiv Copilot, PaSa search tool, arXiv API ubiquitous |
| 2 | Semantic / embedding search | **Established** | SPECTER2/SciRepEval, LitSearch, all RAG systems |
| 3 | Seed-paper upload as the entry point | **Emerging** | ResearchAgent (core paper), M3SciQA (anchor); most systems are query-seeded |
| 4 | Automatic related-paper discovery (multi-strategy) | **Well studied per strategy; Emerging as a fused multi-strategy pipeline** | PaSa (search+citation), CitationNet-LLM (citation+semantic); nobody fuses semantic-doc + method + RQ + citation + keyword + expansion |
| 5 | Structured research profile from a paper | **Emerging / Less explored as a named artefact** | ChatCite key elements, ArxivDIGESTables aspects, FacetSum facets — all implicit |
| 6 | Related-paper ranking | **Established (ranking) / Less explored (transparent multi-signal + explanation)** | rerankers everywhere; CitationNet-LLM fuses 2 signals opaquely; no per-paper reason |
| 7 | Typed research trail | **Less explored** | CHIME (topic only); contradiction detection exists; no relationship typing |
| 8 | PDF RAG | **Established** | PaperQA, PaperHelper, PDFTriage |
| 9 | FAISS vector index | **Established** | standard; not novel |
| 10 | Local embeddings (MiniLM) | **Established** | standard; SPECTER2 is the scholarly upgrade |
| 11 | LLM summarisation | **Established** | SciTLDR, AutoSurvey, all systems |
| 12 | Key-point extraction | **Well studied** | FacetSum, ChatCite, Scim (reserve) |
| 13 | Paper QA (single) | **Established** | QASPER, PaperQA, PaperHelper |
| 14 | Multi-paper comparison | **Well studied** | ArxivDIGESTables, Ai2 Scholar QA, ChatCite |
| 15 | Research-gap identification (evidence-grounded, confidence-labelled) | **Potential research opportunity** | ContraCrow (contradictions), GraphRAG (themes), ResearchAgent (ideas) — no structured gap object |
| 16 | Research-idea / direction generation | **Emerging** | ResearchAgent, Si et al. (reserve) |
| 17 | Citation generation (deterministic) | **Established** | RA-FSM; standard metadata formatting |
| 18 | Citation verification / grounding | **Well studied** | ALCE, Self-RAG, OpenScholar, R12 |
| 19 | Presentation-outline generation | **Established (outline) / Less explored (slides from a multi-paper workspace)** | AutoSurvey/SurveyForge/STORM generate outlines, not slide decks from a curated set |
| 20 | Agentic orchestration | **Well studied (patterns) / Emerging (for this task)** | PaperQA line, PaSa, ResearchAgent, RA-FSM, Self-RAG |
| 21 | End-to-end research workflow (seed → slides), human-in-the-loop, evaluated whole | **Potential research opportunity** | no reviewed system spans it or evaluates it end-to-end |

**Summary:** 9 features Established, 4 Well studied, 4 Emerging, 2 Less explored, **2 Potential research opportunity** (#15 evidence-grounded gap object, #21 evaluated end-to-end workflow), with #4/#6/#7/#19 being "less explored" in their *transparent/typed/workspace* form. ResearchNexus's contribution narrative should rest on #15, #21, and the transparent/typed forms of #4, #6, #7.

## 23. ResearchNexus vs Existing Systems

| Dimension | Best existing system(s) | What they do | What ResearchNexus adds |
|---|---|---|---|
| Entry point | ResearchAgent (core paper) | paper → research ideas | paper → **profile → discovery → workspace → synthesis → slides** |
| Discovery | PaSa (agent + citation), CitationNet-LLM (citation + semantic) | ranked list of papers | **multi-strategy fusion + per-paper typed relationship + relevance explanation** |
| Ranking | Ai2 Scholar QA reranker, PaSa Selector | opaque relevance score | **transparent multi-signal fusion, each signal shown** |
| Trail | CHIME (topic hierarchy) | topic tree of a given set | **typed edges (foundational/competing/extension/dataset/contradictory) with evidence** |
| Workspace | — | (none persistent) | **persistent curated multi-paper workspace with editable per-paper profiles** |
| Multi-paper QA | PaperQA2, OpenScholar, GraphRAG | query → cited synthesis | same, but **seeded by the trail** and inside the workspace |
| Comparison | ArxivDIGESTables, Ai2 Scholar QA | one-shot comparison table | comparison over **extracted profiles**, cited per cell, re-runnable in the workspace |
| Research gap | PaperQA2/ContraCrow (contradictions), ResearchAgent (ideas) | pairwise contradictions / free ideas | **structured gap objects: statement + support + evidence + confidence + direction** |
| Citation | OpenScholar, RA-FSM, ALCE | grounded / deterministic + checked | same (adopt best practice) — deterministic build + ALCE/Self-RAG checks |
| Presentation | AutoSurvey/STORM (outline) | topic outline | **slide outline from the workspace**, cited |
| Evaluation | stage benchmarks (LitSearch, QASPER, ArxivDIGESTables, M3SciQA, RAGAs) | per-stage metrics | **composite end-to-end workflow score** + per-stage metrics |
| Cost/latency | rarely reported | — | **reported per stage** (BYOK cost transparency) |
| Deployment model | mostly research prototypes / one closed app | fixed model, closed corpus | **BYOK multi-provider, user-uploaded + arXiv corpus, open workflow** |

**Honest positioning sentence for the paper:** *"ResearchNexus does not introduce a new retriever, embedding model, or LLM; its contribution is the integration of seed-paper profiling, transparent multi-strategy discovery, a typed research trail, and evidence-grounded gap analysis into one human-in-the-loop workflow, together with an end-to-end evaluation that the literature currently performs only stage-by-stage."*

---

## 24. Recommended Architecture (literature-grounded)

Mapping the reviewed evidence onto the ResearchNexus pipeline. Full design in `docs/architecture/ResearchNexus_Seed_Paper_Research_Trail.md`.

| Stage | Papers that inform it | Dominant approach | Weakness to avoid | Recommended for ResearchNexus |
|---|---|---|---|---|
| PDF extraction / cleaning | PDFTriage, Nougat, MinerU (reserve) | layout-aware parsing → structured tree | assuming clean text; losing tables/sections | `pypdf`/`pdfplumber` baseline + optional Nougat/MinerU for hard PDFs; keep section map + table blocks |
| Chunking | PDFTriage, data-science RAG (reserve), chunking-strategies study (reserve) | section-aware / semantic | fixed-size char chunks fragment context | section-aware chunks (~600–900 tokens) + small structure index; A/B vs recursive (§25) |
| Seed-paper profile | ChatCite, ArxivDIGESTables, FacetSum, ResearchAgent | LLM structured extraction over key sections | free-text fields; no provenance | one strict-JSON LLM call over {abstract, intro, method, experiments, conclusion, limitations}; each field carries a source span |
| Search-concept generation | LitLLM, "there yet?", STORM, OpenScholar | LLM keyword + query expansion; multi-perspective questions | over-narrow keywords | generate keyword sets + expanded queries + "perspective" questions from the profile |
| Discovery | PaSa, CitationNet-LLM, LitSearch, SPECTER2 | agent search + citation expansion; hybrid dense+sparse; doc embeddings | single strategy; popularity/recency bias | run 6 strategies (semantic-chunk, semantic-doc/SPECTER2, BM25, arXiv API, 1–2-hop citations, LLM-expanded queries); union + dedup |
| Ranking | Ai2 Scholar QA, PaSa Selector, CitationNet-LLM, "there yet?" | cross-encoder / learned relevance / 2-signal fusion | opaque; single view | transparent linear fusion over {semantic_doc, semantic_chunk, problem_sim, method_sim, citation, recency, dataset_overlap}; store the tuple; **always rerank** |
| Relevance explanation | (gap) | — | — | template from the score tuple + one LLM sentence citing both papers' spans |
| Typed trail | CHIME, PaperQA2/ContraCrow, ArxivDIGESTables, SciFact | topic hierarchy; contradiction detection | topic-only; no relationship type | deterministic rules (citation dir+year, shared dataset+diff method, recency) → LLM confirmation with spans → confidence band; human confirm |
| Multi-paper workspace | (gap) | — | one-shot artefacts | persistent object {seed profile, related profiles (flagged abstract-only), edges, chat, artefacts} |
| Multi-paper RAG / QA | PaperQA2, OpenScholar, SurveyForge, PDFTriage, GraphRAG | retrieve→rerank→contextual-filter→structured gen→verify; structure-aware; graph for global Qs | flat top-k for "what's missing" | k≈8 dense → cross-encoder rerank → per-chunk filter → structured gen with per-claim citations → Self-RAG `IsSupported?` → RAGAs faithfulness gate; **route gap/theme questions to a per-workspace GraphRAG** |
| Summarise / key points | AutoSurvey, SciTLDR, FacetSum, ChatCite | map-reduce / faceted extraction | unfaithful compression | map-reduce for long papers; FacetSum-typed key points; faithfulness-checked |
| Comparison | ArxivDIGESTables, Ai2 Scholar QA, ChatCite | schema→value; extract-then-compare | hallucinated cells | compare over profiles; schema from union of method/dataset/metric fields; every cell cites a span; DecontextEval in CI |
| Research gap | ContraCrow, GraphRAG, ResearchAgent, SciFact | contradiction / theme / idea | free-text; unverifiable | structured matrix → rule-derived candidates → evidence assembly (≥2 papers) → constrained LLM phrasing → confidence band → human accept/reject |
| Research directions | ResearchAgent, Si et al. (reserve) | LLM idea generation + review | over-novel, infeasible; unreliable self-eval | derive from accepted gaps only; ReviewingAgent-style critique pass; label feasibility as uncertain |
| Citation generation | RA-FSM, ALCE, OpenScholar | deterministic build + grounding checks | LLM-written references (78–90% hallucination) | deterministic APA/IEEE/BibTeX from metadata of workspace papers only; ALCE citation P/R on generated text |
| Presentation outline | AutoSurvey, SurveyForge, STORM | outline heuristics | ungrounded slides | slide outline from workspace artefacts; each bullet cites a paper |
| Orchestration | PaperQA line, PaSa, ResearchAgent, RA-FSM, Self-RAG, B4 | single agent + tools + stop policy; 2–3 roles max | agent swarm; unbounded loops | one Research Orchestrator, typed tools, bounded plan, deterministic code for parse/dedup/cite/FAISS, verification pass, answerability gating, "I don't know" |
| Evaluation | LitSearch, QASPER, M3SciQA, ArxivDIGESTables, RAGAs, ALCE, SurveyBench | per-stage benchmarks | no whole-workflow metric | per-stage metrics **plus** a composite workflow score (§25) |

## 25. Recommended Experiments (Phase 8)

All experiments use **user-provided / BYOK LLM keys**; report provider and version with every result. Do not fabricate relevance percentages — every number must come from a labelled set or a named metric.

### 25.1 Related-paper discovery

Compare strategies **A** keyword/BM25 · **B** dense semantic (chunk) · **B2** dense semantic (SPECTER2 document) · **C** citation-based (1–2 hop, OpenAlex/Semantic Scholar) · **D** hybrid (A+B2+C) · **E** LLM-generated queries + expansion · **F** agentic search (PaSa-style crawler+selector over A–E).

- **Data:** an RN discovery benchmark — take N seed papers with known "related" sets from their own reference lists + citing papers + author-curated additions (LitSearch / AutoScholarQuery construction method). Hold out a human-judged subset.
- **Metrics:** Precision@{5,10,20}, Recall@{10,20,50}, MRR, nDCG@10; **diversity** (mean pairwise SPECTER2 distance of the top-k); **recency** (median age vs corpus); **expert relevance** (blind High/Med/Low on a sample).
- **Expected pattern from the literature:** B2/C beat A (LitSearch: dense +24.8 R@5); D beats any single strategy; F adds recall at higher cost (PaSa +38 R@20 but multi-call). Report the recall gain of D and F over the best single strategy, and the cost.

### 25.2 RAG (QA over the workspace)

- **Metrics:** RAGAs faithfulness, answer relevance, context relevance; ALCE citation precision/recall; hallucination rate (unsupported-sentence %); QA correctness on QASPER (single-paper) and an M3SciQA-style anchor+trail set (multi-paper); evidence F1.
- **Ablations:** ± rerank; ± per-chunk contextual filter; ± Self-RAG `IsSupported?` gate; top-k ∈ {3,5,8,12}; chunking {recursive-800/120, section-aware}; embedding {MiniLM, SPECTER2, BGE/E5}; with vs without RAG (closed-book LLM).

### 25.3 Summarisation & key points

- **Metrics:** ROUGE-1/2/L and BERTScore vs SciTLDR / FacetSum / author abstracts; RAGAs faithfulness; expert Likert (accuracy, coverage, usefulness); FacetSum per-facet ROUGE for typed key points.
- **Ablations:** single-pass vs map-reduce; temperature; typed vs free-text key points.

### 25.4 Multi-paper comparison

- **Metrics:** DecontextEval (aspect alignment) and column/value recall vs a reference table (arxivDIGESTables method); evidence coverage (% cells with a valid supporting span); citation accuracy per cell; contradiction-detection precision/recall vs a small SciFact-style labelled set.
- **Ablations:** compare over raw text vs extracted profiles; schema given vs generated.

### 25.5 Research gap

- **Metrics:** expert relevance (blind High/Med/Low, ≥2 raters, report agreement/κ); evidence-support rate (% gap statements with ≥2 cited papers and valid spans); novelty (expert: is this genuinely under-addressed?); consistency (same gaps on re-run, same seed); hallucination rate (claims in the gap not supported by a cited span); calibration of the confidence band vs expert agreement.
- **Baseline comparison:** RN structured-matrix gaps vs (i) "ask GPT-4 for research gaps" free-text, (ii) ContraCrow-style contradictions only, (iii) GraphRAG "what is missing?" prose.

### 25.6 Performance / efficiency (an RN differentiator — rarely reported in the literature)

- Latency per stage (profile, discovery, rank, trail-typing, one RAG answer, comparison, gap); end-to-end wall-clock for a 1-seed → 20-paper workspace.
- Token usage and **USD cost** per stage and end-to-end, by provider.
- FAISS: index build time and retrieval latency vs #papers ∈ {5, 20, 50, 100} and #chunks; memory footprint on a `t3.small`-class box.
- Scaling: quality and latency vs workspace size.

### 25.7 Agentic vs non-agentic

- RN full orchestrated workflow vs a fixed-pipeline (no tool selection, no verification, no answerability gating) on: discovery recall, QA faithfulness, gap expert-rating, citation integrity, latency, cost. Isolates the value of the agentic layer (the brief's requested comparison).

### 25.8 Composite workflow score

Define `W = w1·norm(Recall@20) + w2·norm(trail-typing F1) + w3·norm(faithfulness) + w4·norm(DecontextEval) + w5·norm(gap expert-rating) + w6·(1 − fabricated-ref rate)`, weights fixed a priori, reported alongside the components. Present `W` for RN and for each baseline below.

### 25.9 Baselines

| Baseline | What it is | What it isolates / evaluates |
|---|---|---|
| **B1 — Keyword academic search** | BM25/arXiv keyword search from the seed title+abstract, no LLM | floor for discovery; shows the value of semantics |
| **B2 — Dense semantic search** | SPECTER2/embedding kNN from the seed, no rerank | value of scientific document embeddings over keywords |
| **B3 — Citation-based discovery** | 1–2-hop citation neighbours (OpenAlex), ranked by citation proximity | value and bias (popularity/recency) of the citation signal alone |
| **B4 — Hybrid semantic + citation** | union of B2 + B3 with score fusion, no LLM rerank | value of fusing signals before any LLM |
| **B5 — Standard RAG** | top-k dense + single LLM generation, no rerank/verify | baseline QA/synthesis quality and faithfulness |
| **B6 — RAG + reranking** | B5 + cross-encoder rerank + per-chunk filter | isolated value of rerank/contextualisation (cf. "there yet?" doubling recall) |
| **B7 — LLM academic search** | "ask the LLM to list related papers / gaps" directly, no retrieval | quantifies hallucination risk without grounding (cf. OpenScholar 78–90%) |
| **B8 — Agentic academic search** | PaSa-style crawler+selector for discovery only, then B6 for QA | value of agentic multi-hop discovery vs fixed retrieval |
| **B9 — ResearchNexus complete workflow** | seed → profile → multi-strategy discovery → transparent ranking → typed trail → workspace → verified RAG → profile-grounded comparison → structured gaps → directions → deterministic citations → outline | the full system; compared on every metric above and on `W` |

## 26. Failure Cases (analysis + mitigations)

| Failure | Evidence it is real | ResearchNexus mitigation |
|---|---|---|
| Poor PDF text extraction | PDFTriage premise; parser fragility | fall back to Nougat/MinerU; flag low-confidence extraction; show the user the parsed text |
| Scanned / image-only PDFs | Nougat motivation | detect (no text layer) → OCR path or reject with a clear message |
| Tables not extracted | PDFTriage (table reasoning is where structure helps most) | dedicated table-block extraction; store tables verbatim; "dataset/metric" questions route to table blocks |
| Figures ignored | SPIQA, M3SciQA (multimodal gap) | state the limitation; extract figure captions as text; don't answer figure-only questions confidently |
| Wrong related papers surfaced | LitSearch (recall gaps), ResearchArena (LLM agents lose to keyword baselines) | multi-strategy union + rerank; show per-signal scores so the user can spot a bad match; human selection step |
| Semantic similarity without real relevance | SPECTER2 conflates topic vs method | separate `problem_sim`/`method_sim` signals; require ≥2 agreeing signals for a "similar" edge |
| Citation-graph bias (popularity) | CitationNet-LLM cold-start; citation dynamics | cap the citation signal weight; always blend with semantics; show why a paper ranked |
| Recency bias / missing older foundational work | citation recency dynamics | explicit "foundational" strategy: high age + high in-citations from the seed's cluster |
| Missing contradictory papers | ContraCrow finds some, not all | run an explicit contradiction pass over the seed's key claims; label confidence; never claim exhaustiveness |
| LLM hallucination in answers | M3SciQA (models ≪ humans); ALCE (~50% incomplete support) | retrieve→filter→generate→`IsSupported?`→RAGAs gate; drop/flag unsupported sentences |
| Citation hallucination | OpenScholar (GPT-4o 78–90%); R12 | deterministic citation build from metadata only; never LLM-authored references |
| Research-gap hallucination | Si et al. (LLM self-eval unreliable) | gaps only from the structured matrix + ≥2 cited papers; confidence band; human accept/reject |
| Duplicate papers (arXiv vs published, v1 vs v2) | common in multi-source discovery | normalise by DOI/arXiv-id/title-hash; merge; keep the most complete record |
| API failures / rate limits (LLM or arXiv/OpenAlex) | operational reality; BYOK keys | per-provider retry/backoff; partial-result rendering; cache; surface "N of M sources reached" |
| Retrieval bias toward the seed's own sub-community | STORM "source-bias transfer" | diversity term in ranking; query expansion with paraphrases; cross-strategy union |
| Domain terminology / acronym mismatch | scholarly-search difficulty (LitSearch) | LLM query expansion with synonyms/expansions from the profile; hybrid dense+BM25 |
| Long-context limits on full papers | AutoSurvey, ALCE | section-aware chunking + map-reduce; never stuff a whole paper |
| Over-confident multi-paper QA | M3SciQA | calibrate; prefer "retrieved passages say X and Y" phrasing with citations over synthesised assertions |
| Prompt injection inside a PDF | untrusted-content risk (see architecture doc §21) | treat PDF text as data; delimit; instruction-strip; never let paper text change tool policy |

## 27. Threats to Validity

- **Preprint reliance.** 7 of 25 primary papers are arXiv-only (PaperQA, PaperQA2, PaperHelper, RA-FSM, GraphRAG, LitLLM, "there yet?"). They are field-defining and widely used, but not peer-reviewed; PaperQA2's and OpenScholar's headline numbers were read from authoritative project/venue pages, not independently reproduced here.
- **Metric provenance.** Several numbers (AutoSurvey citation recall/precision, PaSa recall@k, LitSearch gaps, OpenScholar deltas) were confirmed from the paper's own abstract/venue page or the authors' materials; a few finer figures (exact LitQA accuracy, GraphRAG win-rates, M3SciQA gap size) could not be pinned to an authoritative page and are reported qualitatively and flagged.
- **Recency cut-off.** "Current date" for this review is September 2026; the OpenScholar *Nature* record was published online February 2026. Work after mid-2026 is not covered.
- **Domain skew.** The corpus is dominated by NLP/ML and biology; conclusions about scholarly search/QA may not transfer to, e.g., mathematics or the humanities.
- **Selection bias.** Discovery leaned on arXiv/ACL/Semantic Scholar visibility; strong work in IEEE/Elsevier venues with weaker open indexing may be under-represented (partially mitigated by including *Nature*, *Scientometrics*, ACM, Wiley).
- **English-only.** All reviewed systems and benchmarks are English.
- **No re-implementation.** This is a literature review; none of the systems were run. Recommended-experiment expectations are hypotheses grounded in reported results, not RN measurements.
- **"Novelty" is a moving target.** Claims in §21–§23 reflect the reviewed set as of the cut-off; a system matching the full RN workflow could appear at any time. The framing is deliberately "comparatively few / not to our knowledge", not "nobody has done this".

## 28. Conclusion

Across 2022–2026 the AI research assistant became **real, citation-grounded, and increasingly agentic**: OpenScholar (in *Nature*) reaches human-level citation accuracy over 45M papers; PaperQA2 matches domain experts and flags contradictions; PaSa automates multi-hop paper search; Ai2 Scholar QA ships organized, attributed synthesis with comparison tables. Every individual capability ResearchNexus needs — scientific RAG QA, dense scholarly retrieval, PDF parsing, LLM summarisation, comparison-table synthesis, citation grounding, agentic search — is **established or well studied**, and FAISS / local embeddings / outline generation are **not novel at all**.

What the reviewed literature does **not** provide is the specific ResearchNexus combination: **one uploaded seed paper → an auditable structured research profile → multi-strategy related-paper discovery → transparent, explained multi-signal ranking → a *typed* research trail (foundational / similar / recent / competing / method-extension / dataset-related / contradictory) → a persistent multi-paper workspace → verified RAG, comparison, and evidence-grounded, confidence-labelled research-gap objects → directions, deterministic citations, and a slide outline — orchestrated by a single agent and evaluated end-to-end.** The nearest systems each cover a slice (PaSa: discovery; ResearchAgent: paper→ideas; OpenScholar/PaperQA2: query→synthesis) and the field evaluates *stages*, never the *workflow*.

The defensible contributions for ResearchNexus are therefore **(1) auditable multi-signal related-paper ranking with per-paper relevance explanations, (2) a typed evidence-carrying research trail, (3) structured evidence-grounded confidence-labelled research-gap objects, and (4) an end-to-end, human-in-the-loop workflow with a composite evaluation** — stated in evidence-based language, not as "nobody has done this". The recommended architecture (§24) and experiments (§25) are built directly from what the reviewed systems show works (retrieve→rerank→filter→verify; deterministic citations; multi-strategy discovery; human-in-the-loop confirmation) and what they show fails (LLM-authored citations; single-strategy discovery; flat lists; fixed-size chunking; unverified gap prose).

## 29. References

Cited as: short name — full title. Author list (first author et al. where long). Year. Venue. Identifier. Verification status.

**Primary (2022–2026)**

1. **PaperQA** — Lála, J., O'Donoghue, O., Shtedritski, A., Cox, S., Rodriques, S. G., White, A. D. *PaperQA: Retrieval-Augmented Generative Agent for Scientific Research.* 2023. arXiv preprint. arXiv:2312.07559. https://arxiv.org/abs/2312.07559 — verified YES (preprint).
2. **PaperQA2** — Skarlinski, M. D., Cox, S., Laurent, J. M., Braza, J. D., Hinks, M., Hammerling, M. J., Ponnapati, M., Rodriques, S. G., White, A. D. *Language agents achieve superhuman synthesis of scientific knowledge.* 2024. arXiv preprint (FutureHouse). arXiv:2409.13740. https://arxiv.org/abs/2409.13740 — verified YES (preprint).
3. **OpenScholar** — Asai, A., He, J., Shao, R., Shi, W., Singh, A., Chang, J. C., Lo, K., Soldaini, L., Feldman, S., D'Arcy, M., Wadden, D., et al. *Synthesizing scientific literature with retrieval-augmented language models (OpenScholar).* arXiv:2411.14199 (2024); *Nature*, published online 4 Feb 2026. DOI 10.1038/s41586-025-10072-4. https://www.nature.com/articles/s41586-025-10072-4 — verified YES (peer-reviewed, Nature).
4. **Ai2 Scholar QA** — Singh, A., Chang, J. C., Haddad, D., Naik, A., Hwang, J. D., Kinney, R., Weld, D. S., Downey, D., Feldman, S. *Ai2 Scholar QA: Organized Literature Synthesis with Attribution.* 2025. ACL 2025 System Demonstrations, pp. 513–523. DOI 10.18653/v1/2025.acl-demo.49. https://aclanthology.org/2025.acl-demo.49/ — verified YES.
5. **PaperHelper** — Yin, C., Wei, E., Zhang, Z., Zhan, Z. *PaperHelper: Knowledge-Based LLM QA Paper Reading Assistant.* 2025. arXiv preprint. arXiv:2502.14271. https://arxiv.org/abs/2502.14271 — verified YES (preprint).
6. **RA-FSM** — Bhavsar, V., Ereifej, J., Gurusami, A. *Hallucination-Resistant, Domain-Specific Research Assistant with Self-Evaluation and Vector-Grounded Retrieval.* 2025. arXiv preprint. arXiv:2510.02326. https://arxiv.org/abs/2510.02326 — verified YES (preprint).
7. **PaSa** — He, Y., Huang, G., Feng, P., Lin, Y., Zhang, Y., Li, H., E, W. *PaSa: An LLM Agent for Comprehensive Academic Paper Search.* 2025. ACL 2025 (Long), pp. 11663–11679. DOI 10.18653/v1/2025.acl-long.572. https://aclanthology.org/2025.acl-long.572/ — verified YES.
8. **LitLLM** — Agarwal, S., Sahu, G., Puri, A., Laradji, I. H., Dvijotham, K. DJ, Stanley, J., Charlin, L., Pal, C. *LitLLM: A Toolkit for Scientific Literature Review.* 2024. arXiv preprint. arXiv:2402.01788. https://arxiv.org/abs/2402.01788 — verified PARTIAL (venue status of a demo version unconfirmed).
9. **LitLLMs "Are we there yet?"** — Agarwal, S., Sahu, G., Puri, A., Laradji, I. H., Dvijotham, K. DJ, Stanley, J., Charlin, L., Pal, C. *LitLLMs, LLMs for Literature Review: Are we there yet?* 2024 (arXiv:2412.15249); reported TMLR 2025. https://arxiv.org/abs/2412.15249 — verified PARTIAL (TMLR acceptance per authors' repo; OpenReview record not confirmed here).
10. **LitSearch** — Ajith, A., Xia, M., Chevalier, A., Goyal, T., Chen, D., Gao, T. *LitSearch: A Retrieval Benchmark for Scientific Literature Search.* 2024. EMNLP 2024 (Main), pp. 15068–15083. DOI 10.18653/v1/2024.emnlp-main.840. https://aclanthology.org/2024.emnlp-main.840/ — verified YES.
11. **SciRepEval / SPECTER2** — Singh, A., D'Arcy, M., Cohan, A., Downey, D., Feldman, S. *SciRepEval: A Multi-Format Benchmark for Scientific Document Representations.* 2023. EMNLP 2023 (Main), pp. 5548–5566. DOI 10.18653/v1/2023.emnlp-main.338. https://aclanthology.org/2023.emnlp-main.338/ — verified YES.
12. **ResearchAgent** — Baek, J., Jauhar, S. K., Cucerzan, S., Hwang, S. J. *ResearchAgent: Iterative Research Idea Generation over Scientific Literature with Large Language Models.* 2025. NAACL 2025 (Long), pp. 6709–6738. DOI 10.18653/v1/2025.naacl-long.342. https://aclanthology.org/2025.naacl-long.342/ — verified YES.
13. **CitationNet-LLM** — Liu, K., Zhang, Y., Pan, R., et al. *Academic literature recommendation in large-scale citation networks enhanced by large language models.* 2025. *Scientometrics*, 130, 5143–5169. DOI 10.1007/s11192-025-05420-0. https://link.springer.com/article/10.1007/s11192-025-05420-0 (arXiv:2503.01189) — verified YES.
14. **ArxivDIGESTables** — Newman, B., Lee, Y., Naik, A., Siangliulue, P., Fok, R., Kim, J., Weld, D. S., Chang, J. C., Lo, K. *ArxivDIGESTables: Synthesizing Scientific Literature into Tables using Language Models.* 2024. EMNLP 2024 (Main), pp. 9612–9631. DOI 10.18653/v1/2024.emnlp-main.538. https://aclanthology.org/2024.emnlp-main.538/ — verified YES.
15. **CHIME** — Hsu, C.-C., Bransom, E., Sparks, J., Kuehl, B., Tan, C., Wadden, D., Wang, L. L., Naik, A. *CHIME: LLM-Assisted Hierarchical Organization of Scientific Studies for Literature Review Support.* 2024. ACL 2024 (Findings), pp. 118–132. DOI 10.18653/v1/2024.findings-acl.8. https://aclanthology.org/2024.findings-acl.8/ — verified YES.
16. **AutoSurvey** — Wang, Y., Guo, Q., Yao, W., Zhang, H., Zhang, X., Wu, Z., Zhang, M., Dai, X., Zhang, M., Wen, Q., Ye, W., Zhang, S., Zhang, Y. *AutoSurvey: Large Language Models Can Automatically Write Surveys.* 2024. NeurIPS 2024. arXiv:2406.10252. https://proceedings.neurips.cc/paper_files/paper/2024/hash/d07a9fc7da2e2ec0574c38d5f504d105-Abstract-Conference.html — verified YES.
17. **SurveyForge** — Yan, X., Feng, S., Yuan, J., Xia, R., Wang, B., Bai, L., Zhang, B. *SurveyForge: On the Outline Heuristics, Memory-Driven Generation, and Multi-dimensional Evaluation for Automated Survey Writing.* 2025. ACL 2025 (Long), pp. 12444–12465. DOI 10.18653/v1/2025.acl-long.609. https://aclanthology.org/2025.acl-long.609/ — verified YES.
18. **STORM** — Shao, Y., Jiang, Y., Kanell, T. A., Xu, P., Khattab, O., Lam, M. S. *Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models.* 2024. NAACL 2024 (Long), pp. 6252–6278. DOI 10.18653/v1/2024.naacl-long.347. https://aclanthology.org/2024.naacl-long.347/ — verified YES.
19. **ChatCite** — Li, Y., Chen, L., Liu, A., Yu, K., Wen, L. *ChatCite: LLM Agent with Human Workflow Guidance for Comparative Literature Summary.* 2025. COLING 2025 (Main), pp. 3613–3630. ACL Anthology 2025.coling-main.244 (arXiv:2403.02574). https://aclanthology.org/2025.coling-main.244/ — verified PARTIAL (DOI not confirmed).
20. **GraphRAG** — Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky, D., Ness, R. O., Larson, J. *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* 2024. arXiv preprint (Microsoft Research). arXiv:2404.16130. https://arxiv.org/abs/2404.16130 — verified YES (preprint).
21. **PDFTriage** — Saad-Falcon, J., Barrow, J., Siu, A., Nenkova, A., Yoon, S., Rossi, R. A., Dernoncourt, F. *PDFTriage: Question Answering over Long, Structured Documents.* 2024. EMNLP 2024 (Industry), pp. 153–169. DOI 10.18653/v1/2024.emnlp-industry.13. https://aclanthology.org/2024.emnlp-industry.13/ — verified YES.
22. **M3SciQA** — Li, C., Shangguan, Z., Zhao, Y., Li, D., Liu, Y., Cohan, A. *M3SciQA: A Multi-Modal Multi-Document Scientific QA Benchmark for Evaluating Foundation Models.* 2024. EMNLP 2024 (Findings), pp. 15419–15446. DOI 10.18653/v1/2024.findings-emnlp.904. https://aclanthology.org/2024.findings-emnlp.904/ — verified YES.
23. **ALCE** — Gao, T., Yen, H., Yu, J., Chen, D. *Enabling Large Language Models to Generate Text with Citations.* 2023. EMNLP 2023 (Main), pp. 6465–6488. DOI 10.18653/v1/2023.emnlp-main.398. https://aclanthology.org/2023.emnlp-main.398/ — verified YES.
24. **Self-RAG** — Asai, A., Wu, Z., Wang, Y., Sil, A., Hajishirzi, H. *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.* ICLR 2024 (Oral). arXiv:2310.11511. https://arxiv.org/abs/2310.11511 — verified YES.
25. **RAGAs** — Es, S., James, J., Espinosa Anke, L., Schockaert, S. *RAGAs: Automated Evaluation of Retrieval Augmented Generation.* 2024. EACL 2024 System Demonstrations, pp. 150–158. DOI 10.18653/v1/2024.eacl-demo.16. https://aclanthology.org/2024.eacl-demo.16/ — verified YES.

**Foundational / Background (pre-2022)**

F1. **QASPER** — Dasigi, P., Lo, K., Beltagy, I., Cohan, A., Smith, N. A., Gardner, M. *A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers.* 2021. NAACL 2021, pp. 4599–4610. DOI 10.18653/v1/2021.naacl-main.365. — verified YES.
F2. **Multi-XScience** — Lu, Y., Dong, Y., Charlin, L. *Multi-XScience: A Large-scale Dataset for Extreme Multi-document Summarization of Scientific Articles.* 2020. EMNLP 2020, pp. 8068–8074. DOI 10.18653/v1/2020.emnlp-main.648. — verified YES.
F3. **SciTLDR** — Cachola, I., Lo, K., Cohan, A., Weld, D. S. *TLDR: Extreme Summarization of Scientific Documents.* 2020. EMNLP 2020 (Findings), pp. 4766–4777. DOI 10.18653/v1/2020.findings-emnlp.428. — verified YES.
F4. **FacetSum** — Meng, R., Thaker, K., Zhang, L., Dong, Y., Yuan, X., Wang, T., He, D. *Bringing Structure into Summaries: a Faceted Summarization Dataset for Long Scientific Documents.* 2021. ACL-IJCNLP 2021 (Short), pp. 1080–1089. DOI 10.18653/v1/2021.acl-short.137. — verified YES.
F5. **SciFact** — Wadden, D., Lin, S., Lo, K., Wang, L. L., van Zuylen, M., Cohan, A., Hajishirzi, H. *Fact or Fiction: Verifying Scientific Claims.* 2020. EMNLP 2020, pp. 7534–7550. DOI 10.18653/v1/2020.emnlp-main.609. — verified YES.

**Background surveys**

B1. **RAG Survey** — Gao, Y., Xiong, Y., Gao, X., Jia, K., Pan, J., Bi, Y., Dai, Y., Sun, J., Wang, M., Wang, H. *Retrieval-Augmented Generation for Large Language Models: A Survey.* 2023. arXiv:2312.10997. — verified YES (preprint).
B2. **LLM4SR** — Luo, Z., Yang, Z., Xu, Z., Yang, W., Du, X. *LLM4SR: A Survey on Large Language Models for Scientific Research.* 2025. arXiv:2501.04306. — verified YES (preprint).
B3. **From Hypothesis to Publication** — Zhou, Z., Feng, X., Huang, L., Feng, X., Song, Z., Chen, R., Zhao, L., Ma, W., Gu, Y., Wang, B., Wu, D., Hu, G., Liu, T., Qin, B. *From Hypothesis to Publication: A Comprehensive Survey of AI-Driven Research Support Systems.* 2025. EMNLP 2025 (Findings), pp. 11773–11803. DOI 10.18653/v1/2025.findings-emnlp.631. — verified YES.
B4. **Agentic RAG Survey** — Singh, A., Ehtesham, A., Kumar, S., Talaei Khoei, T., Vasilakos, A. V. *Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG.* 2025. arXiv:2501.09136. — verified YES (preprint).

**Reserve pool (verified; not counted in the primary 25)** — Scim (Fok et al., IUI 2023, DOI 10.1145/3581641.3584034); Nougat (Blecher et al., 2023, arXiv:2308.13418); MinerU (2024, arXiv:2409.18839); SciLitLLM (Li et al., ICLR 2025, arXiv:2408.15545); The AI Scientist (Lu et al., 2024, arXiv:2408.06292); SciAgents (Ghafarollahi & Buehler, *Advanced Materials* 2025, DOI 10.1002/adma.202413523); Can LLMs Generate Novel Research Ideas? (Si et al., 2024, arXiv:2409.04109); SciReviewGen (Kasanishi et al., ACL 2023 Findings, DOI 10.18653/v1/2023.findings-acl.418); SPIQA (Pramanick et al., NeurIPS 2024 D&B, arXiv:2407.09413); RAG Framework for Academic Literature Navigation in Data Science (Aytar et al., 2024, arXiv:2412.15404); Arxiv Copilot (Lin et al., EMNLP 2024 Demo, DOI 10.18653/v1/2024.emnlp-demo.13); Do Language Models Know When They're Hallucinating References? (Agrawal et al., 2023, arXiv:2305.18248).

**Removed in Phase 2 (unverifiable or redundant):** "A synergistic multi-stage RAG architecture …" (no stable record); HiReview (no stable identifier); SPAR (arXiv:2507.15245, unverified/redundant with PaSa); Scholar Inbox (unverified/tangential).

---

*End of literature review. Fact-check log: all 25 primary + 5 foundational + 4 background titles, authors, years, venues and identifiers were confirmed against authoritative pages during Phases 1–3; ACL Anthology DOIs follow the confirmed `10.18653/v1/<id>` pattern; unconfirmed items (ChatCite DOI; LitLLM/"there yet?" venue) are flagged inline and in `paper-metadata.csv`; figures that could not be tied to an authoritative page are stated qualitatively and flagged; no facial-recognition / attendance content appears anywhere in this document.*





