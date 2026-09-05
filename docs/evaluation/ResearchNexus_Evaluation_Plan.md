# ResearchNexus — Evaluation Plan

**Purpose.** How ResearchNexus is measured — per stage **and** end-to-end. The literature review's contribution area #4 is *"end-to-end evaluation of the complete research workflow"*, because existing systems evaluate only stages *[review §19, §25]*. **Design only — no evaluation code is written by this document.**

**Companions:** `ResearchNexus_Implementation_Architecture.md`, `ResearchNexus_Data_Model.md`, `ResearchNexus_API_Specification.md`, `ResearchNexus_Implementation_Roadmap.md` (Phase 16), literature review §19 & §25.

**Principles**
- **No fabricated numbers.** Every metric is defined here with its source dataset and computation. Where human judgement is used, the rubric and rater count are stated.
- **Reproducible core.** Public benchmarks (QASPER, LitSearch, arxivDIGESTables, M3SciQA, SciRepEval, WikiEval via RAGAS) plus RN-built sets whose construction is documented and scripted (`eval/datasets/`).
- **Contamination control.** For discovery/gap evaluation, prefer seed papers published *after* common LLM training cut-offs (LitSearch / M3SciQA practice).
- **Report per provider.** BYOK means quality varies by the user's LLM; every result names the provider+model and is never generalised across them.
- **Observers don't touch production paths.** The harness reads `stage_runs` and re-runs pipelines in an eval mode; it does not alter output.

---

## 1. Datasets

| Id | Dataset | Source | Use | Build/where |
|---|---|---|---|---|
| D-QASPER | QASPER (5,049 Q / 1,585 papers) | public *[review F1]* | single-paper RAG QA (answer F1, evidence F1) | download |
| D-LITSEARCH | LitSearch (597 queries) | public *[LitSearch]* | retrieval sanity (BM25 vs dense vs rerank) | download |
| D-M3SCIQA | M3SciQA (1,452 Q / 70 anchor+cited clusters) | public *[M3SciQA]* | multi-paper QA + anchor retrieval MRR; the anchor+cited structure ≈ RN seed+trail | download |
| D-ADT | arxivDIGESTables (2,228 tables / 7,542 papers) | public *[ArxivDIGESTables]* | comparison-table column/value recall + DecontextEval | download |
| D-SCIREPEVAL | SciRepEval search/proximity tasks | public *[SciRepEval]* | embedding choice (MiniLM vs SPECTER2 vs BGE/E5) for discovery | download |
| D-WIKIEVAL | WikiEval (RAGAS validation set) | via `ragas` *[RAGAs]* | sanity-check that faithfulness/answer/context-relevance track humans | library |
| **D-RN-DISC** | **RN Discovery Benchmark** — N=40 seeds, each with a "relevant set" | RN-built | discovery Recall/Precision/MRR/nDCG per strategy and fused | `eval/datasets/build_discovery_benchmark.py` |
| **D-RN-TRAIL** | **RN Trail-Label set** — ≥150 (seed, target) pairs, human-labelled relationship type(s) | RN-built | trail-typing precision/recall/F1 + confidence calibration | `eval/datasets/build_trail_labels.py` |
| **D-RN-GAP** | **RN Gap-Rating set** — 10 workspaces, expert-rated gaps | RN-built | gap relevance / evidence-support / novelty / hallucination | `eval/datasets/build_gap_rating.py` |
| **D-RN-E2E** | **RN End-to-End set** — 10 seed papers with a full "gold" walkthrough (relevant papers, expected trail types, 5 QA pairs, a reference comparison, ≥1 expert-agreed gap) | RN-built | the composite `W` and baseline comparison | `eval/datasets/build_e2e_set.py` |

**D-RN-DISC construction (documented, not fabricated).** For each seed: relevant = (a) papers in the seed's own reference list that a rater marks topically central + (b) papers that cite the seed and a rater marks central + (c) rater-added papers found by manual search. Two raters; keep the union; a held-out 10-seed slice gets a third-rater adjudication for High/Med/Low relevance. Seeds chosen post-2024 to limit contamination. This mirrors LitSearch/AutoScholarQuery methodology.

