"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import type { Camera } from "@/lib/graph/camera";
import { nodeZoom, zoomAt } from "@/lib/graph/camera";
import { placeLabels } from "@/lib/graph/labels";
import { NODE_RADIUS, type Layout } from "@/lib/graph/layout";
import { EDGE_STYLE, type GEdge, type GNode, type GraphModel, type Visible } from "@/lib/graph/model";
import { C } from "../ui";
import styles from "./graph.module.css";

export type Selection = { kind: "node"; id: string } | { kind: "edge"; key: string };
export type Phase = "hidden" | "intro" | "settled";

export interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
}

export interface IntroTimeline {
  node: Map<string, number>;
  edge: Map<string, number>;
  /** When labels and the axis fade in, in seconds. */
  chrome: number;
}

interface GraphCanvasProps {
  model: GraphModel;
  layout: Layout;
  visible: Visible;
  cam: Camera;
  size: { w: number; h: number };
  phase: Phase;
  intro: IntroTimeline;
  selection: Selection | null;
  hover: Selection | null;
  highlight: Highlight | null;
  picking: boolean;
  /** Nodes are gliding to a new layout; labels wait for them. */
  relayout: boolean;
  /** Stage edges covered by the details panel: no label is placed under it. */
  covered: { right: number; bottom: number };
  onCamera: (update: (cam: Camera) => Camera) => void;
  onSelect: (selection: Selection | null) => void;
  onHover: (update: (hover: Selection | null) => Selection | null) => void;
  onNodeFocus: (id: string) => void;
  describeNode: (node: GNode) => string;
}

const KIND_LABEL = { seed: "seed paper", member: "in this workspace", connected: "connected, not in this workspace" } as const;
const INK_HALO = "#04060f";

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

let measureCtx: CanvasRenderingContext2D | null = null;

/** A label's rendered width, measured in the page's own font. */
function measureLabel(text: string, bold: boolean): number {
  if (typeof document === "undefined") return text.length * 6.7;
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * 6.7;
  measureCtx.font = `${bold ? 700 : 500} 12.5px ${getComputedStyle(document.body).fontFamily}`;
  return Math.ceil(measureCtx.measureText(text).width) + 2;
}

interface EdgeGeometry {
  d: string;
  reversed: string;
  mid: { x: number; y: number };
}

/** A gently bowed curve between the two node rims (the background's
 * backbone links bow the same way), trimmed so arrowheads meet the rim. */
function edgeGeometry(a: { x: number; y: number }, b: { x: number; y: number }, ra: number, rb: number, key: string): EdgeGeometry {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const bend = (((hash(key) % 1000) / 1000 - 0.5) * 0.28 + (hash(key) % 2 ? 0.06 : -0.06)) * len;
  const cx = (a.x + b.x) / 2 - (dy / len) * bend;
  const cy = (a.y + b.y) / 2 + (dx / len) * bend;
  const trim = (p: { x: number; y: number }, r: number) => {
    const ux = cx - p.x;
    const uy = cy - p.y;
    const ul = Math.hypot(ux, uy) || 1;
    return { x: p.x + (ux / ul) * r, y: p.y + (uy / ul) * r };
  };
  const s = trim(a, ra);
  const e = trim(b, rb);
  const f = (v: number) => v.toFixed(1);
  return {
    d: `M${f(s.x)} ${f(s.y)}Q${f(cx)} ${f(cy)} ${f(e.x)} ${f(e.y)}`,
    reversed: `M${f(e.x)} ${f(e.y)}Q${f(cx)} ${f(cy)} ${f(s.x)} ${f(s.y)}`,
    mid: { x: 0.25 * s.x + 0.5 * cx + 0.25 * e.x, y: 0.25 * s.y + 0.5 * cy + 0.25 * e.y },
  };
}

const delayStyle = (seconds: number | undefined): CSSProperties => ({ "--delay": `${(seconds ?? 0).toFixed(3)}s` }) as CSSProperties;

