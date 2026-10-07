import type {
  Confidence,
  EdgeUserState,
  GroupedTrail,
  RelationshipType,
  TrailEdge,
  TrailEvidence,
  TrailGroupEntry,
} from "@/lib/api/types";
import { RELATIONSHIP_TYPES } from "@/lib/api/types";

/** A trail group entry with its relationship type carried along, so a flat,
 * filtered list still knows which group each connection came from. */
export interface TrailEntry extends TrailGroupEntry {
  type: RelationshipType;
}

export const RELATIONSHIP_COPY: Record<RelationshipType, { label: string; singular: string; description: string }> = {
  FOUNDATIONAL: { label: "Foundational", singular: "Foundational work", description: "Earlier work the seed paper cites and builds on." },
  METHOD_EXTENSION: {
    label: "Method extensions",
    singular: "Method extension",
    description: "Later papers that cite the seed paper and build on its method.",
  },
  SIMILAR: { label: "Similar", singular: "Similar work", description: "Papers working on a closely matching problem." },
  RECENT: { label: "Recent", singular: "Recent work", description: "Newer papers on the seed paper's problem." },
  COMPETING: { label: "Competing", singular: "Competing approach", description: "The same problem, approached a different way." },
  DATASET_RELATED: { label: "Shared data", singular: "Shared data", description: "Papers that work with the same datasets." },
  POTENTIALLY_CONTRADICTORY: {
    label: "Possible contradictions",
    singular: "Possible contradiction",
    description: "Findings that may disagree with the seed paper's.",
  },
};

const CONCLUSIONS: Record<RelationshipType, string> = {
  FOUNDATIONAL: "The seed paper builds on this earlier work.",
  METHOD_EXTENSION: "It builds on the seed paper's method.",
  SIMILAR: "It works on a closely matching problem.",
  RECENT: "It is newer work on the seed paper's problem.",
  COMPETING: "It takes a different approach to the same problem.",
  DATASET_RELATED: "It works with the same data as the seed paper.",
  POTENTIALLY_CONTRADICTORY: "Its findings may contradict the seed paper's.",
};

/** The relationship stated as a finding about the connected paper. */
export function conclusion(type: RelationshipType): string {
  return CONCLUSIONS[type];
}

const CONFIDENCE_ORDER: Record<Confidence, number> = { high: 0, medium: 1, low: 2 };

export function flattenTrail(trail: GroupedTrail): TrailEntry[] {
  return RELATIONSHIP_TYPES.flatMap((type) =>
    [...(trail.groups[type] ?? [])]
      .sort(
        (a, b) =>
          CONFIDENCE_ORDER[a.edge.confidence] - CONFIDENCE_ORDER[b.edge.confidence] ||
          (a.target.title ?? "").localeCompare(b.target.title ?? ""),
      )
      .map((e) => ({ ...e, type })),
  );
}

export const pct = (value: number) => `${Math.round(value * 100)}%`;

/** Why the rule fired, in plain language, with the measured values it fired
 * on where the run recorded them -- and without numbers where it did not. */
export function ruleReasons(entry: TrailEntry, seedYear?: number | null): string[] {
  const s = entry.ranking?.signals ?? {};
  const year = entry.target.year;
  switch (entry.edge.rule_fired) {
    case "cited_by_seed AND target_year < seed_year":
      return [
        "The seed paper cites it.",
        year && seedYear ? `It came first: ${year}, before the seed's ${seedYear}.` : year ? `It came first (${year}).` : "It came first.",
      ];
    case "target_year > seed_year AND (problem_sim>=0.45 OR semantic_doc>=0.45)": {
      const overlap = Math.max(s.problem_sim ?? -1, s.semantic_doc ?? -1);
      return [
        year && seedYear ? `It is newer: ${year}, after the seed's ${seedYear}.` : "It is newer than the seed paper.",
        overlap >= 0 ? `Its topic overlaps the seed's: ${pct(overlap)} similar (the rule needs 45%).` : "Its topic overlaps the seed's.",
      ];
    }
    case "shared_dataset_name_in_target_abstract OR dataset_overlap>=0.5":
      return entry.edge.evidence.some((e) => e.role === "shared_dataset")
        ? ["Its abstract names a dataset the seed paper uses."]
        : [
            s.dataset_overlap != null
              ? `Its datasets overlap the seed's by ${pct(s.dataset_overlap)} (the rule needs 50%).`
              : "Its datasets overlap the seed's.",
          ];
    case "cites_seed AND method_sim>=0.55":
      return [
        "It cites the seed paper.",
        s.method_sim != null ? `Its method is ${pct(s.method_sim)} similar to the seed's (the rule needs 55%).` : "Its method is similar to the seed's.",
      ];
    case "problem_sim>=0.55 AND method_sim<0.40 AND citation_relationship=none":
      return [
        s.problem_sim != null ? `It tackles the same problem: ${pct(s.problem_sim)} similar (the rule needs 55%).` : "It tackles the same problem.",
        s.method_sim != null ? `Its method differs: only ${pct(s.method_sim)} similar (the rule needs under 40%).` : "Its method differs.",
        "Neither paper cites the other.",
      ];
    case "semantic_doc>=0.65 OR problem_sim>=0.60":
      if (s.semantic_doc != null && s.semantic_doc >= 0.65)
        return [`Its overall topic is ${pct(s.semantic_doc)} similar to the seed's (the rule needs 65%).`];
      if (s.problem_sim != null && s.problem_sim >= 0.6)
        return [`Its research problem is ${pct(s.problem_sim)} similar to the seed's (the rule needs 60%).`];
      return ["Its overall topic closely matches the seed's."];
    case "topical_overlap AND negation_cue_in_target_abstract AND seed_has_findings":
      return [
        "Its topic overlaps the seed's.",
        "Its abstract negates or disputes a result.",
        "A language model found a claim in each paper that conflicts.",
      ];
    default:
      return entry.edge.rule_fired ? [`Rule: ${entry.edge.rule_fired}`] : [];
  }
}

