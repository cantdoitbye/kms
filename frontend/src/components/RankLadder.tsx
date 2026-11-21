"use client";

import { useState } from "react";
import { ChunkResult, docTitle, Mode, pageLabel } from "@/lib/api";

/**
 * Slope chart of how each returned passage moved through the retrieval stages:
 * its rank from vector search (circle) and keyword search (square) merge into a
 * fused RRF rank, which the cross-encoder then reorders into the final rank.
 */
export function RankLadder({
  results,
  mode,
  citedRefs,
  activeRef,
  onPick,
}: {
  results: ChunkResult[];
  mode: Mode;
  citedRefs: Set<number>;
  activeRef: number | null;
  onPick: (ref: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (mode === "vector" || mode === "keyword") {
    return (
      <p className="text-sm text-ink-soft">
        This answer used a single retriever, so there&apos;s nothing to merge. Switch the search mode to Hybrid or
        Hybrid + rerank and ask again to see how the rankings combine.
      </p>
    );
  }

  const rerank = mode === "hybrid_rerank";
  const ranksOf = (c: ChunkResult) => [c.scores.vector_rank, c.scores.keyword_rank, c.scores.rrf_rank, c.scores.rerank_rank];
  const maxRank = Math.min(
    20,
    Math.max(results.length, ...results.flatMap((c) => ranksOf(c).filter((r): r is number => r != null))),
  );

  const W = 360;
  const rowH = 15;
  const top = 26;
  const missY = top + maxRank * rowH + 14;
  const H = missY + 14;
  const xIn = 52;
  const xFused = rerank ? 128 : 200;
  const xFinal = 200;
  const y = (r: number | undefined) => (r == null || r > maxRank ? missY : top + (r - 0.5) * rowH);

  const active = hover ?? activeRef;

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="How retrieval stages ranked each passage">
        {/* column headings */}
        <g className="fill-ink-soft text-[10px]" style={{ fontSize: 10 }}>
          <text x={xIn} y={12} textAnchor="middle">Retrieved</text>
          <text x={xFused} y={12} textAnchor="middle">Fused</text>
          {rerank && <text x={xFinal} y={12} textAnchor="middle">Reranked</text>}
        </g>
        {/* rank guides */}
        {Array.from({ length: maxRank }, (_, i) => i + 1).map((r) => (
          <g key={r}>
            <line x1={xIn - 26} x2={xFinal} y1={y(r)} y2={y(r)} stroke="var(--color-rule)" strokeWidth={0.5} strokeDasharray={r % 5 === 0 ? "" : "1 3"} />
            {(r === 1 || r % 5 === 0) && (
              <text x={xIn - 30} y={y(r) + 3} textAnchor="end" style={{ fontSize: 9 }} className="fill-ink-faint">
                {r}
              </text>
            )}
          </g>
        ))}
        <text x={xIn - 30} y={missY + 3} textAnchor="end" style={{ fontSize: 9 }} className="fill-ink-faint">
          miss
        </text>
        <line x1={xIn - 26} x2={xFinal} y1={missY} y2={missY} stroke="var(--color-rule)" strokeWidth={0.5} />

        {results.map((c, i) => {
          const ref = i + 1;
          const [v, k, f, rr] = ranksOf(c);
          const isActive = active === ref;
          const dim = active != null && !isActive;
          const color = citedRefs.has(ref) ? "var(--color-pen)" : "var(--color-ink-faint)";
          const final = rerank ? (rr ?? ref) : (f ?? ref);
          return (
            <g
              key={c.id}
              opacity={dim ? 0.18 : 1}
              onMouseEnter={() => setHover(ref)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onPick(ref)}
              className="cursor-pointer"
            >
              <line x1={xIn - 6} y1={y(v)} x2={xFused} y2={y(f)} stroke={color} strokeWidth={isActive ? 2 : 1.2} />
              <line x1={xIn + 6} y1={y(k)} x2={xFused} y2={y(f)} stroke={color} strokeWidth={isActive ? 2 : 1.2} strokeDasharray="3 2" />
              {rerank && <line x1={xFused} y1={y(f)} x2={xFinal} y2={y(rr)} stroke={color} strokeWidth={isActive ? 2.4 : 1.6} />}
              <circle cx={xIn - 6} cy={y(v)} r={3} fill={v ? color : "var(--color-sheet)"} stroke={color} />
              <rect x={xIn + 3} y={y(k) - 3} width={6} height={6} fill={k ? color : "var(--color-sheet)"} stroke={color} />
              <circle cx={xFused} cy={y(f)} r={3} fill={color} />
              {rerank && <circle cx={xFinal} cy={y(rr)} r={3.5} fill={color} />}
              <text x={xFinal + 10} y={y(final) + 3.5} style={{ fontSize: 10 }} className="fill-ink">
                <tspan fontWeight={600} fill={color}>[{ref}]</tspan>{" "}
                {truncate(docTitle(c.filename), 20)}
                {pageLabel(c) ? ` ${pageLabel(c)}` : ""}
              </text>
              {/* generous invisible hit area */}
              <rect x={0} y={y(final) - 7} width={W} height={14} fill="transparent" />
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10"><circle cx="5" cy="5" r="3" fill="currentColor" /></svg>Vector rank
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10"><rect x="2" y="2" width="6" height="6" fill="currentColor" /></svg>Keyword rank
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 bg-pen" />Cited in the answer
        </span>
      </figcaption>
    </figure>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