export function GraphCanvas({
  model,
  layout,
  visible,
  cam,
  size,
  phase,
  intro,
  selection,
  hover,
  highlight,
  picking,
  relayout,
  covered,
  onCamera,
  onSelect,
  onHover,
  onNodeFocus,
  describeNode,
}: GraphCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ startX: number; startY: number; moved: boolean; pinch: number | null } | null>(null);
  const suppressClick = useRef(false);
  const [grabbing, setGrabbing] = useState(false);

  // wheel zoom needs a non-passive listener to keep the page from scrolling
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? rect.height : 1;
      const factor = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0016));
      onCamera((c) => zoomAt(c, factor, e.clientX - rect.left, e.clientY - rect.top));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onCamera]);

  function localPoint(e: { clientX: number; clientY: number }) {
    const rect = svgRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function onPointerDown(e: PointerEvent<SVGSVGElement>) {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    pointers.current.set(e.pointerId, localPoint(e));
    suppressClick.current = false;
    if (pointers.current.size === 1) {
      gesture.current = { startX: e.clientX, startY: e.clientY, moved: false, pinch: null };
    } else if (pointers.current.size === 2) {
      const [p, q] = [...pointers.current.values()];
      gesture.current = { startX: e.clientX, startY: e.clientY, moved: true, pinch: Math.hypot(p.x - q.x, p.y - q.y) };
      suppressClick.current = true;
    }
  }

  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    const g = gesture.current;
    const prev = pointers.current.get(e.pointerId);
    if (!g || !prev) return;
    const now = localPoint(e);
    pointers.current.set(e.pointerId, now);
    if (pointers.current.size >= 2 && g.pinch != null) {
      const [p, q] = [...pointers.current.values()];
      const dist = Math.hypot(p.x - q.x, p.y - q.y);
      const mid = { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 };
      const factor = dist / (g.pinch || dist);
      g.pinch = dist;
      // this pointer's share of the midpoint's travel pans; the spread zooms
      const pan = { x: (now.x - prev.x) / 2, y: (now.y - prev.y) / 2 };
      onCamera((c) => {
        const z = zoomAt(c, factor, mid.x, mid.y);
        return { ...z, x: z.x + pan.x, y: z.y + pan.y };
      });
      return;
    }
    if (!g.moved && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) < 4) return;
    if (!g.moved) {
      g.moved = true;
      suppressClick.current = true;
      svgRef.current?.setPointerCapture(e.pointerId);
      setGrabbing(true);
    }
    const dx = now.x - prev.x;
    const dy = now.y - prev.y;
    onCamera((c) => ({ ...c, x: c.x + dx, y: c.y + dy }));
  }

  function endPointer(e: PointerEvent<SVGSVGElement>) {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size === 0) {
      gesture.current = null;
      setGrabbing(false);
    } else if (gesture.current) {
      gesture.current.pinch = null; // one finger left: carry on panning
    }
  }

  function click(next: Selection | null) {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onSelect(next);
  }

  function nodeKey(e: KeyboardEvent<SVGGElement>, id: string) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect({ kind: "node", id });
    }
  }

  const k = cam.k;
  const zs = nodeZoom(k);
  const inIntro = phase === "intro";
  const radiusOf = (n: GNode) => (NODE_RADIUS[n.kind] * zs) / k; // graph units

  // nodes in reading order: left to right through time, so Tab follows the timeline
  const nodes = useMemo(
    () =>
      model.nodes
        .filter((n) => visible.nodes.has(n.id))
        .sort((a, b) => layout.pos.get(a.id)!.x - layout.pos.get(b.id)!.x || layout.pos.get(a.id)!.y - layout.pos.get(b.id)!.y),
    [model, visible, layout],
  );
  const edges = model.edges.filter((e) => visible.edges.has(e.key));
  const hoverNode = hover?.kind === "node" ? hover.id : null;
  const hoverEdge = hover?.kind === "edge" ? hover.key : null;
  const selectedNode = selection?.kind === "node" ? selection.id : null;
  const selectedEdge = selection?.kind === "edge" ? selection.key : null;

  const screen = (id: string) => {
    const p = layout.pos.get(id)!;
    return { x: p.x * k + cam.x, y: p.y * k + cam.y };
  };

  // labels live in screen space so text stays one size at every zoom
  const labels = placeLabels(
    nodes.map((n) => {
      const s = screen(n.id);
      const emphasised = n.id === selectedNode || highlight?.nodes.has(n.id);
      return {
        id: n.id,
        x: s.x,
        y: s.y,
        r: NODE_RADIUS[n.kind] * zs,
        text: n.title,
        priority: (n.kind === "seed" ? 60 : n.kind === "member" ? 30 : 10) + (emphasised ? 100 : 0),
        // the seed and the paper in focus read in full; members before papers only connected
        maxChars: n.kind === "seed" || n.id === selectedNode ? 56 : n.kind === "member" ? (k > 1.15 ? 48 : 38) : k > 1.15 ? 40 : 28,
      };
    }),
    nodes.map((n) => ({ ...screen(n.id), r: NODE_RADIUS[n.kind] * zs })),
    { width: size.w - covered.right, height: size.h - covered.bottom },
    (text, id) => measureLabel(text, id === selectedNode || model.byId.get(id)?.kind === "seed"),
  );
  const labelled = new Set(labels.map((l) => l.id));
  const hoverLabel =
    hoverNode && !labelled.has(hoverNode) && model.byId.get(hoverNode)
      ? placeLabels(
          [{ id: hoverNode, ...screen(hoverNode), r: NODE_RADIUS[model.byId.get(hoverNode)!.kind] * zs, text: model.byId.get(hoverNode)!.title, priority: 1, maxChars: 60 }],
          [],
          { width: size.w - covered.right, height: size.h - covered.bottom },
          (text) => measureLabel(text, false),
        )[0]
      : null;

  const pulses = new Set(
    edges
      .filter((e) => e.state === "accepted")
      .sort((a, b) => hash(a.key) - hash(b.key))
      .slice(0, 24)
      .map((e) => e.key),
  );

  // the selected paper never fades, whatever else is being pointed at
  const dimNode = (id: string) => highlight != null && !highlight.nodes.has(id) && id !== selectedNode;
  const dimEdge = (key: string) => highlight != null && !highlight.edges.has(key);

  function edgeView(e: GEdge) {
    const style = EDGE_STYLE[e.type];
    const a = model.byId.get(e.src)!;
    const b = model.byId.get(e.dst)!;
    const arrowGap = 3 / k;
    const geo = edgeGeometry(
      layout.pos.get(e.src)!,
      layout.pos.get(e.dst)!,
      radiusOf(a) + (style.arrow === "src" ? arrowGap : 1 / k),
      radiusOf(b) + (style.arrow === "dst" ? arrowGap : 1 / k),
      e.key,
    );
    const lit = highlight?.edges.has(e.key) || e.key === selectedEdge || e.key === hoverEdge;
    const width = (style.width * (lit ? 1.55 : e.state === "pending" ? 0.85 : 1)) / k;
    // at rest the connections recede so their types read; pointing at a paper lights its own
    const opacity = dimEdge(e.key) ? 0.08 : lit ? 1 : e.state === "pending" ? 0.26 : 0.6;
    const dash = style.dash
      ?.split(" ")
      .map((v) => (Number(v) / k).toFixed(2))
      .join(" ");
    const delay = intro.edge.get(e.key);
    const pulseCycle = 7 + (hash(e.key) % 500) / 100;
    return (
      <g key={e.key} className={styles.dimmable} style={{ opacity }}>
        {inIntro && (
          <path
            d={geo.d}
            pathLength={1}
            fill="none"
            stroke={style.color}
            strokeWidth={(style.width * 1.4) / k}
            strokeLinecap="round"
            className={styles.draw}
            style={delayStyle(delay)}
          />
        )}
        <path
          d={geo.d}
          fill="none"
          stroke={style.color}
          strokeWidth={width}
          strokeDasharray={dash}
          strokeLinecap={style.dash?.startsWith("1.5") ? "round" : "butt"}
          markerEnd={style.arrow === "dst" ? `url(#rn-arrow-${e.type})` : undefined}
          markerStart={style.arrow === "src" ? `url(#rn-arrow-${e.type})` : undefined}
          className={inIntro ? styles.styledIn : undefined}
          style={inIntro ? delayStyle(delay) : undefined}
        />
        {phase === "settled" && pulses.has(e.key) && !dimEdge(e.key) && (
          <path
            d={style.arrow === "src" ? geo.reversed : geo.d}
            pathLength={1}
            fill="none"
            stroke={style.color}
            strokeWidth={3.2 / k}
            strokeLinecap="round"
            className={styles.pulse}
            style={{ "--cycle": `${pulseCycle.toFixed(2)}s`, "--delay": `${((hash(e.key) % 900) / 100).toFixed(2)}s` } as CSSProperties}
            aria-hidden
          />
        )}
        {/* a wide, invisible stroke makes a thin line easy to point at */}
        <path
          d={geo.d}
          fill="none"
          stroke="transparent"
          strokeWidth={16 / k}
          data-edge={e.key}
          className="cursor-pointer"
          onPointerEnter={(ev) => ev.pointerType === "mouse" && onHover(() => ({ kind: "edge", key: e.key }))}
          onPointerLeave={() => onHover((h) => (h?.kind === "edge" && h.key === e.key ? null : h))}
          onClick={() => click({ kind: "edge", key: e.key })}
        />
      </g>
    );
  }

  const axis = layout.timeline;
  const axisY = size.h - 30;
  // year ticks that fit on screen without crowding: the seed's year first,
  // then the ends of the range, then whatever else has room
  const ticks: { year: number; x: number }[] = [];
  if (axis) {
    const onScreen = axis.ticks.map((year) => ({ year, x: axis.yearX(year) * k + cam.x })).filter((t) => t.x >= 22 && t.x <= size.w - 22);
    const rank = (t: { year: number }) => (t.year === axis.seedYear ? 0 : t === onScreen[0] || t === onScreen.at(-1) ? 1 : 2);
    for (const t of [...onScreen].sort((a, b) => rank(a) - rank(b) || a.x - b.x)) {
      if (ticks.every((p) => Math.abs(p.x - t.x) >= 38)) ticks.push(t);
    }
    ticks.sort((a, b) => a.x - b.x);
  }

  return (
    <svg
      ref={svgRef}
      width={size.w}
      height={size.h}
      className={`absolute inset-0 block touch-none select-none ${picking ? "cursor-crosshair" : grabbing ? styles.grabbing : styles.grab}`}
      style={{ visibility: phase === "hidden" ? "hidden" : "visible" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endPointer}
      onPointerCancel={endPointer}
      role="group"
      aria-label={`Research graph: ${nodes.length} papers, ${edges.length} connections. Tab through the papers, or drag to pan and scroll to zoom.`}
    >
      <defs>
        <radialGradient id="rn-halo">
          <stop offset="0" stopColor="#5df0a8" stopOpacity="0.5" />
          <stop offset="0.35" stopColor="#22d3ee" stopOpacity="0.16" />
          <stop offset="1" stopColor="#22d3ee" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="rn-seed-core" cx="0.38" cy="0.34" r="0.75">
          <stop offset="0" stopColor="#e9fff4" />
          <stop offset="0.45" stopColor="#5df0a8" />
          <stop offset="1" stopColor="#1fae72" />
        </radialGradient>
        {Object.entries(EDGE_STYLE)
          .filter(([, s]) => s.arrow)
          .map(([type, s]) => (
            <marker
              key={type}
              id={`rn-arrow-${type}`}
              viewBox="0 0 10 10"
              refX="8.5"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
              markerUnits="strokeWidth"
            >
              <path d="M0.5 1L9 5L0.5 9z" fill={s.color} />
            </marker>
          ))}
      </defs>

      {/* empty space: clicking it clears the selection */}
      <rect width={size.w} height={size.h} fill="transparent" onClick={() => click(null)} />

      <g transform={`translate(${cam.x.toFixed(2)} ${cam.y.toFixed(2)}) scale(${k.toFixed(4)})`}>
        <g>{edges.map(edgeView)}</g>
        <g>
          {nodes.map((n) => {
            const p = layout.pos.get(n.id)!;
            const R = NODE_RADIUS[n.kind];
            const selected = n.id === selectedNode;
            const hovered = n.id === hoverNode;
            const delay = intro.node.get(n.id);
            return (
              <g
                key={n.id}
                className={styles.node}
                style={{ transform: `translate(${p.x}px, ${p.y}px)` }}
              >
                <g transform={`scale(${(zs / k).toFixed(4)})`}>
                  <g
                    className={`${styles.nodeHit} ${styles.dimmable} cursor-pointer`}
                    style={{ opacity: dimNode(n.id) ? 0.22 : 1 }}
                    tabIndex={0}
                    role="button"
                    aria-pressed={selected}
                    aria-label={describeNode(n)}
                    data-node={n.id}
                    data-kind={n.kind}
                    onClick={() => click({ kind: "node", id: n.id })}
                    onKeyDown={(e) => nodeKey(e, n.id)}
                    onFocus={() => onNodeFocus(n.id)}
                    onPointerEnter={(e) => e.pointerType === "mouse" && onHover(() => ({ kind: "node", id: n.id }))}
                    onPointerLeave={() => onHover((h) => (h?.kind === "node" && h.id === n.id ? null : h))}
                  >
                    <g className={`${styles.nodeBody} ${inIntro ? styles.emerge : ""}`} style={inIntro ? delayStyle(delay) : undefined}>
                      {n.kind === "seed" && <circle r={R * 3.1} fill="url(#rn-halo)" className={styles.breathe} />}
                      {n.kind === "member" && <circle r={R * 2.4} fill="url(#rn-halo)" opacity={0.75} />}
                      <circle r={Math.max(R + 12, 22 / zs)} fill="transparent" />
                      <circle className={styles.focusRing} r={R + 9} fill="none" stroke={C.mint} strokeWidth={2} />
                      {(selected || hovered) && (
                        <circle r={R + 5.5} fill="none" stroke="#ffffff" strokeOpacity={selected ? 0.95 : 0.5} strokeWidth={selected ? 1.6 : 1} />
                      )}
                      {n.kind === "seed" ? (
                        <>
                          <circle r={R + 4} fill="none" stroke={C.mint} strokeOpacity={0.45} strokeWidth={1} />
                          <circle r={R} fill="url(#rn-seed-core)" stroke={INK_HALO} strokeOpacity={0.5} strokeWidth={1.5} />
                        </>
                      ) : n.kind === "member" ? (
                        <circle r={R} fill={C.mint} stroke={INK_HALO} strokeOpacity={0.55} strokeWidth={1.5} />
                      ) : (
                        <circle r={R} fill="#0b1226" stroke="#cfe0ff" strokeOpacity={0.85} strokeWidth={1.6} />
                      )}
                    </g>
                    <title>{`${n.title} (${KIND_LABEL[n.kind]})`}</title>
                  </g>
                </g>
              </g>
            );
          })}
        </g>
      </g>

      {/* screen-space chrome: the time axis and the labels */}
      {axis && (
        <g
          className={inIntro ? styles.fadeIn : undefined}
          style={inIntro ? { animationDelay: `${intro.chrome}s` } : undefined}
          aria-hidden
          pointerEvents="none"
        >
          <line x1={16} x2={size.w - 16} y1={axisY} y2={axisY} stroke={C.lineStrong} />
          <text x={16} y={axisY - 8} fontSize={11} fill={C.muted2}>
            Older
          </text>
          <text x={size.w - 16} y={axisY - 8} fontSize={11} fill={C.muted2} textAnchor="end">
            Newer
          </text>
          {ticks.map(({ year, x }) => {
            const isSeed = year === axis.seedYear;
            return (
              <g key={year}>
                <line x1={x} x2={x} y1={axisY - (isSeed ? 7 : 4)} y2={axisY} stroke={isSeed ? C.mint : C.lineStrong} strokeWidth={isSeed ? 1.5 : 1} />
                <text x={x} y={axisY + 15} fontSize={11} textAnchor="middle" fill={isSeed ? C.mint : C.muted} className="font-mono tabular-nums">
                  {year}
                </text>
              </g>
            );
          })}
        </g>
      )}
      <g
        className={`${styles.labels} ${inIntro ? styles.fadeIn : ""}`}
        style={{ opacity: relayout ? 0 : 1, ...(inIntro ? { animationDelay: `${intro.chrome}s` } : {}) }}
        aria-hidden
        pointerEvents="none"
      >
        {[...labels, ...(hoverLabel ? [hoverLabel] : [])].map((l) => {
          const n = model.byId.get(l.id)!;
          const strong = n.kind === "seed" || l.id === selectedNode;
          return (
            <text
              key={l.id}
              x={l.x}
              y={l.y}
              dy="0.35em"
              textAnchor={l.anchor}
              fontSize={12.5}
              fontWeight={strong ? 700 : 500}
              fill={n.kind === "connected" && !strong ? C.muted : C.ink}
              stroke={INK_HALO}
              strokeWidth={4}
              strokeLinejoin="round"
              paintOrder="stroke"
              opacity={dimNode(l.id) ? 0.3 : 1}
            >
              {l.text}
            </text>
          );
        })}
      </g>
    </svg>
  );
}
