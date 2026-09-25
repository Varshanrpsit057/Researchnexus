"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { useReducedMotion } from "motion/react";
import { ArrowLeft, Crosshair, FrameCorners, MagnifyingGlass, Minus, Path, Plus, X } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { papers as papersApi, workspaces } from "@/lib/api/endpoints";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import type { EdgeUserState, GraphEdgeType } from "@/lib/api/types";
import { MORPH } from "@/components/effects/constellation/field";
import { CinematicHeader } from "@/components/layout/CinematicHeader";
import { sendToBackground } from "@/lib/background-bus";
import { boundsOf, centerOn, fitCamera, lerpCamera, toScreen, zoomAt, type Camera, type Insets } from "@/lib/graph/camera";
import { truncate } from "@/lib/graph/labels";
import { NODE_RADIUS, layoutGraph, type Layout } from "@/lib/graph/layout";
import {
  EDGE_STYLE,
  EDGE_TYPE_ORDER,
  buildModel,
  countBy,
  neighbourhood,
  otherEnd,
  searchNodes,
  shortestPath,
  topologyKey,
  visibleParts,
  type EdgeState,
  type GEdge,
  type GNode,
} from "@/lib/graph/model";
import { flattenTrail, type TrailEntry } from "@/lib/trail";
import { C, InlineError, WorkspaceLoadError, focusRing, primaryButton, quietButton } from "../ui";
import { GraphCanvas, type Highlight, type IntroTimeline, type Phase, type Selection } from "./GraphCanvas";
import { EdgeSwatch, GraphPanel, NodeGlyph } from "./GraphPanel";

const ALL_STATES: EdgeState[] = ["accepted", "pending"];
const STATE_LABEL: Record<EdgeState, string> = { accepted: "Accepted", pending: "To review" };
const KIND_LABEL: Record<GNode["kind"], string> = {
  seed: "Seed paper",
  member: "In this workspace",
  connected: "Connected, not in this workspace",
};

function subscribeMedia(query: string) {
  return (onChange: () => void) => {
    const mq = window.matchMedia(query);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  };
}

function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeMedia(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => true,
  );
}

const nodeZoom = (k: number) => Math.max(0.75, Math.min(1.3, k));

/** The entrance, timed against the background's morph: nodes emerge as the
 * converging knots arrive (seed first, then outward), edges draw after them
 * in the same outward order, labels and the axis follow. */
function introTimeline(nodes: GNode[], edges: GEdge[], layout: Layout, seedId: string | null): IntroTimeline & { total: number } {
  const origin = (seedId && layout.pos.get(seedId)) || { x: 0, y: 0 };
  const dist = (id: string) => {
    const p = layout.pos.get(id)!;
    return Math.hypot(p.x - origin.x, p.y - origin.y);
  };
  const nodeStart = MORPH.converge[1] - 0.28;
  const nodeStagger = Math.min(0.045, 0.5 / Math.max(1, nodes.length));
  const node = new Map([...nodes].sort((a, b) => dist(a.id) - dist(b.id)).map((n, i) => [n.id, nodeStart + i * nodeStagger]));
  const edgeStart = MORPH.converge[1] + 0.12;
  const edgeStagger = Math.min(0.05, 0.7 / Math.max(1, edges.length));
  const far = (e: GEdge) => Math.max(dist(e.src), dist(e.dst));
  const edge = new Map([...edges].sort((a, b) => far(a) - far(b)).map((e, i) => [e.key, edgeStart + i * edgeStagger]));
  const lastNode = nodeStart + Math.max(0, nodes.length - 1) * nodeStagger + 0.56;
  const lastEdge = edges.length ? edgeStart + (edges.length - 1) * edgeStagger + 0.95 : 0;
  return { node, edge, chrome: nodeStart + 0.35, total: Math.max(MORPH.handoff[1], lastNode, lastEdge) + 0.1 };
}

type PathResult = { from: string; to: string; nodes: string[]; edges: string[] };