export function detectionLabel(method: TrailEdge["detection_method"]): string {
  switch (method) {
    case "rule_llm_confirmed":
      return "Found by a rule, confirmed by a language model";
    case "contradiction_nli":
      return "Checked for contradiction by a language model";
    case "user":
      return "Added by you";
    default:
      return "Found by a rule";
  }
}

/** An edge from connecting the workspace's own papers rather than from a
 * discovery run: those runs are named `run_wsp_<workspace>`
 * (app/services/trail/workspace_trail.py, workspace_run_id). */
export function fromWorkspacePapers(runId: string): boolean {
  return runId.startsWith("run_wsp_");
}

/** The system's own reasons for the confidence band, from the basis it
 * recorded (app/services/trail/confidence.py). */
export function confidenceReasons(edge: TrailEdge): string[] {
  const b = edge.confidence_basis;
  const out: string[] = [];
  if (typeof b.signal_agreement === "number") {
    const n = b.signal_agreement;
    out.push(n === 0 ? "No ranking signal agrees." : n === 1 ? "1 ranking signal agrees." : `${n} ranking signals agree.`);
  }
  if (typeof b.evidence_complete === "boolean") {
    out.push(b.evidence_complete ? "The evidence is complete." : "The evidence is incomplete.");
  }
  if (b.llm_disagreed === true) {
    out.push("A language model reviewed it and did not confirm it.");
  } else if (edge.llm_confirmed) {
    const certainty = typeof b.llm_certainty === "string" && b.llm_certainty !== "none" ? ` with ${b.llm_certainty} certainty` : "";
    out.push(`A language model confirmed it${certainty}.`);
  } else {
    out.push(
      edge.confidence === "high"
        ? "Not checked by a language model."
        : "Not checked by a language model, and high confidence needs that confirmation.",
    );
  }
  if (edge.relationship_type === "POTENTIALLY_CONTRADICTORY") out.push("Contradictions are capped at medium confidence.");
  return out;
}

export interface EvidenceDescription {
  side: "seed" | "target";
  label: string;
  /** The span is only the connected paper's title: a record, not a claim. */
  titleOnly: boolean;
  location: string | null;
}

const TITLE_ONLY_ROLES = new Set(["citation", "similarity_signal", "competing_signal", "recency"]);

export function describeEvidence(ev: TrailEvidence): EvidenceDescription {
  const { section, page } = ev.span;
  const location = [section, page != null ? `page ${page}` : null].filter(Boolean).join(", ") || null;
  switch (ev.role) {
    case "seed_reference":
      return { side: "seed", label: "The seed paper's reference list", titleOnly: false, location };
    case "seed_claim":
      return { side: "seed", label: "The seed paper, in its own words", titleOnly: false, location };
    case "target_claim":
      return { side: "target", label: section ? `This paper's ${section.toLowerCase()}` : "This paper's text", titleOnly: false, location };
    case "shared_dataset":
      return { side: "target", label: "The shared dataset, named in this paper's abstract", titleOnly: false, location };
    default:
      if (TITLE_ONLY_ROLES.has(ev.role)) {
        return { side: "target", label: ev.role === "citation" ? "Citation record" : "Measured similarity", titleOnly: true, location };
      }
      return { side: "target", label: ev.role.replace(/_/g, " "), titleOnly: false, location };
  }
}

export function countByState(entries: TrailEntry[]): Record<EdgeUserState, number> {
  const counts: Record<EdgeUserState, number> = { pending: 0, accepted: 0, rejected: 0 };
  for (const e of entries) counts[e.edge.user_state] += 1;
  return counts;
}

export interface TrailFilter {
  state: EdgeUserState;
  types?: Set<RelationshipType>;
  band?: Confidence;
  query?: string;
}

/** Search matches every term against the paper's title, authors and venue
 * and the evidence quotes -- the real text of the trail, nothing derived. */
export function filterTrail(entries: TrailEntry[], filter: TrailFilter): TrailEntry[] {
  const terms = (filter.query ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  return entries.filter((e) => {
    if (e.edge.user_state !== filter.state) return false;
    if (filter.types && filter.types.size > 0 && !filter.types.has(e.type)) return false;
    if (filter.band && e.edge.confidence !== filter.band) return false;
    if (terms.length === 0) return true;
    const haystack = [e.target.title, ...(e.target.authors ?? []), e.target.venue, ...e.edge.evidence.map((ev) => ev.span.quote)]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return terms.every((t) => haystack.includes(t));
  });
}
