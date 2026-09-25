"use client";

import { useId, useState } from "react";
import Link from "next/link";
import {
  ArrowSquareOut,
  ArrowsOutSimple,
  CaretDown,
  CheckCircle,
  Crosshair,
  GitBranch,
  Path,
  Plus,
  X,
} from "@phosphor-icons/react/dist/ssr";
import type { Confidence, EdgeUserState, RelationshipType } from "@/lib/api/types";
import { EDGE_STYLE, otherEnd, shortAuthors, type EdgeState, type GEdge, type GNode, type GraphModel } from "@/lib/graph/model";
import { truncate } from "@/lib/graph/labels";
import { RELATIONSHIP_COPY, conclusion, confidenceReasons, describeEvidence, ruleReasons, type TrailEntry } from "@/lib/trail";
import type { GraphEdgeType } from "@/lib/api/types";
import { C, InlineError, focusRing, primaryButton, quietButton } from "../ui";
import type { Selection } from "./GraphCanvas";

const BAND_LABEL: Record<Confidence, string> = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
const BAND_COLOR: Record<Confidence, string> = { high: C.mint, medium: C.ink, low: C.warning };
const STATUS: Record<GNode["kind"], string> = {
  seed: "Seed paper",
  member: "In this workspace",
  connected: "Connected, not in this workspace",
};

export interface SeedInfo {
  id: string;
  title: string | null;
  year: number | null;
}

/** A short drawn sample of a relationship's line: its colour, pattern and
 * arrow. Doubles as the legend in the filter chips. */
export function EdgeSwatch({ type, state = "accepted" }: { type: GraphEdgeType; state?: EdgeState }) {
  const s = EDGE_STYLE[type];
  return (
    <svg width="26" height="10" viewBox="0 0 26 10" aria-hidden className="shrink-0">
      <line
        x1="1"
        y1="5"
        x2={s.arrow ? 20 : 25}
        y2="5"
        stroke={s.color}
        strokeWidth={s.width + 0.4}
        strokeDasharray={s.dash ?? undefined}
        strokeLinecap={s.dash?.startsWith("1.5") ? "round" : "butt"}
        opacity={state === "pending" ? 0.45 : 1}
      />
      {s.arrow && <path d="M19 1.5L25.5 5L19 8.5z" fill={s.color} opacity={state === "pending" ? 0.45 : 1} />}
    </svg>
  );
}

export function NodeGlyph({ kind, size = 12 }: { kind: GNode["kind"]; size?: number }) {
  const r = size / 2 - 1.5;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="shrink-0">
      {kind === "connected" ? (
        <circle cx={size / 2} cy={size / 2} r={r} fill="#0b1226" stroke="#cfe0ff" strokeWidth="1.5" />
      ) : (
        <circle cx={size / 2} cy={size / 2} r={r} fill={C.mint} stroke={kind === "seed" ? "#e9fff4" : "none"} strokeWidth="1.5" />
      )}
    </svg>
  );
}

interface GraphPanelProps {
  model: GraphModel;
  selection: Selection;
  workspaceId: string;
  seed: SeedInfo;
  trailById: Map<string, TrailEntry>;
  path: { from: string; to: string; nodes: string[]; edges: string[] } | null;
  /** The node a path is being traced from, while the second is picked. */
  pathFrom: string | null;
  focusedOn: string | null;
  hiddenNeighbours: number;
  onClose: () => void;
  onSelect: (selection: Selection) => void;
  onFocus: (id: string | null) => void;
  onExpand: (id: string) => void;
  onTracePath: (id: string | null) => void;
  onDecide: (edge: GEdge, trailEdgeIds: string[], state: EdgeUserState, title: string) => Promise<void>;
  onAdd: (node: GNode, runId: string | null) => Promise<void>;
}

const actionClass = `inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors hover:bg-white/10 disabled:opacity-60 sm:min-h-9 ${focusRing}`;