export default function GraphPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { mutate: mutateGlobal } = useSWRConfig();
  const reduceMotion = useReducedMotion() ?? false;
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  // ?paper=<id>: arrive with that paper selected (from a chat source, say)
  const linkedPaper = useSearchParams().get("paper");
  const linkApplied = useRef(false);

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  const graphQ = useSWR(ready && workspaceQ.data ? ["ws-graph", id] : null, () => workspaces.graph(id));
  // the evidence behind each connection, shared with the trail page's cache
  const trailQ = useSWR(ready && workspaceQ.data ? ["ws-trail-all", id] : null, () => workspaces.trail(id, { state: "all" }));
  const workspace = workspaceQ.data;

  const [hiddenTypes, setHiddenTypes] = useState<Set<GraphEdgeType>>(() => new Set());
  const [states, setStates] = useState<Set<EdgeState>>(() => new Set(ALL_STATES));
  const [focus, setFocus] = useState<{ on: string; nodes: Set<string> } | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [hover, setHover] = useState<Selection | null>(null);
  const [pathFrom, setPathFrom] = useState<string | null>(null);
  const [path, setPath] = useState<PathResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [cam, setCam] = useState<Camera | null>(null);
  const [phase, setPhase] = useState<Phase>("hidden");
  const [layoutState, setLayoutState] = useState<{ key: string; layout: Layout } | null>(null);
  const [relayout, setRelayout] = useState(false);

  const model = useMemo(() => (graphQ.data ? buildModel(graphQ.data, workspace?.seed_paper_id) : null), [graphQ.data, workspace?.seed_paper_id]);

  // Layout follows topology only, and settles from the previous positions
  // (stored from the last render, React's derived-state pattern).
  const key = model ? topologyKey(model) : "";
  if (model && layoutState?.key !== key) {
    setLayoutState({ key, layout: layoutGraph(model, layoutState?.layout.pos) });
    if (layoutState) setRelayout(true);
  }
  const layout = model && layoutState?.key === key ? layoutState.layout : null;

  const trailById = useMemo(() => {
    const map = new Map<string, TrailEntry>();
    if (trailQ.data) for (const entry of flattenTrail(trailQ.data)) map.set(entry.edge.edge_id, entry);
    return map;
  }, [trailQ.data]);

  const seedId = model?.seedId ?? workspace?.seed_paper_id ?? "";
  const seedPaperQ = useSWR(seedId && trailQ.data && !trailQ.data.seed?.title ? ["paper", seedId] : null, () => papersApi.get(seedId));
  const seed = {
    id: seedId,
    title: trailQ.data?.seed?.title ?? seedPaperQ.data?.title ?? model?.byId.get(seedId)?.title ?? null,
    year: trailQ.data?.seed?.year ?? seedPaperQ.data?.year ?? model?.byId.get(seedId)?.year ?? null,
  };

  const visible = useMemo(
    () => (model ? visibleParts(model, { hiddenTypes, states, focus: focus?.nodes ?? null }) : { nodes: new Set<string>(), edges: new Set<string>() }),
    [model, hiddenTypes, states, focus],
  );

  // a selection whose node or edge left the graph (rejected, filtered) is dropped
  const selectionLive =
    selection && model
      ? selection.kind === "node"
        ? visible.nodes.has(selection.id)
        : visible.edges.has(selection.key)
      : false;
  if (selection && model && !selectionLive) setSelection(null);
  const activeSelection = selectionLive ? selection : null;
  if (path && model && !path.edges.every((e) => visible.edges.has(e))) setPath(null);

  const intro = useMemo(
    () => (model && layout ? introTimeline(model.nodes, model.edges, layout, model.seedId) : { node: new Map(), edge: new Map(), chrome: 0, total: 0 }),
    [model, layout],
  );

  // --- stage size and camera -------------------------------------------------
  useEffect(() => {
    if (!stageEl) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      const h = Math.round(entry.contentRect.height);
      setSize((prev) => {
        if (prev && prev.w === w && prev.h === h) return prev;
        // keep whatever was centred still centred
        if (prev) setCam((c) => (c ? { ...c, x: c.x + (w - prev.w) / 2, y: c.y + (h - prev.h) / 2 } : c));
        return { w, h };
      });
    });
    ro.observe(stageEl);
    return () => ro.disconnect();
  }, [stageEl]);

  const panelOpen = activeSelection != null || path != null;
  const insetsFor = useCallback(
    (withPanel: boolean, stageHeight = size?.h ?? 600): Insets =>
      isDesktop
        ? { top: 76, right: withPanel ? 444 : 56, bottom: 72, left: 88 }
        : { top: 56, right: 24, bottom: withPanel ? Math.round(stageHeight * 0.58) : 84, left: 24 },
    [isDesktop, size],
  );

  const camRef = useRef<Camera | null>(null);
  const flight = useRef(0);
  useEffect(() => {
    camRef.current = cam;
  }, [cam]);

  const flyTo = useCallback(
    (target: Camera) => {
      cancelAnimationFrame(flight.current);
      const from = camRef.current;
      if (reduceMotion || !from) {
        setCam(target);
        return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - t0) / 480);
        setCam(lerpCamera(from, target, 1 - Math.pow(1 - t, 3)));
        if (t < 1) flight.current = requestAnimationFrame(tick);
      };
      flight.current = requestAnimationFrame(tick);
    },
    [reduceMotion],
  );

  const onCamera = useCallback((update: (c: Camera) => Camera) => {
    cancelAnimationFrame(flight.current); // the user's own pan or zoom wins
    setCam((c) => (c ? update(c) : c));
  }, []);

  useEffect(() => () => cancelAnimationFrame(flight.current), []);

  function fitTo(ids: Iterable<string>, withPanel = panelOpen, maxK = 1.6) {
    if (!layout || !size) return;
    const points = [...ids].map((n) => layout.pos.get(n)).filter((p): p is { x: number; y: number } => p != null);
    if (points.length === 0) return;
    flyTo(fitCamera(boundsOf(points, 20), size.w, size.h, insetsFor(withPanel), maxK));
  }

  const inClearArea = (nodeId: string, withPanel: boolean) => {
    if (!layout || !size || !cam) return true;
    const p = layout.pos.get(nodeId);
    if (!p) return true;
    const s = toScreen(cam, p);
    const inset = insetsFor(withPanel);
    const margin = 24;
    return s.x > inset.left - margin && s.x < size.w - inset.right + margin && s.y > inset.top - margin && s.y < size.h - inset.bottom + margin;
  };

  /** Show a selected paper with its connections when there are only a few
   * of them; for a hub (the seed), just make sure the paper itself shows. */
  function revealWithNeighbours(nodeId: string) {
    if (!model || !cam) return;
    const hood = [nodeId, ...(model.incident.get(nodeId) ?? []).filter((e) => visible.edges.has(e.key)).map((e) => otherEnd(e, nodeId))];
    if (hood.length <= 8 && !hood.every((n) => inClearArea(n, true))) fitTo(hood, true, cam.k);
    else reveal(nodeId, true);
  }

  /** Bring a node into the clear part of the stage if it is off screen or behind the panel. */
  function reveal(nodeId: string, withPanel: boolean) {
    if (!layout || !size || !cam) return;
    const p = layout.pos.get(nodeId);
    if (!p || inClearArea(nodeId, withPanel)) return;
    flyTo(centerOn(cam, p, size.w, size.h, insetsFor(withPanel)));
  }

  // --- the entrance: the background condenses into this graph --------------
  useEffect(() => {
    if (phase !== "hidden" || !model || !layout || !stageEl) return;
    // measured after the toolbar has laid out, so the fit is for the stage as it is
    const raf = requestAnimationFrame(() => {
      const rect = stageEl.getBoundingClientRect();
      const w = Math.round(rect.width);
      const h = Math.round(rect.height);
      const fit = fitCamera(layout.bounds, w, h, insetsFor(false, h));
      setSize({ w, h });
      setCam(fit);
      const targets = model.nodes
        .filter((n) => visible.nodes.has(n.id))
        .map((n) => {
          const s = toScreen(fit, layout.pos.get(n.id)!);
          return { x: rect.left + s.x, y: rect.top + s.y, r: NODE_RADIUS[n.kind] * nodeZoom(fit.k) };
        })
        .filter((t) => t.x > -40 && t.y > -40 && t.x < window.innerWidth + 40 && t.y < window.innerHeight + 40);
      sendToBackground({ type: "morph", targets });
      setPhase(reduceMotion ? "settled" : "intro");
    });
    return () => cancelAnimationFrame(raf);
  }, [phase, model, layout, stageEl, visible, reduceMotion, insetsFor]);

  useEffect(() => {
    if (phase !== "intro") return;
    const t = setTimeout(() => setPhase("settled"), intro.total * 1000);
    return () => clearTimeout(t);
  }, [phase, intro.total]);

  useEffect(() => {
    if (phase !== "settled" || !linkedPaper || linkApplied.current || !model?.byId.has(linkedPaper)) return;
    linkApplied.current = true;
    const raf = requestAnimationFrame(() => {
      setSelection({ kind: "node", id: linkedPaper });
      revealWithNeighboursRef.current?.(linkedPaper);
    });
    return () => cancelAnimationFrame(raf);
  }, [phase, linkedPaper, model]);

  // leaving the page gives the background its full field back
  useEffect(() => () => sendToBackground({ type: "release" }), []);

  useEffect(() => {
    if (!relayout) return;
    const t = setTimeout(() => setRelayout(false), 680);
    return () => clearTimeout(t);
  }, [relayout]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  // --- interaction -----------------------------------------------------------
  function select(next: Selection | null) {
    if (!model) return;
    if (pathFrom && next?.kind === "node" && next.id !== pathFrom) {
      const found = shortestPath(model, pathFrom, next.id, visible.edges);
      const from = model.byId.get(pathFrom)!.title;
      const to = model.byId.get(next.id)!.title;
      if (found) {
        setPath({ from: pathFrom, to: next.id, ...found });
        setAnnouncement(`Path traced: ${found.nodes.length - 1} step${found.nodes.length === 2 ? "" : "s"} from ${from} to ${to}.`);
        fitTo(found.nodes, true);
      } else {
        setPath(null);
        setNotice(`No connection path links “${truncate(from, 40)}” and “${truncate(to, 40)}” with the current filters.`);
      }
      setPathFrom(null);
      setSelection(next);
      return;
    }
    if (pathFrom && next == null) return; // picking: empty space does nothing
    setSelection(next);
    if (next == null) {
      setPath(null);
      return;
    }
    if (next.kind === "node") revealWithNeighbours(next.id);
    else {
      const e = model.edges.find((x) => x.key === next.key);
      if (e) reveal(otherEnd(e, model.seedId ?? e.src), true);
    }
  }

  const revealWithNeighboursRef = useRef<((id: string) => void) | null>(null);
  useEffect(() => {
    revealWithNeighboursRef.current = revealWithNeighbours;
  });

  function focusOn(nodeId: string | null) {
    if (!model) return;
    if (!nodeId) {
      setFocus(null);
      fitTo(model.nodes.map((n) => n.id));
      setAnnouncement("Showing the whole graph.");
      return;
    }
    const nodes = neighbourhood(model, nodeId);
    setFocus({ on: nodeId, nodes });
    setPath(null);
    fitTo(nodes, true);
    setAnnouncement(`Focused on ${model.byId.get(nodeId)?.title}: ${nodes.size - 1} connected paper${nodes.size === 2 ? "" : "s"}.`);
  }

  function expand(nodeId: string) {
    if (!model || !focus) return;
    const added = neighbourhood(model, nodeId);
    const nodes = new Set([...focus.nodes, ...added]);
    setFocus({ ...focus, nodes });
    fitTo(nodes, true);
    setAnnouncement(`Showing ${nodes.size - focus.nodes.size} more connected paper${nodes.size - focus.nodes.size === 1 ? "" : "s"}.`);
  }

  function tracePath(nodeId: string | null) {
    setPath(null);
    setPathFrom(nodeId);
    if (nodeId && model) setAnnouncement(`Choose a second paper to trace the path from ${model.byId.get(nodeId)?.title}.`);
  }

  function clearFilters() {
    setHiddenTypes(new Set());
    setStates(new Set(ALL_STATES));
    setFocus(null);
  }

  async function refresh() {
    await Promise.all([graphQ.mutate(), trailQ.mutate()]);
    // the overview and trail pages count connections and papers too
    void mutateGlobal(["ws-trail", id]);
    void mutateGlobal(["workspace", id]);
  }

  async function decide(edge: GEdge, trailEdgeIds: string[], state: EdgeUserState, title: string) {
    if (trailEdgeIds.length === 0) return;
    const results = await Promise.allSettled(trailEdgeIds.map((eid) => workspaces.setEdgeState(id, eid, state)));
    const saved = results.filter((r) => r.status === "fulfilled").length;
    await refresh();
    if (saved === 0) throw new Error("not saved");
    setAnnouncement(
      state === "accepted"
        ? `Accepted the connection to ${title}.`
        : `Rejected the connection to ${title}. It is kept on the trail's Rejected tab.`,
    );
    if (state === "rejected") setNotice(`Rejected the connection to “${truncate(title, 48)}”. You can restore it from the trail's Rejected tab.`);
  }

  async function addPaper(node: GNode, runId: string | null) {
    await workspaces.addPapers(id, { paper_ids: [node.id], from_run_id: runId ?? workspace?.source_run_id ?? null });
    await refresh();
    setAnnouncement(`Added ${node.title} to this workspace.`);
  }

  /** Zoom about the centre of the part of the stage the panel leaves clear. */
  function zoomBy(factor: number) {
    if (!size || !cam) return;
    const inset = insetsFor(panelOpen);
    const cx = inset.left + (size.w - inset.left - inset.right) / 2;
    const cy = inset.top + (size.h - inset.top - inset.bottom) / 2;
    flyTo(zoomAt(cam, factor, cx, cy));
  }

  function chooseFromSearch(n: GNode) {
    if (!visible.nodes.has(n.id)) {
      clearFilters();
      setAnnouncement(`Filters cleared to show ${n.title}.`);
    }
    setPath(null);
    setPathFrom(null);
    setSelection({ kind: "node", id: n.id });
    if (layout && size && cam) flyTo(centerOn(cam, layout.pos.get(n.id)!, size.w, size.h, insetsFor(true), Math.max(cam.k, 1)));
    requestAnimationFrame(() => document.querySelector<SVGGElement>(`[data-node="${CSS.escape(n.id)}"]`)?.focus({ preventScroll: true }));
  }

  function onStageKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!size || !cam) return;
    if (e.key === "+" || e.key === "=") zoomBy(1.3);
    else if (e.key === "-" || e.key === "_") zoomBy(1 / 1.3);
    else if (e.key === "0") fitTo(visible.nodes);
    else if (e.key === "Escape") {
      if (pathFrom) setPathFrom(null);
      else if (path) setPath(null);
      else if (activeSelection) setSelection(null);
      else if (focus) focusOn(null);
      else return;
    } else if (e.target === e.currentTarget && e.key.startsWith("Arrow")) {
      const step = 80;
      const dx = e.key === "ArrowLeft" ? step : e.key === "ArrowRight" ? -step : 0;
      const dy = e.key === "ArrowUp" ? step : e.key === "ArrowDown" ? -step : 0;
      onCamera((c) => ({ ...c, x: c.x + dx, y: c.y + dy }));
    } else return;
    e.preventDefault();
  }

  const describeNode = useCallback(
    (n: GNode) => {
      const edges = model?.incident.get(n.id) ?? [];
      const pending = edges.filter((e) => e.state === "pending").length;
      return [
        n.title,
        KIND_LABEL[n.kind],
        n.year != null ? String(n.year) : "Year unknown",
        `${edges.length} connection${edges.length === 1 ? "" : "s"}${pending ? `, ${pending} to review` : ""}`,
      ].join(". ");
    },
    [model],
  );

  // --- what is lit -------------------------------------------------------------
  let highlight: Highlight | null = null;
  if (model) {
    const around = (nodeId: string): Highlight => {
      const nodes = new Set([nodeId]);
      const edges = new Set<string>();
      for (const e of model.incident.get(nodeId) ?? []) {
        if (!visible.edges.has(e.key)) continue;
        edges.add(e.key);
        nodes.add(otherEnd(e, nodeId));
      }
      return { nodes, edges };
    };
    const onEdge = (key: string): Highlight | null => {
      const e = model.edges.find((x) => x.key === key);
      return e ? { nodes: new Set([e.src, e.dst]), edges: new Set([key]) } : null;
    };
    const lead = hover ?? activeSelection;
    if (path) highlight = { nodes: new Set(path.nodes), edges: new Set(path.edges) };
    else if (lead?.kind === "node" && visible.nodes.has(lead.id)) highlight = around(lead.id);
    else if (lead?.kind === "edge") highlight = onEdge(lead.key);
  }

  // --- counts for the header and the filters ---------------------------------
  const typeCounts = model ? countBy(model.edges.map((e) => e.type)) : new Map<GraphEdgeType, number>();
  const stateCounts = model ? countBy(model.edges.map((e) => e.state)) : new Map<EdgeState, number>();
  const presentTypes = EDGE_TYPE_ORDER.filter((t) => typeCounts.has(t));
  const papersIn = model?.nodes.filter((n) => n.kind !== "connected").length ?? 0;
  const connectedOnly = model?.nodes.filter((n) => n.kind === "connected").length ?? 0;
  const filtered = hiddenTypes.size > 0 || states.size < ALL_STATES.length || focus != null;
  const hiddenNeighbours =
    focus && model && activeSelection?.kind === "node" ? [...neighbourhood(model, activeSelection.id)].filter((n) => !focus.nodes.has(n)).length : 0;

  if (!ready) return null;

  const graphMissing = graphQ.error instanceof ApiError && graphQ.error.status === 404;
  if (workspaceQ.error || graphMissing) {
    return (
      <Shell>
        <div className="px-4">
          <WorkspaceLoadError error={workspaceQ.error ?? graphQ.error} onRetry={() => (workspaceQ.error ? workspaceQ.mutate() : graphQ.mutate())} />
        </div>
      </Shell>
    );
  }

  const settled = phase === "settled";

  return (
    <Shell>
      <div className="mx-auto w-full max-w-[1480px] shrink-0 px-4 pt-5 sm:px-6">
        {workspace ? (
          <Link
            href={`/workspace/${id}`}
            className={`inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <ArrowLeft className="size-4 shrink-0" aria-hidden />
            <span className="truncate">{workspace.title}</span>
          </Link>
        ) : (
          <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
        )}
        <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <h1 className="text-[clamp(24px,3vw,34px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Research graph</h1>
          {model && (
            <p className="text-sm tabular-nums" style={{ color: C.muted }}>
              {papersIn} paper{papersIn === 1 ? "" : "s"} in the workspace
              {connectedOnly > 0 && ` · ${connectedOnly} connected`} · {model.edges.length} connection{model.edges.length === 1 ? "" : "s"}
              {(stateCounts.get("pending") ?? 0) > 0 && ` · ${stateCounts.get("pending")} to review`}
            </p>
          )}
        </div>

        {model && model.edges.length > 0 && (
          <div className="mt-4 flex flex-col gap-2.5 lg:flex-row lg:items-center">
            <SearchBox model={model} onChoose={(n) => chooseFromSearch(n)} />
            <div
              className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [mask-image:linear-gradient(to_right,black_88%,transparent)] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0 sm:[mask-image:none]"
              role="group"
              aria-label="Show relationships"
            >
              {presentTypes.map((t) => {
                const on = !hiddenTypes.has(t);
                return (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setHiddenTypes((prev) => {
                        const next = new Set(prev);
                        if (next.has(t)) next.delete(t);
                        else next.add(t);
                        return next;
                      })
                    }
                    className={`inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full px-3 text-[13px] font-medium transition-[background-color,opacity] hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                    style={{ ...quietButton, opacity: on ? 1 : 0.5 }}
                  >
                    <EdgeSwatch type={t} />
                    {EDGE_STYLE[t].label}
                    <span className="tabular-nums" style={{ color: C.muted }}>
                      {typeCounts.get(t)}
                    </span>
                  </button>
                );
              })}
              <span aria-hidden className="mx-1 hidden w-px self-stretch sm:block" style={{ background: C.line }} />
              {ALL_STATES.filter((s) => stateCounts.has(s)).map((s) => {
                const on = states.has(s);
                return (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setStates((prev) => {
                        const next = new Set(prev);
                        if (next.has(s)) next.delete(s);
                        else next.add(s);
                        return next;
                      })
                    }
                    className={`inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full px-3 text-[13px] font-medium transition-[background-color,opacity] hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                    style={{ ...quietButton, opacity: on ? 1 : 0.5 }}
                  >
                    <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden className="shrink-0">
                      <line x1="1" y1="5" x2="17" y2="5" stroke={C.ink} strokeWidth="2" opacity={s === "pending" ? 0.4 : 0.95} />
                    </svg>
                    {STATE_LABEL[s]}
                    <span className="tabular-nums" style={{ color: C.muted }}>
                      {stateCounts.get(s)}
                    </span>
                  </button>
                );
              })}
              {filtered && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className={`min-h-11 shrink-0 rounded-sm px-2 text-[13px] underline underline-offset-4 hover:text-white sm:min-h-9 ${focusRing}`}
                  style={{ color: C.muted }}
                >
                  Clear filters
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      <div
        ref={setStageEl}
        tabIndex={-1}
        onKeyDown={onStageKey}
        data-phase={phase}
        data-testid="graph-stage"
        className="relative mt-3 min-h-[340px] flex-1 overflow-hidden outline-none"
      >
        {model && layout && cam && size && (
          <GraphCanvas
            model={model}
            layout={layout}
            visible={visible}
            cam={cam}
            size={size}
            phase={phase}
            intro={intro}
            selection={activeSelection}
            hover={hover}
            highlight={highlight}
            picking={pathFrom != null}
            relayout={relayout}
            covered={
              panelOpen
                ? isDesktop
                  ? { right: 444, bottom: 0 }
                  : { right: 0, bottom: Math.round(size.h * 0.56) + 8 }
                : { right: 0, bottom: 0 }
            }
            onCamera={onCamera}
            onSelect={select}
            onHover={setHover}
            onNodeFocus={(nodeId) => reveal(nodeId, panelOpen)}
            describeNode={describeNode}
          />
        )}

        {/* loading and failure sit over the live background, not a blank box */}
        {!graphQ.error && (!model || !layout) && (
          <div role="status" className="absolute inset-0 flex items-center justify-center">
            <p className="rounded-full px-4 py-2 text-sm backdrop-blur-sm" style={{ background: "rgba(10,15,32,.6)", color: C.muted, border: `1px solid ${C.line}` }}>
              Mapping the research graph…
            </p>
          </div>
        )}
        {graphQ.error && (
          <div className="absolute inset-0 flex items-center justify-center px-4" data-testid="graph-error">
            <div className="max-w-sm rounded-2xl p-6 text-center backdrop-blur-md" style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${C.lineStrong}` }}>
              <InlineError message="Could not load the research graph." />
              <button type="button" onClick={() => graphQ.mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Try again
              </button>
            </div>
          </div>
        )}

        {model && layout && settled && model.edges.length === 0 && workspace && (
          <div className="absolute inset-x-4 bottom-20 flex justify-center">
            <div className="max-w-md rounded-2xl px-6 py-5 text-center backdrop-blur-md" style={{ background: "rgba(10,15,32,.82)", border: `1px dashed ${C.lineStrong}` }}>
              <h2 className="text-base font-bold">No connections yet</h2>
              <p className="mt-1.5 text-sm leading-relaxed" style={{ color: C.muted }}>
                {workspace.source_run_id
                  ? "No rule linked a paper from this workspace's discovery run to the seed paper, so there is nothing to draw between them."
                  : "Connections come from discovering papers related to the seed. This workspace started from the seed paper alone."}
              </p>
              <Link
                href={workspace.source_run_id ? `/discover/${workspace.seed_paper_id}?run=${workspace.source_run_id}` : `/discover/${workspace.seed_paper_id}`}
                className={`mt-4 inline-flex rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                style={primaryButton}
              >
                {workspace.source_run_id ? "Open the discovery results" : "Discover related papers"}
              </Link>
            </div>
          </div>
        )}
        {model && settled && model.edges.length > 0 && visible.edges.size === 0 && (
          <div className="absolute inset-x-4 top-16 flex justify-center">
            <div className="rounded-2xl px-5 py-4 text-center text-sm backdrop-blur-md" style={{ background: "rgba(10,15,32,.82)", border: `1px dashed ${C.lineStrong}` }}>
              <p style={{ color: C.muted }}>No connections match these filters.</p>
              <button type="button" onClick={clearFilters} className={`mt-3 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={quietButton}>
                Clear filters
              </button>
            </div>
          </div>
        )}

        {/* what the view is doing right now */}
        {settled && (pathFrom || focus || notice) && (
          <div className="pointer-events-none absolute inset-x-3 top-3 flex justify-center lg:right-[444px]">
            <div
              className="pointer-events-auto flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl px-4 py-2 text-[13px] backdrop-blur-md"
              style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${pathFrom ? "rgba(93,240,168,.35)" : C.lineStrong}` }}
            >
              {pathFrom && model ? (
                <>
                  <Path className="size-4 shrink-0" style={{ color: C.mint }} aria-hidden />
                  <span>
                    Choose a second paper to trace the path from <strong className="font-semibold">{truncate(model.byId.get(pathFrom)?.title ?? "", 40)}</strong>
                  </span>
                  <BannerButton onClick={() => setPathFrom(null)}>Cancel</BannerButton>
                </>
              ) : notice ? (
                <>
                  <span style={{ color: C.muted }}>{notice}</span>
                  <BannerButton onClick={() => setNotice(null)} label="Dismiss">
                    <X className="size-3.5" weight="bold" aria-hidden />
                  </BannerButton>
                </>
              ) : focus && model ? (
                <>
                  <Crosshair className="size-4 shrink-0" style={{ color: C.mint }} aria-hidden />
                  <span>
                    Focused on <strong className="font-semibold">{truncate(model.byId.get(focus.on)?.title ?? "", 40)}</strong>
                    <span style={{ color: C.muted }}> and {focus.nodes.size - 1} connected</span>
                  </span>
                  <BannerButton onClick={() => focusOn(null)}>Show everything</BannerButton>
                </>
              ) : null}
            </div>
          </div>
        )}

        {model && layout && settled && (
          <>
            <div
              className={`absolute bottom-14 flex overflow-hidden rounded-2xl backdrop-blur-md ${isDesktop ? "left-4 flex-col" : "right-3 flex-row"} ${!isDesktop && panelOpen ? "hidden" : ""}`}
              style={{ background: "rgba(10,15,32,.72)", border: `1px solid ${C.lineStrong}` }}
              role="group"
              aria-label="Zoom"
            >
              <ZoomButton label="Zoom in" onClick={() => zoomBy(1.3)}>
                <Plus className="size-4" weight="bold" aria-hidden />
              </ZoomButton>
              <ZoomButton label="Zoom out" onClick={() => zoomBy(1 / 1.3)}>
                <Minus className="size-4" weight="bold" aria-hidden />
              </ZoomButton>
              <ZoomButton label="Fit the graph to the view" onClick={() => fitTo(visible.nodes)}>
                <FrameCorners className="size-4" weight="bold" aria-hidden />
              </ZoomButton>
            </div>
            <ul
              aria-label="Key"
              className={`pointer-events-none absolute left-4 top-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] ${pathFrom || focus || notice ? "hidden" : ""}`}
              style={{ color: C.muted }}
            >
              <li className="flex items-center gap-1.5">
                <NodeGlyph kind="seed" /> Seed paper
              </li>
              <li className="flex items-center gap-1.5">
                <NodeGlyph kind="member" /> In this workspace
              </li>
              {connectedOnly > 0 && (
                <li className="flex items-center gap-1.5">
                  <NodeGlyph kind="connected" /> Connected, not added
                </li>
              )}
            </ul>
          </>
        )}

        {model && panelOpen && (activeSelection || path) && (
          <div className={isDesktop ? "absolute bottom-4 right-4 top-4 w-[412px]" : "absolute inset-x-2 bottom-2 max-h-[56%]"} style={{ display: "flex" }}>
            <div className="flex min-h-0 w-full flex-col">
              <GraphPanel
                model={model}
                selection={activeSelection ?? { kind: "node", id: path!.to }}
                workspaceId={id}
                seed={seed}
                trailById={trailById}
                path={path}
                pathFrom={pathFrom}
                focusedOn={focus?.on ?? null}
                hiddenNeighbours={hiddenNeighbours}
                onClose={() => {
                  setSelection(null);
                  setPath(null);
                  setPathFrom(null);
                  stageEl?.focus();
                }}
                onSelect={select}
                onFocus={focusOn}
                onExpand={expand}
                onTracePath={tracePath}
                onDecide={decide}
                onAdd={addPaper}
              />
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}

/** The page frame: header over a full-height stage. A light vignette instead
 * of the dense scrim other pages use, so the background can become the graph. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden selection:bg-[rgba(93,240,168,0.28)] selection:text-white" style={{ color: C.ink }}>
      <div
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "radial-gradient(130% 95% at 50% 55%, rgba(4,6,15,.08) 0%, rgba(4,6,15,.42) 62%, rgba(4,6,15,.8) 100%)" }}
      />
      <CinematicHeader />
      <main id="main" className="relative flex min-h-0 flex-1 flex-col">
        {children}
      </main>
    </div>
  );
}

function ZoomButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`inline-flex size-11 items-center justify-center transition-colors hover:bg-white/10 active:scale-[0.96] ${focusRing}`}
      style={{ color: C.ink }}
    >
      {children}
    </button>
  );
}

function BannerButton({ onClick, label, children }: { onClick: () => void; label?: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`inline-flex min-h-11 items-center rounded-full px-2 font-semibold underline underline-offset-4 hover:text-white sm:min-h-8 ${focusRing}`}
      style={{ color: C.mint }}
    >
      {children}
    </button>
  );
}

/** Find a paper by title, author, venue or year; picking one selects it and
 * flies the camera there. A standard combobox: arrows move, Enter picks. */
function SearchBox({ model, onChoose }: { model: ReturnType<typeof buildModel>; onChoose: (n: GNode) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const results = searchNodes(model, query);

  function choose(n: GNode) {
    onChoose(n);
    setQuery("");
    setOpen(false);
  }

  return (
    <div className="relative lg:w-80 lg:shrink-0">
      <label className="relative block">
        <span className="sr-only">Find a paper in the graph</span>
        <MagnifyingGlass className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2" style={{ color: C.muted }} aria-hidden />
        <input
          type="search"
          role="combobox"
          aria-expanded={open && query.trim() !== ""}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              e.preventDefault();
              choose(results[active]);
            } else if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Find a paper by title, author or year"
          className="h-11 w-full rounded-full pl-9 pr-4 text-sm caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] focus-visible:border-[#5df0a8] sm:h-10"
          style={{ background: "rgba(10,15,32,.7)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
        />
      </label>
      {open && query.trim() !== "" && (
        <div
          className="absolute left-0 right-0 top-full z-20 mt-1.5 overflow-hidden rounded-2xl backdrop-blur-md"
          style={{ background: "rgba(10,15,32,.96)", border: `1px solid ${C.lineStrong}` }}
        >
          {results.length === 0 ? (
            <p className="px-4 py-3 text-sm" style={{ color: C.muted }}>
              No paper in this graph matches.
            </p>
          ) : (
            <ul id={listId} role="listbox" aria-label="Matching papers" className="max-h-72 overflow-y-auto py-1">
              {results.map((n, i) => (
                <li
                  key={n.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(n);
                  }}
                  onMouseEnter={() => setActive(i)}
                  className="flex cursor-pointer items-start gap-2.5 px-4 py-2.5 text-sm"
                  style={{ background: i === active ? "rgba(93,240,168,.1)" : undefined }}
                >
                  <span className="mt-[4px]">
                    <NodeGlyph kind={n.kind} size={11} />
                  </span>
                  <span className="min-w-0">
                    <span className="block leading-snug">{n.title}</span>
                    <span className="block text-[12px] tabular-nums" style={{ color: C.muted }}>
                      {[n.year, KIND_LABEL[n.kind]].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