**D-RN-TRAIL construction.** Sample (seed, target) pairs across bands and strategies from D-RN-DISC runs; two annotators assign zero-or-more of the 7 `RelationshipType`s using a written rubric (see §7); adjudicate disagreements; record inter-annotator agreement (Cohen's κ per type).

**D-RN-GAP construction.** Build 10 workspaces (5–15 papers each) from D-RN-DISC seeds; run the gap pipeline; ≥2 domain experts rate each surfaced gap on the §6 rubric; also collect expert-written "true gaps" for recall estimation.

---

## 2. Layer: Discovery

**What it measures.** Does multi-strategy discovery surface the right related papers from a seed?

| Metric | Definition | Dataset |
|---|---|---|
| Precision@{5,10,20} | fraction of top-k that are in the relevant set | D-RN-DISC |
| Recall@{10,20,50} | fraction of the relevant set found in top-k | D-RN-DISC |
| MRR | 1/rank of the first relevant | D-RN-DISC |
| nDCG@10 | graded (High/Med/Low relevance) | D-RN-DISC held-out slice |
| Diversity | mean pairwise SPECTER2 distance of top-k (guards against sub-community collapse — *[STORM source-bias]*) | D-RN-DISC |
| Recency | median (now − year) of top-k vs the corpus median | D-RN-DISC |
| Expert relevance | blind High/Med/Low on a sample of top-20 | D-RN-DISC held-out |
| API health | per-strategy error rate, p50/p95 latency, tokens, USD | `stage_runs` |
| Strategy overlap | Jaccard of results between each pair of strategies (are they redundant?) | D-RN-DISC |

**Protocol.** Run each strategy alone and the fused union; report per-strategy and fused; sanity-check the retriever choice on D-LITSEARCH and D-SCIREPEVAL. Expected from the literature: dense/SPECTER2 ≫ BM25 alone *[LitSearch: +24.8 R@5]*; fused > best single *[review §9]*; rerank +~4% *[LitSearch]*.

---

## 3. Layer: Ranking  (contribution area 1)

**What it measures.** Does the transparent multi-signal fusion order papers well, and are the per-paper reasons true?

| Metric | Definition | Dataset |
|---|---|---|
| nDCG@10 | vs graded relevance | D-RN-DISC held-out |
| Pairwise preference | % of expert pairwise judgements the ranking agrees with | D-RN-DISC held-out (sampled pairs) |
| Reason accuracy | for each stated bullet reason, a human confirms it is true given the signal values (target ≥ 0.95) | D-RN-DISC held-out |
| Reason coverage | % of top-10 papers with ≥ 2 non-trivial reasons | D-RN-DISC |
| Band calibration | agreement between `high/medium/low` bands and expert High/Med/Low | D-RN-DISC held-out |
| Determinism | identical inputs → identical `fused_score` / `final_rank` (unit test) | fixtures |

**Weight tuning.** `RankingWeights` start at `w0-initial` (values + rationale in Data Model §4). Tune on a D-RN-DISC train split (grid / coordinate ascent maximising nDCG@10), evaluate on the held-out split, **check the tuned `w1-*` version into the repo with the eval run that produced it**. Never present `w0-initial` results as optimal.

---

## 4. Layer: Typed research trail  (contribution area 2)

| Metric | Definition | Dataset |
|---|---|---|
| Per-type Precision / Recall / F1 | vs human labels, per `RelationshipType` | D-RN-TRAIL |
| Contradiction precision | of `POTENTIALLY_CONTRADICTORY` edges, fraction humans confirm (target ≥ 0.8 — false contradictions are costly) | D-RN-TRAIL |
| Multi-type correctness | for pairs with >1 true type, fraction of types recovered | D-RN-TRAIL |
| Confidence calibration | reliability curve: does `high` confidence ⇒ higher human agreement than `medium`/`low`? (ECE) | D-RN-TRAIL |
| Rule vs LLM contribution | F1 with rules only vs rules+LLM-confirm (feeds ablation A9) | D-RN-TRAIL |
| Inter-annotator κ | per type (dataset quality) | D-RN-TRAIL |

**Targets (from Roadmap P7 acceptance):** `FOUNDATIONAL`/`RECENT`/`DATASET_RELATED` F1 ≥ 0.75; `SIMILAR`/`METHOD_EXTENSION`/`COMPETING` F1 ≥ 0.6; `POTENTIALLY_CONTRADICTORY` precision ≥ 0.8.

---

## 5. Layer: RAG (QA over the workspace)

| Metric | Definition | Dataset |
|---|---|---|
| Faithfulness | RAGAS faithfulness (answer entailed by retrieved context) | D-QASPER, D-M3SCIQA, D-RN-E2E |
| Answer relevance | RAGAS answer relevance | same |
| Context relevance | RAGAS context relevance (retrieved context on-point) | same |
| Citation precision / recall | ALCE-style NLI between each sentence and its cited chunk(s) *[ALCE]* | D-RN-E2E |
| Unsupported-sentence rate | % sentences dropped/flagged by `IsSupported?` | all |
| Answer F1 / Evidence F1 | token F1 vs QASPER gold; evidence-span F1 | D-QASPER |
| Multi-doc accuracy | exact/soft match vs M3SciQA gold; anchor MRR | D-M3SCIQA |
| Answerability | on unanswerable questions, does the gate say "I don't know"? (precision/recall of abstention) | D-QASPER (unanswerable split) + crafted |
| Latency / tokens / cost | per message, per provider | `stage_runs` |

**Targets (Roadmap P9):** median faithfulness ≥ 0.85; unsupported-sentence rate ≤ 5 %; **fabricated-reference rate = 0**.

---

## 6. Layer: Citation integrity

| Metric | Definition | Dataset |
|---|---|---|
| **Fabricated-reference rate** | % of generated reference strings not corresponding to a real workspace paper (target **0** — structurally, since the LLM never writes references) | all generated artefacts in D-RN-E2E |
| Citation precision | % of cited (sentence → chunk) links where the chunk supports the sentence | D-RN-E2E |
| Citation recall | % of check-worthy sentences that carry a supporting citation | D-RN-E2E |
| Citation correctness | formatter output matches canonical CSL metadata (golden tests) | fixtures |
| Metadata resolution rate | % of workspace papers resolved to full metadata (else `Not available`, never guessed) | D-RN-DISC papers |

---

## 7. Layer: Gap detection  (contribution area 3)

**Rubric (per surfaced gap, ≥ 2 domain-expert raters):**
- **Relevance / plausibility** (1–5): is this a real, meaningful gap given the workspace?
- **Evidence support** (yes/no): do the ≥ 2 cited spans actually support the gap? (should be 100 % by construction)
- **Novelty** (1–5): is it genuinely under-addressed by the workspace papers (not a strawman, not already solved)?
- **Hallucination** (count): claims in `statement`/`why_unaddressed` not backed by a cited span.
- **Confidence appropriateness** (over/under/ok): does the `high/medium/low` band match the evidence strength?

| Metric | Definition | Dataset |
|---|---|---|
| Expert relevance rate | % of surfaced gaps rated ≥ 3/5 by ≥ 2 raters (target ≥ 0.6) | D-RN-GAP |
| Evidence-support rate | % with ≥ 2 valid supporting spans (target 1.0) | D-RN-GAP |
| Hallucination rate | mean unsupported claims per gap (target ≤ 0.02 per surfaced gap) | D-RN-GAP |
| Gap recall (proxy) | of expert-written "true gaps", fraction the system also surfaced | D-RN-GAP |
| Confidence calibration | band vs expert-judged evidence strength | D-RN-GAP |
| Consistency | Jaccard of surfaced gaps across 3 re-runs on the same workspace (temperature fixed) | D-RN-GAP |
| Baseline delta | RN structured gaps vs the 3 baselines below on relevance + hallucination | D-RN-GAP |

**Gap baselines (from review §25.5):** (i) "ask GPT-4 for the research gaps in these papers" — free text; (ii) contradiction-only (ContraCrow-style pass, no coverage/evaluation/method rules); (iii) GraphRAG "what is missing here?" prose. RN must beat all three on expert relevance *and* hallucination.

---

## 8. Layer: Summarisation & key points

| Metric | Definition | Dataset |
|---|---|---|
| ROUGE-1/2/L, BERTScore | vs author abstracts / SciTLDR / FacetSum facets | D-QASPER papers, public SciTLDR/FacetSum |
| RAGAS faithfulness | summary entailed by the paper | RN papers |
| Per-facet ROUGE | typed key points vs FacetSum purpose/method/findings/value | FacetSum |
| Expert Likert | accuracy, coverage, usefulness (1–5) | D-RN-E2E |

## 8b. Layer: Comparison

| Metric | Definition | Dataset |
|---|---|---|
| Column/value recall | vs reference tables | D-ADT |
| DecontextEval | aspect-aligned match despite surface differences *[ArxivDIGESTables]* | D-ADT + D-RN-E2E |
| Per-cell evidence coverage | % of non-null cells with a valid supporting span (target ≥ 0.9) | D-RN-E2E |
| Per-cell citation accuracy | span supports the cell value | D-RN-E2E |

## 8c. Layer: Research directions

Expert rubric (1–5): novelty, specificity, feasibility, groundedness. Also: % correctly labelled `evidence_backed_inference` vs `llm_hypothesis`; % phrased as fact (should be ~0, checked by a lint prompt + human spot-check). Target: median groundedness ≥ 3.5.

---

## 9. End-to-end evaluation  (contribution area 4 — the methodological contribution)

**Protocol.** For each of the 10 seeds in D-RN-E2E, run the *whole* pipeline (seed → profile → discovery → ranking → trail → workspace → QA → comparison → gap → direction → citations) and score every stage against that seed's gold walkthrough. Then compute the composite.

**Composite workflow score `W`** (weights `u_i` fixed a priori, components always reported alongside):

```
W = u1 * norm(Recall@20)                 # discovery
  + u2 * norm(trail_typing_macro_F1)      # trail
  + u3 * norm(RAG_faithfulness)           # RAG
  + u4 * norm(DecontextEval)              # comparison
  + u5 * norm(gap_expert_relevance_rate)  # gap
  + u6 * (1 - fabricated_reference_rate)  # citation integrity
```

Initial `u = [0.20, 0.15, 0.20, 0.15, 0.20, 0.10]` (labelled provisional; sensitivity analysis reported). `norm(x)` is min–max against the baseline spread on D-RN-E2E so `W` is comparable across systems. `W` is reported for ResearchNexus **and** for baselines B1–B9 (§10) — this cross-system, whole-workflow number is what the literature does not currently produce *[review §19]*.

---

## 10. Baselines  (from literature review §25.9)

| Id | Baseline | What it isolates / evaluates |
|---|---|---|
| B1 | Keyword academic search (BM25/arXiv from seed title+abstract, no LLM) | floor for discovery; value of semantics |
| B2 | Dense semantic search (SPECTER2 kNN from seed, no rerank) | value of scholarly document embeddings over keywords |
| B3 | Citation-based discovery (1–2-hop OpenAlex neighbours, citation-proximity rank) | value + bias (popularity/recency) of the citation signal alone |
| B4 | Hybrid semantic + citation (B2 ∪ B3, score fusion, no LLM rerank) | value of fusing signals before any LLM |
| B5 | Standard RAG (top-k dense + single LLM generation, no rerank/verify) | baseline QA/synthesis faithfulness |
| B6 | RAG + reranking (B5 + cross-encoder + contextual filter) | isolated value of rerank/contextualisation *[LitLLM "there yet?": doubles recall]* |
| B7 | LLM academic search ("ask the LLM to list related papers / gaps", no retrieval) | quantifies hallucination without grounding *[OpenScholar 78–90 %]* |
| B8 | Agentic academic search (PaSa-style crawler+selector for discovery only, then B6 for QA) | value of agentic multi-hop discovery vs fixed retrieval |
| B9 | **ResearchNexus complete workflow** | the full system; scored on every layer above and on `W` |

Each baseline is a config of the same codebase (the ablation switchboard, §11), not a separate re-implementation, so comparisons are apples-to-apples.

---

## 11. Ablation studies

Each toggles **one** component; each answers one scientific question. Run on D-RN-E2E (+ the layer's own dataset where noted).

| Id | Configuration | Scientific question it answers |
|---|---|---|
| **A1** | Keyword only | How much of discovery quality comes from keyword search alone? (lower bound) |
| **A2** | Semantic only (chunk + SPECTER2 doc) | Is dense semantic retrieval sufficient on its own for scholarly discovery? |
| **A3** | Citation only | How far can pure citation-graph traversal get, and how biased (recency/popularity) is it? |
| **A4** | Keyword + semantic | Does adding lexical search to semantic help beyond noise? |
| **A5** | Keyword + semantic + citation | Do the three "cheap" strategies together approach the full set? |
| **A6** | Full multi-signal (all 7 strategies + fused ranking) | Does the full multi-strategy design beat every subset — i.e. is "multi-strategy" earning its cost? |
| **A7** | Without cross-encoder reranking | What is the isolated contribution of reranking to ranking quality and downstream QA? *[expect large — LitLLM "there yet?"]* |
| **A8** | Without research-profile extraction (discover directly from title+abstract) | Does the structured profile (problem/method/dataset fields) improve discovery, ranking, and gap quality over raw text? |
| **A9** | Without typed trail (flat ranked list only) | Does relationship typing add value users can act on — measured by selection precision and gap quality — vs a flat list? |
| **A10** | Without evidence verification (`IsSupported?` + faithfulness gate off) | How much do the verification steps reduce unsupported claims / citation errors, and at what latency/cost? |
| **A11** | Vanilla RAG vs structured RAG (recursive char chunks + flat top-k **vs** section-aware chunks + structure index + GraphRAG routing) | Does scientific-document structure awareness improve faithfulness and "what dataset / what metric" answer accuracy? *[PDFTriage]* |
| **A12** | Single-paper vs multi-paper RAG (restrict retrieval to the seed vs the whole workspace) | What does the multi-paper workspace buy for QA quality vs single-paper QA? |
| **A13** | Without workspace-level research graph (no GraphRAG routing; gaps from profiles only, no graph projection) | Does the per-workspace graph improve themes/gaps answers and gap-candidate quality enough to justify building it? |
| A-concepts | Without LLM query expansion / perspective questions (S5) | Do generated search concepts raise discovery recall/diversity over profile keywords alone? |
| A-agentic | Full orchestrator vs fixed pipeline (no tool-selection discretion, no extra citation hop, no regenerate-once, no answerability gate) | Does the (bounded) agentic layer improve discovery recall / faithfulness / citation integrity, and is the added latency/cost worth it? (the brief's requested comparison) |

**Reporting.** For every ablation: the affected layer metrics + `W` + Δlatency + Δtokens + ΔUSD, with a one-line verdict ("keep / drop / conditional").

---

## 12. Human-evaluation protocol

- **Raters.** ≥ 2 per task (discovery relevance, trail typing, gap rating, direction rating, reason accuracy); a 3rd adjudicates disagreements on held-out slices.
- **Blinding.** System identity hidden; for baseline comparisons, outputs are shuffled and unlabeled.
- **Rubrics.** Written, with worked examples, checked into `eval/datasets/rubrics/`. Agreement reported (Cohen's κ / Krippendorff's α).
- **Sample sizes (MVP-feasible).** D-RN-DISC: 40 seeds, held-out 10 for graded relevance. D-RN-TRAIL: ≥ 150 pairs. D-RN-GAP: 10 workspaces. D-RN-E2E: 10 seeds.
- **Contamination note recorded** per seed (publication date vs the evaluated LLM's cut-off).
- **Ethics / IP.** Only open-access PDFs and abstracts; no redistribution of paywalled full text; raters see excerpts, not full copyrighted PDFs where avoidable.

---

## 13. Observability / telemetry (always on)

- **`stage_runs`** row per tool call: stage, tool, input/output hashes, tokens (prompt/completion), USD, latency, ok/error. **No prompt or response bodies; no secrets.**
- **Per-workspace rollups:** total tokens, USD, wall-clock for seed→workspace and per operation; surfaced in the UI (BYOK cost transparency — a differentiator few papers report *[review §25.6]*).
- **FAISS metrics:** index build time and query latency vs #papers ∈ {5, 20, 50, 100}; resident memory.
- **Model/provenance:** every artefact records `generator_model` / `extraction_model` / `weights_version` for reproducibility.
- **Structured logs** (structlog JSON) with a redaction processor; error logs carry `request_id` but never key material.
- **Regression gates in CI:** a small fixed fixture set runs the deterministic layers + mocked-LLM pipelines; faithfulness / citation-integrity / determinism checks fail the build on regression.
- **Eval runs are versioned:** `scripts/run_eval.py --tag <git-sha>` writes a results table + the exact dataset + weights versions used.

---

## 14. Success criteria (what "the evaluation supports the paper" means)

The four contribution claims are considered evidenced iff, on D-RN-E2E and the relevant layer datasets, with tuned weights and ≥ 2 raters, and reported per LLM provider:

1. **Ranking:** reason accuracy ≥ 0.95 **and** nDCG@10 > `preliminary_rank` **and** full multi-signal (A6) > every subset (A1–A5).
2. **Trail:** macro per-type F1 meets the P7 targets **and** confidence is calibrated **and** A9 shows the typed trail improves selection precision / gap quality over a flat list.
3. **Gap objects:** expert-relevance ≥ 0.6, evidence-support = 1.0, hallucination ≤ 0.02/gap, **and** RN beats all three gap baselines on relevance + hallucination.
4. **End-to-end:** `W(RN) > W(B7)` (grounded > ungrounded) and `W(RN) ≥ W(B8)` (full workflow ≥ agentic-discovery-only), with the whole-workflow `W` reported for every baseline — a comparison the literature does not currently provide.

Failing (1)–(3) is a gate on the corresponding contribution claim, not a reason to overclaim.

---

## 15. IEEE BigData 2024 traceability — provenance completeness (a Phase 2 precursor metric)

Full trace: IEEE limitation → ResearchNexus solution → required data → future implementation phase → evaluation metric is recorded in `docs/architecture/ResearchNexus_Implementation_Architecture.md` §9. Summary:

- **Limitation tracked:** Ahad et al., *"Empowering Meta-Analysis: Leveraging Large Language Models for Scientific Synthesis,"* IEEE BigData 2024 (DOI 10.1109/BigData62323.2024.10825310; arXiv:2411.10878) describes fine-tuned-LLM+RAG generation of meta-analysis narrative text, evaluated for overall relevance (87.6% human-rated relevant) — not a structured, per-claim, auditable evidence trail across the source papers, and not an explicit research-gap-identification step. (Characterisation from the abstract/arXiv metadata; the IEEE-Xplore full text was not reviewed.)
- **Gates §7 (Gap detection)** above: evidence-support rate, hallucination rate, expert relevance, confidence calibration all depend on the gap engine being able to resolve every claim to a real span.

**New precursor metric — provenance completeness (measurable starting now, in Phase 2, before the gap engine exists in Phase 11):**

| Metric | Definition | How it's checked |
|---|---|---|
| Chunk round-trip integrity | `full_text[chunk.char_start:chunk.char_end] == chunk.text` for every non-table chunk | asserted directly in `backend/tests/unit/test_chunker.py` (`test_all_non_table_chunks_round_trip_to_full_text`, `test_real_fixture_end_to_end_chunking`) and holds by construction in `app/services/ingest/chunker.py` |
| Table anchoring rate | fraction of `TableBlock`s whose provenance anchor is the real caption span (`full_text.find(caption)` hit) rather than the page-start fallback | computable from `app/services/ingest/chunker.py::_anchor_table`; not yet aggregated into a report (Phase 11 will report it per workspace) |
| Section attribution completeness | fraction of `PaperChunk`s with a non-null `section` (body/abstract chunks always have one; only `TABLE` chunks are expected to be null) | `app/domain/chunk.py` schema + `app/services/ingest/chunker.py` |
| Confidence-weighted evidence eligibility | fraction of ingested papers with `parse_confidence != LOW`, i.e. eligible to contribute *high-confidence* evidence to a future gap matrix | `app/services/ingest/confidence.py`; asserted per-fixture in `backend/tests/unit/test_pipeline.py` |

These are **not** a substitute for the Phase 11 gap-quality metrics (§7) — they are the necessary precondition, verified now so that when Phase 11 is built, "no evidence found" is never caused by a Phase 2 provenance gap.

*Design only. No evaluation code, datasets, or CI jobs are created by this document. Every metric is defined with a source; no numbers are fabricated. No facial-recognition / attendance content appears anywhere.*