export function GraphPanel(props: GraphPanelProps) {
  const { model, selection, onClose } = props;
  const headingId = useId();
  const node = selection.kind === "node" ? model.byId.get(selection.id) : undefined;
  const edge = selection.kind === "edge" ? model.edges.find((e) => e.key === selection.key) : undefined;

  return (
    <aside
      aria-labelledby={headingId}
      className="relative flex max-h-full flex-col overflow-hidden rounded-2xl backdrop-blur-md"
      style={{ background: "rgba(10,15,32,.9)", border: `1px solid ${C.lineStrong}` }}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close the details"
        className={`absolute right-2 top-2 z-10 inline-flex size-11 items-center justify-center rounded-full transition-colors hover:bg-white/10 sm:size-9 ${focusRing}`}
        style={{ color: C.muted }}
      >
        <X className="size-4" weight="bold" aria-hidden />
      </button>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-5 pb-5 pt-4 [scrollbar-color:rgba(150,175,230,.28)_transparent]">
        {props.path && <PathSummary {...props} path={props.path} />}
        {/* keyed, so each paper or connection opens fresh rather than inheriting the last one's disclosures */}
        {node ? (
          <NodeDetails key={node.id} {...props} node={node} headingId={headingId} />
        ) : edge ? (
          <EdgeDetails key={edge.key} {...props} edge={edge} headingId={headingId} />
        ) : null}
      </div>
    </aside>
  );
}

function PathSummary({ model, path, onSelect, onTracePath }: GraphPanelProps & { path: NonNullable<GraphPanelProps["path"]> }) {
  const title = (id: string) => truncate(model.byId.get(id)?.title ?? id, 44);
  return (
    <section aria-label="Path between two papers" className="mb-5 mt-8 rounded-xl p-4" style={{ background: "rgba(93,240,168,.07)", border: `1px solid rgba(93,240,168,.25)` }}>
      <h3 className="text-sm font-bold">
        {path.nodes.length - 1 === 1 ? "Directly connected" : `Connected in ${path.nodes.length - 1} steps`}
      </h3>
      <ol className="mt-2 space-y-1.5 text-[13px] leading-snug">
        {path.edges.map((key) => {
          const e = model.edges.find((x) => x.key === key);
          if (!e) return null;
          return (
            <li key={key} className="flex gap-2">
              <span className="mt-[5px]">
                <EdgeSwatch type={e.type} state={e.state} />
              </span>
              <span>{EDGE_STYLE[e.type].describe(title(e.src), title(e.dst))}.</span>
            </li>
          );
        })}
      </ol>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        <button type="button" onClick={() => onSelect({ kind: "node", id: path.to })} className={`min-h-11 text-[13px] underline underline-offset-4 hover:text-white sm:min-h-0 ${focusRing}`} style={{ color: C.muted }}>
          Details of {truncate(model.byId.get(path.to)?.title ?? path.to, 30)}
        </button>
        <button type="button" onClick={() => onTracePath(null)} className={`min-h-11 text-[13px] underline underline-offset-4 hover:text-white sm:min-h-0 ${focusRing}`} style={{ color: C.muted }}>
          Clear the path
        </button>
      </div>
    </section>
  );
}

