"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { GraphEdgeRecord, GraphNode, GraphNodeType } from "@/lib/api/types";
import Link from "next/link";
import { ArrowSquareOut } from "@phosphor-icons/react/dist/ssr";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge, ConfidenceBadge } from "@/components/ui/Badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";

const NODE_TYPES: GraphNodeType[] = ["PAPER", "METHOD", "DATASET", "TOPIC", "RESEARCH_QUESTION", "CLAIM", "GAP", "DIRECTION"];
const WIDTH = 720;
const HEIGHT = 480;

interface Point {
  x: number;
  y: number;
}

/** A small, dependency-free force-directed layout (Fruchterman-Reingold
 * style: uniform repulsion between every pair of nodes, spring attraction
 * along real edges, positions clamped to the canvas) -- real spatial
 * meaning (connected nodes end up near each other, everything else spreads
 * out to stay legible), not a fixed decorative arrangement. Nodes seed on
 * a circle so the simulation starts from a stable, non-overlapping state. */
function useForceLayout(nodes: GraphNode[], edges: GraphEdgeRecord[]): Map<string, Point> {
  return useMemo(() => {
    const n = nodes.length;
    const positions = new Map<string, Point>();
    if (n === 0) return positions;

    const cx = WIDTH / 2;
    const cy = HEIGHT / 2;
    const r0 = Math.min(WIDTH, HEIGHT) * 0.35;
    const idIndex = new Map(nodes.map((node, i) => [node.id, i]));
    const pos = nodes.map((_, i) => ({
      x: cx + r0 * Math.cos((i / n) * Math.PI * 2),
      y: cy + r0 * Math.sin((i / n) * Math.PI * 2),
    }));
    const edgePairs = edges
      .map((e): [number, number] | null => {
        const a = idIndex.get(e.src);
        const b = idIndex.get(e.dst);
        return a != null && b != null && a !== b ? [a, b] : null;
      })
      .filter((pair): pair is [number, number] => pair !== null);

    const REPULSION = 3200;
    const SPRING = 0.02;
    const IDEAL_LENGTH = Math.min(WIDTH, HEIGHT) / Math.max(4, Math.sqrt(n));
    const iterations = n > 80 ? 50 : 150;

    for (let iter = 0; iter < iterations; iter++) {
      const fx = new Array(n).fill(0);
      const fy = new Array(n).fill(0);
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let dx = pos[i].x - pos[j].x;
          let dy = pos[i].y - pos[j].y;
          const distSq = Math.max(dx * dx + dy * dy, 1);
          const dist = Math.sqrt(distSq);
          const force = REPULSION / distSq;
          dx /= dist;
          dy /= dist;
          fx[i] += dx * force;
          fy[i] += dy * force;
          fx[j] -= dx * force;
          fy[j] -= dy * force;
        }
      }
      for (const [a, b] of edgePairs) {
        const dx = pos[b].x - pos[a].x;
        const dy = pos[b].y - pos[a].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const displacement = (dist - IDEAL_LENGTH) * SPRING;
        const ux = dx / dist;
        const uy = dy / dist;
        fx[a] += ux * displacement;
        fy[a] += uy * displacement;
        fx[b] -= ux * displacement;
        fy[b] -= uy * displacement;
      }
      for (let i = 0; i < n; i++) {
        pos[i].x = Math.max(28, Math.min(WIDTH - 28, pos[i].x + Math.max(-8, Math.min(8, fx[i]))));
        pos[i].y = Math.max(28, Math.min(HEIGHT - 28, pos[i].y + Math.max(-8, Math.min(8, fy[i]))));
      }
    }

    nodes.forEach((node, i) => positions.set(node.id, pos[i]));
    return positions;
  }, [nodes, edges]);
}