function NodeDetails({
  model,
  node,
  headingId,
  workspaceId,
  trailById,
  pathFrom,
  focusedOn,
  hiddenNeighbours,
  seed,
  onFocus,
  onExpand,
  onTracePath,
  onAdd,
  onSelect,
  onDecide,
}: GraphPanelProps & { node: GNode; headingId: string }) {
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const incident = [...(model.incident.get(node.id) ?? [])].sort(
    (a, b) =>
      (a.state === "pending" ? 0 : 1) - (b.state === "pending" ? 0 : 1) ||
      (model.byId.get(otherEnd(a, node.id))?.title ?? "").localeCompare(model.byId.get(otherEnd(b, node.id))?.title ?? ""),
  );
  const meta = [shortAuthors(node.authors), node.venue, node.year != null ? String(node.year) : null].filter(Boolean).join(" · ");
  const firstTrailEdge = incident.flatMap((e) => e.trailEdgeIds)[0];
  const runId = incident.flatMap((e) => e.trailEdgeIds.map((id) => trailById.get(id)?.edge.run_id)).find(Boolean) ?? null;
  const focused = focusedOn === node.id;
  const tracingFromHere = pathFrom === node.id;

  async function add() {
    setAdding(true);
    setAddError(null);
    try {
      await onAdd(node, runId);
    } catch {
      setAddError("It wasn't added. Try again.");
    } finally {
      setAdding(false);
    }
  }

  return (
    <>
      <h2 id={headingId} className="pr-9 text-lg font-bold leading-snug tracking-[-0.01em]">
        {node.title}
      </h2>
      {meta && (
        <p className="mt-1 text-[13px]" style={{ color: C.muted }}>
          {meta}
        </p>
      )}
      <p className="mt-1.5 flex items-center gap-2 text-[13px] font-medium" style={{ color: node.kind === "connected" ? C.muted : C.mint }}>
        <NodeGlyph kind={node.kind} />
        {STATUS[node.kind]}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {node.kind === "connected" && (
          <button type="button" onClick={add} disabled={adding} className={`${actionClass} hover:bg-transparent`} style={primaryButton}>
            <Plus className="size-4" weight="bold" aria-hidden />
            {adding ? "Adding…" : "Add to workspace"}
          </button>
        )}
        <Link href={node.kind === "seed" ? `/seed/${node.id}` : `/papers/${node.id}`} className={actionClass} style={quietButton}>
          <ArrowSquareOut className="size-4" aria-hidden />
          Open paper
        </Link>
        <Link
          href={node.kind === "seed" || !firstTrailEdge ? `/workspace/${workspaceId}/trail` : `/workspace/${workspaceId}/trail?edge=${firstTrailEdge}`}
          className={actionClass}
          style={quietButton}
        >
          <GitBranch className="size-4" aria-hidden />
          {node.kind === "seed" ? "Open the trail" : "Show in trail"}
        </Link>
      </div>
      {addError && (
        <div className="mt-2">
          <InlineError message={addError} />
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5">
        {incident.length > 0 && (
          <button
            type="button"
            onClick={() => onFocus(focused ? null : node.id)}
            aria-pressed={focused}
            className={`inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium hover:text-white sm:min-h-9 ${focusRing}`}
            style={{ color: focused ? C.mint : C.muted }}
          >
            <Crosshair className="size-4" aria-hidden />
            {focused ? "Show the whole graph" : "Focus on its connections"}
          </button>
        )}
        {focusedOn && !focused && hiddenNeighbours > 0 && (
          <button
            type="button"
            onClick={() => onExpand(node.id)}
            className={`inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium hover:text-white sm:min-h-9 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <ArrowsOutSimple className="size-4" aria-hidden />
            Expand {hiddenNeighbours} more connection{hiddenNeighbours === 1 ? "" : "s"}
          </button>
        )}
        {model.nodes.length > 2 && (
          <button
            type="button"
            onClick={() => onTracePath(tracingFromHere ? null : node.id)}
            aria-pressed={tracingFromHere}
            className={`inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium hover:text-white sm:min-h-9 ${focusRing}`}
            style={{ color: tracingFromHere ? C.mint : C.muted }}
          >
            <Path className="size-4" aria-hidden />
            {tracingFromHere ? "Cancel tracing" : "Trace a path from here"}
          </button>
        )}
      </div>

      <section aria-labelledby={`${headingId}-connections`} className="mt-5 border-t pt-4" style={{ borderColor: C.line }}>
        <h3 id={`${headingId}-connections`} className="text-sm font-bold">
          Connections <span className="tabular-nums" style={{ color: C.muted }}>{incident.length}</span>
        </h3>
        {incident.length === 0 ? (
          <p className="mt-2 text-[13px] leading-relaxed" style={{ color: C.muted }}>
            {node.kind === "seed"
              ? "No connections yet. They come from discovering related papers."
              : "No accepted or pending connection links this paper to the others here."}
          </p>
        ) : (
          <ul className="mt-2 divide-y" style={{ borderColor: C.line }}>
            {incident.map((e, i) => (
              <ConnectionItem
                key={e.key}
                model={model}
                seed={seed}
                trailById={trailById}
                edge={e}
                from={node.id}
                defaultOpen={i === 0 && node.kind !== "seed"}
                onSelect={onSelect}
                onDecide={onDecide}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function EdgeDetails({ model, edge, headingId, trailById, workspaceId, seed, onSelect, onDecide }: GraphPanelProps & { edge: GEdge; headingId: string }) {
  const src = model.byId.get(edge.src)!;
  const dst = model.byId.get(edge.dst)!;
  const label = edge.relationshipTypes.length
    ? edge.relationshipTypes.map((t) => RELATIONSHIP_COPY[t].singular).join(" and ")
    : EDGE_STYLE[edge.type].label;
  return (
    <>
      <h2 id={headingId} className="flex items-center gap-2.5 pr-9 text-lg font-bold leading-snug tracking-[-0.01em]">
        <EdgeSwatch type={edge.type} state={edge.state} />
        {label}
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed" style={{ color: C.muted }}>
        {EDGE_STYLE[edge.type].describe(truncate(src.title, 60), truncate(dst.title, 60))}.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {[src, dst].map((n) => (
          <button
            key={n.id}
            type="button"
            onClick={() => onSelect({ kind: "node", id: n.id })}
            className={`${actionClass} max-w-full`}
            style={quietButton}
          >
            <NodeGlyph kind={n.kind} />
            <span className="truncate">{truncate(n.title, 34)}</span>
          </button>
        ))}
        {edge.trailEdgeIds[0] && (
          <Link href={`/workspace/${workspaceId}/trail?edge=${edge.trailEdgeIds[0]}`} className={actionClass} style={quietButton}>
            <GitBranch className="size-4" aria-hidden />
            Show in trail
          </Link>
        )}
      </div>
      <ul className="mt-4 divide-y border-t" style={{ borderColor: C.line }}>
        <ConnectionItem model={model} seed={seed} trailById={trailById} edge={edge} from={edge.src} defaultOpen hideOther onSelect={onSelect} onDecide={onDecide} />
      </ul>
    </>
  );
}

function ConnectionItem({
  model,
  edge,
  from,
  seed,
  trailById,
  defaultOpen,
  hideOther,
  onSelect,
  onDecide,
}: Pick<GraphPanelProps, "model" | "seed" | "trailById" | "onSelect" | "onDecide"> & {
  edge: GEdge;
  from: string;
  defaultOpen?: boolean;
  hideOther?: boolean;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyId = useId();
  const other = model.byId.get(otherEnd(edge, from))!;
  const target = model.byId.get(edge.dst)!;
  const entries = edge.trailEdgeIds.map((id) => trailById.get(id)).filter((e): e is TrailEntry => e != null);
  const types: RelationshipType[] = entries.length ? entries.map((e) => e.type) : edge.relationshipTypes;
  const label = types.length ? types.map((t) => RELATIONSHIP_COPY[t].singular).join(" and ") : EDGE_STYLE[edge.type].label;
  const pendingIds = entries.length
    ? entries.filter((e) => e.edge.user_state === "pending").map((e) => e.edge.edge_id)
    : edge.state === "pending"
      ? edge.trailEdgeIds
      : [];

  async function decide(state: EdgeUserState) {
    setBusy(true);
    setError(null);
    try {
      await onDecide(edge, state === "accepted" ? pendingIds : edge.trailEdgeIds, state, target.title);
    } catch {
      setError("That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="py-3" style={{ borderColor: C.line }}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
        <EdgeSwatch type={edge.type} state={edge.state} />
        <span className="font-semibold">{label}</span>
        <span style={{ color: C.muted }}>·</span>
        <span style={{ color: edge.state === "pending" ? C.warning : C.mint }}>{edge.state === "pending" ? "To review" : "Accepted"}</span>
        <span style={{ color: C.muted }}>·</span>
        <span style={{ color: BAND_COLOR[edge.confidence] }}>{BAND_LABEL[edge.confidence]}</span>
      </div>
      {!hideOther && (
        <button
          type="button"
          onClick={() => onSelect({ kind: "node", id: other.id })}
          className={`mt-1 flex min-h-11 items-start gap-2 text-left text-sm font-medium leading-snug hover:text-white sm:min-h-0 ${focusRing}`}
          style={{ color: C.ink }}
        >
          <span className="mt-[3px]">
            <NodeGlyph kind={other.kind} size={11} />
          </span>
          <span className="underline decoration-[rgba(93,240,168,0.4)] underline-offset-4">{other.title}</span>
        </button>
      )}
      <p className="mt-1 text-[13px] leading-relaxed" style={{ color: C.muted }}>
        {types.length ? conclusion(types[0]) : `${EDGE_STYLE[edge.type].label}.`}
      </p>

      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
        className={`mt-1 inline-flex min-h-11 items-center gap-1 text-[13px] font-medium hover:text-white sm:min-h-8 ${focusRing}`}
        style={{ color: C.mint }}
      >
        {open ? "Hide the evidence" : `Show the evidence (${entries.length ? entries.reduce((n, e) => n + e.edge.evidence.length, 0) : edge.evidence.length})`}
        <CaretDown className={`size-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`} weight="bold" aria-hidden />
      </button>

      {open && (
        <div id={bodyId} className="mt-2 space-y-4">
          {entries.length > 0
            ? entries.map((entry) => <EntryEvidence key={entry.edge.edge_id} entry={entry} seed={seed} targetTitle={target.title} />)
            : edge.evidence.map((span, i) => (
                <blockquote key={i} className="border-l pl-3 text-sm leading-relaxed" style={{ borderColor: C.lineStrong }}>
                  &ldquo;{span.quote}&rdquo;
                </blockquote>
              ))}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {edge.state === "pending" ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => decide("accepted")}
              aria-label={`Accept the connection to ${target.title}`}
              className={`${actionClass} hover:bg-transparent`}
              style={primaryButton}
            >
              <CheckCircle className="size-4" weight="bold" aria-hidden />
              Accept
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => decide("rejected")}
              aria-label={`Reject the connection to ${target.title}`}
              className={actionClass}
              style={quietButton}
            >
              Reject
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => decide("rejected")}
            aria-label={`Reject the connection to ${target.title}`}
            className={`inline-flex min-h-11 items-center rounded-sm text-[13px] underline underline-offset-4 hover:text-white disabled:opacity-60 sm:min-h-0 ${focusRing}`}
            style={{ color: C.muted }}
          >
            Reject this connection
          </button>
        )}
      </div>
      {error && (
        <div className="mt-2">
          <InlineError message={error} />
        </div>
      )}
    </li>
  );
}

function EntryEvidence({ entry, seed, targetTitle }: { entry: TrailEntry; seed: SeedInfo; targetTitle: string }) {
  const reasons = ruleReasons(entry, seed.year);
  return (
    <div className="space-y-3">
      {entry.edge.evidence.map((ev, i) => {
        const d = describeEvidence(ev);
        return (
          <div key={i}>
            <p className="text-[12.5px]" style={{ color: C.muted }}>
              <span className="font-semibold" style={{ color: C.ink }}>
                {d.label}
              </span>
              {d.location && ` · ${d.location}`}
              {!d.titleOnly && <> · {truncate(d.side === "seed" ? (seed.title ?? "the seed paper") : targetTitle, 48)}</>}
            </p>
            {d.titleOnly ? (
              <p className="mt-1 text-[13px]" style={{ color: C.muted }}>
                Only this paper&apos;s title is on record for this link; it rests on the measured signals below.
              </p>
            ) : (
              <blockquote className="mt-1 border-l pl-3 text-sm leading-relaxed" style={{ borderColor: C.lineStrong, color: C.ink }}>
                &ldquo;{ev.span.quote}&rdquo;
              </blockquote>
            )}
          </div>
        );
      })}
      {reasons.length > 0 && (
        <ul className="space-y-1 text-[13px]" style={{ color: C.ink }}>
          {reasons.map((reason) => (
            <li key={reason} className="flex gap-2">
              <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full" style={{ background: C.mint }} />
              {reason}
            </li>
          ))}
        </ul>
      )}
      <ul className="space-y-0.5 text-[12.5px]" style={{ color: C.muted }}>
        {confidenceReasons(entry.edge).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  );
}