export default function WorkspaceGraphPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: graph, error, isLoading, mutate } = useSWR(["graph", workspaceId], () => workspaces.graph(workspaceId));
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const positions = useForceLayout(graph?.nodes ?? [], graph?.edges ?? []);
  const labelById = useMemo(() => {
    const map = new Map<string, string>();
    graph?.nodes.forEach((n) => map.set(n.id, n.label));
    return map;
  }, [graph]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error) return <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />;
  if (!graph) return null;

  if (graph.node_count === 0) {
    return <EmptyState title="No graph yet" description="The research graph builds automatically from this workspace's papers and trail edges." />;
  }

  const selectedNode = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const connectedEdges = selectedId ? graph.edges.filter((e) => e.src === selectedId || e.dst === selectedId) : [];

  return (
    <div className="space-y-4">
      <p className="border-b border-border pb-3 font-mono text-xs text-ink-subtle">
        {graph.node_count} nodes · {graph.edge_count} edges · rebuilt {new Date(graph.built_at).toLocaleString()}
      </p>

      <div className="lg:grid lg:grid-cols-[1fr_16rem] lg:gap-6">
        <div className="overflow-x-auto border border-border bg-surface-raised p-2">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={`Research graph: ${graph.node_count} nodes, ${graph.edge_count} edges`}
            className="min-w-[480px]"
          >
            <g>
              {graph.edges.map((edge, i) => {
                const a = positions.get(edge.src);
                const b = positions.get(edge.dst);
                if (!a || !b) return null;
                const connected = selectedId != null && (edge.src === selectedId || edge.dst === selectedId);
                const dimmed = selectedId != null && !connected;
                return (
                  <line
                    key={i}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    className={
                      connected
                        ? "stroke-accent"
                        : edge.type === "CONTRADICTS"
                          ? "stroke-danger"
                          : "stroke-border-strong"
                    }
                    strokeWidth={connected ? 2 : 1}
                    strokeDasharray={edge.type === "CONTRADICTS" ? "4 2" : undefined}
                    opacity={dimmed ? 0.15 : edge.type === "CONTRADICTS" ? 0.8 : 0.5}
                  />
                );
              })}
            </g>
            <g>
              {graph.nodes.map((node) => {
                const p = positions.get(node.id);
                if (!p) return null;
                const isPaper = node.type === "PAPER";
                const isSelected = node.id === selectedId;
                const dimmed = selectedId != null && !isSelected && !connectedEdges.some((e) => e.src === node.id || e.dst === node.id);
                const r = isPaper ? 10 : 6;
                return (
                  <g
                    key={node.id}
                    tabIndex={0}
                    role="button"
                    aria-label={`${node.type.toLowerCase().replace(/_/g, " ")}: ${node.label}`}
                    aria-pressed={isSelected}
                    onClick={() => setSelectedId((prev) => (prev === node.id ? null : node.id))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId((prev) => (prev === node.id ? null : node.id));
                      }
                    }}
                    className="cursor-pointer outline-none"
                    opacity={dimmed ? 0.3 : 1}
                  >
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={isSelected ? r + 2 : r}
                      className={isPaper ? "fill-accent-wash" : "fill-surface-raised"}
                      stroke="currentColor"
                      strokeWidth={isSelected ? 2.5 : 1.5}
                      style={{ color: isSelected ? "var(--accent-strong)" : isPaper ? "var(--accent)" : "var(--border-strong)" }}
                    />
                    {(isPaper || isSelected) && (
                      <text x={p.x} y={p.y - r - 4} textAnchor="middle" className="fill-ink-muted text-[9px]">
                        {node.label.length > 28 ? `${node.label.slice(0, 27)}…` : node.label}
                      </text>
                    )}
                    <title>{node.label}</title>
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        <div className="mt-4 lg:mt-0">
          <p className="mb-2 font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            {selectedNode ? "Selected node" : "Legend"}
          </p>
          {selectedNode ? (
            <div className="space-y-2 border-t border-border-strong pt-2">
              <p className="text-xs text-ink-subtle">{selectedNode.type.replace(/_/g, " ").toLowerCase()}</p>
              <p className="text-sm font-medium text-ink">{selectedNode.label}</p>
              {selectedNode.type === "PAPER" && (
                <Link href={`/papers/${selectedNode.id}`} className="inline-flex items-center gap-1 text-xs text-accent-strong hover:underline">
                  View paper <ArrowSquareOut className="size-3" aria-hidden />
                </Link>
              )}
              <p className="text-xs text-ink-subtle">{connectedEdges.length} connection{connectedEdges.length === 1 ? "" : "s"}</p>
              <ul className="space-y-2">
                {connectedEdges.map((e, i) => {
                  const otherId = e.src === selectedNode.id ? e.dst : e.src;
                  return (
                    <li key={i} className="text-xs text-ink-muted">
                      <p>
                        {e.type.toLowerCase().replace(/_/g, " ")} · {labelById.get(otherId) ?? otherId}
                      </p>
                      {e.evidence.length > 0 && (
                        <details className="mt-0.5">
                          <summary className="cursor-pointer list-none text-ink-subtle hover:text-ink-muted">
                            {e.evidence.length} evidence span{e.evidence.length === 1 ? "" : "s"}
                          </summary>
                          <ul className="mt-1 space-y-1">
                            {e.evidence.map((span, j) => (
                              <li key={j} className="rule-t bg-surface-sunken px-2 py-1 italic text-ink-subtle">
                                &ldquo;{span.quote}&rdquo;
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <div className="space-y-1.5 border-t border-border-strong pt-2 text-xs text-ink-muted">
              <p>Click or Tab to a node to see its connections.</p>
              <p className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 rounded-full border border-accent bg-accent-wash" /> Paper
              </p>
              <p className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 rounded-full border border-border-strong bg-surface-raised" /> Method / dataset / topic / claim / gap / direction
              </p>
              <p className="flex items-center gap-1.5">
                <span className="inline-block h-0.5 w-3 bg-danger" /> Contradicts
              </p>
            </div>
          )}
        </div>
      </div>

      <details>
        <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">
          View as a list instead (nodes grouped by type, all edges)
        </summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <h3 className="text-sm font-semibold text-ink">Nodes</h3>
            </CardHeader>
            <CardBody className="space-y-4">
              {NODE_TYPES.map((type) => {
                const nodes = graph.nodes.filter((n) => n.type === type);
                if (nodes.length === 0) return null;
                return (
                  <div key={type}>
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
                      {type.replace(/_/g, " ")} ({nodes.length})
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {nodes.map((n) => (
                        <Badge key={n.id} tone={type === "PAPER" ? "accent" : "neutral"}>
                          {n.label}
                        </Badge>
                      ))}
                    </div>
                  </div>
                );
              })}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-sm font-semibold text-ink">Edges</h3>
            </CardHeader>
            <ul className="max-h-[32rem] divide-y divide-border overflow-y-auto">
              {graph.edges.map((edge, i) => (
                <li key={i} className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm">
                  <span className="min-w-0 truncate text-ink">
                    {labelById.get(edge.src) ?? edge.src}
                    <span className="mx-1.5 text-ink-subtle">{edge.type.toLowerCase().replace(/_/g, " ")}</span>
                    {labelById.get(edge.dst) ?? edge.dst}
                  </span>
                  <ConfidenceBadge confidence={edge.confidence} />
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </details>
    </div>
  );
}
