"use client";

import { useEffect, useRef, useState } from "react";
import { api, bodyOf, ChunkPreview, ChunkResult, DocumentInfo, MODES, pageLabel } from "@/lib/api";
import { RankLadder } from "./RankLadder";
import type { Turn } from "./types";

type Tab = "sources" | "trace";

export function SidePanel({
  turn,
  activeRef,
  onPickRef,
  inspectDoc,
  onCloseInspect,
}: {
  turn: Turn | null;
  activeRef: number | null;
  onPickRef: (ref: number | null) => void;
  inspectDoc: DocumentInfo | null;
  onCloseInspect: () => void;
}) {
  const [tab, setTab] = useState<Tab>("sources");

  if (inspectDoc) return <ChunkInspector key={inspectDoc.id} doc={inspectDoc} onClose={onCloseInspect} />;

  if (!turn || turn.status !== "done") {
    return (
      <div className="px-6 pt-6 text-sm leading-relaxed text-ink-soft">
        <h2 className="mb-2 text-[15px] font-semibold text-ink">Sources</h2>
        <p>
          Every answer lists the passages it was built from, with file, page and section. Click a number in an answer
          to jump to its passage here.
        </p>
        <p className="mt-3">
          The <span className="text-ink">Retrieval trace</span> tab shows how vector search, keyword search and the
          reranker each ranked those passages, and where the time went.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" className="flex gap-5 border-b border-rule px-6 pt-4">
        {(
          [
            ["sources", "Sources"],
            ["trace", "Retrieval trace"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 pb-2.5 text-sm font-medium transition-colors ${
              tab === key ? "border-pen text-ink" : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="pane flex-1 overflow-y-auto px-6 py-5">
        {tab === "sources" ? (
          <Sources turn={turn} activeRef={activeRef} onPickRef={onPickRef} />
        ) : (
          <Trace turn={turn} activeRef={activeRef} onPickRef={onPickRef} />
        )}
      </div>
    </div>
  );
}

function Sources({ turn, activeRef, onPickRef }: { turn: Turn; activeRef: number | null; onPickRef: (r: number | null) => void }) {
  const results = turn.results;
  const cited = turn.cited;
  const refs = useRef<Record<number, HTMLLIElement | null>>({});

  useEffect(() => {
    if (activeRef != null) refs.current[activeRef]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeRef]);

  if (!results.length) return <p className="text-sm text-ink-soft">No passages matched this question.</p>;

  const citedList = results.map((c, i) => ({ c, ref: i + 1 })).filter((x) => cited.has(x.ref));
  const rest = results.map((c, i) => ({ c, ref: i + 1 })).filter((x) => !cited.has(x.ref));
  const showGroups = turn.kind === "answer";

  return (
    <div className="space-y-6">
      {[
        { title: showGroups ? "Cited in the answer" : "Most relevant passages", items: showGroups ? citedList : rest },
        { title: "Retrieved but not cited", items: showGroups ? rest : [] },
      ]
        .filter((g) => g.items.length)
        .map((g) => (
          <section key={g.title}>
            <h3 className="mb-2.5 text-xs font-medium text-ink-soft">{g.title}</h3>
            <ol className="space-y-3">
              {g.items.map(({ c, ref }) => (
                <SourceCard
                  key={c.id}
                  chunk={c}
                  refNum={ref}
                  active={activeRef === ref}
                  onClick={() => onPickRef(activeRef === ref ? null : ref)}
                  liRef={(el) => {
                    refs.current[ref] = el;
                  }}
                />
              ))}
            </ol>
          </section>
        ))}
    </div>
  );
}

function SourceCard({
  chunk,
  refNum,
  active,
  onClick,
  liRef,
}: {
  chunk: ChunkResult;
  refNum: number;
  active: boolean;
  onClick: () => void;
  liRef: (el: HTMLLIElement | null) => void;
}) {
  const page = pageLabel(chunk);
  return (
    <li
      ref={liRef}
      className={`rounded-lg border bg-sheet transition-colors ${active ? "border-highlight shadow-[0_0_0_3px_var(--color-highlight-soft)]" : "border-rule"}`}
    >
      <button onClick={onClick} className="w-full px-4 py-3 text-left" aria-expanded={active}>
        <div className="flex items-start gap-2.5">
          <span
            className={`mt-px inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] px-1 text-[11px] font-semibold ${
              active ? "bg-highlight text-ink" : "bg-pen-soft text-pen"
            }`}
          >
            {refNum}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{chunk.filename}</p>
            <p className="truncate text-xs text-ink-soft">
              {[page, chunk.section].filter(Boolean).join(", ") || `Passage ${chunk.chunk_index + 1}`}
            </p>
          </div>
        </div>
        <p
          className={`mt-2.5 font-serif text-[14.5px] leading-relaxed text-ink ${active ? "marked" : "line-clamp-3"}`}
        >
          {bodyOf(chunk)}
        </p>
      </button>
    </li>
  );
}

const STAGES: { key: string; label: string; color: string }[] = [
  { key: "condense_query", label: "Rewrite follow-up", color: "#c3c8f5" },
  { key: "embed_query", label: "Embed question", color: "#8f97ea" },
  { key: "vector_search", label: "Vector search", color: "#5c66de" },
  { key: "keyword_search", label: "Keyword search", color: "#3b45cf" },
  { key: "fusion", label: "Fuse", color: "#2b36c9" },
  { key: "load_chunks", label: "Load passages", color: "#a4abc0" },
  { key: "rerank", label: "Rerank", color: "#17233a" },
  { key: "generate", label: "Generate answer", color: "#e2c93b" },
  { key: "verify", label: "Check citations", color: "#f3e08a" },
];

function Trace({ turn, activeRef, onPickRef }: { turn: Turn; activeRef: number | null; onPickRef: (r: number | null) => void }) {
  const stages = STAGES.filter((s) => (turn.timings[s.key] ?? 0) > 0).map((s) => ({ ...s, ms: turn.timings[s.key] }));
  const total = stages.reduce((a, s) => a + s.ms, 0);
  const modeLabel = MODES.find((m) => m.value === turn.mode)?.label;

  return (
    <div className="space-y-7">
      {turn.standalone && turn.standalone !== turn.question && (
        <section>
          <h3 className="mb-1.5 text-xs font-medium text-ink-soft">Follow-up rewritten as</h3>
          <p className="font-serif text-[15px] italic">&ldquo;{turn.standalone}&rdquo;</p>
        </section>
      )}

      <section>
        <h3 className="mb-1 text-xs font-medium text-ink-soft">How each passage was ranked ({modeLabel})</h3>
        <RankLadder
          results={turn.results}
          mode={turn.mode}
          citedRefs={turn.kind === "answer" ? turn.cited : new Set(turn.results.map((_, i) => i + 1))}
          activeRef={activeRef}
          onPick={(r) => onPickRef(r)}
        />
      </section>

      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-xs font-medium text-ink-soft">Where the time went</h3>
          <span className="text-sm font-medium">{fmtMs(total)}</span>
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-rule/60">
          {stages.map((s) => (
            <div key={s.key} style={{ width: `${(s.ms / total) * 100}%`, background: s.color }} title={`${s.label}: ${fmtMs(s.ms)}`} />
          ))}
        </div>
        <dl className="mt-3 grid grid-cols-[auto_1fr_auto] items-center gap-x-2.5 gap-y-1.5 text-xs">
          {stages.map((s) => (
            <div key={s.key} className="contents">
              <span className="size-2 rounded-sm" style={{ background: s.color }} />
              <dt className="text-ink-soft">{s.label}</dt>
              <dd className="text-right tabular-nums">{fmtMs(s.ms)}</dd>
            </div>
          ))}
        </dl>
      </section>

      {turn.usage && (
        <section className="text-xs text-ink-soft">
          <p>
            {turn.model} used {turn.usage.prompt_tokens.toLocaleString()} prompt tokens and{" "}
            {turn.usage.completion_tokens.toLocaleString()} completion tokens.
          </p>
        </section>
      )}
    </div>
  );
}

function fmtMs(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

function ChunkInspector({ doc, onClose }: { doc: DocumentInfo; onClose: () => void }) {
  const [chunks, setChunks] = useState<ChunkPreview[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .chunks(doc.id)
      .then((r) => live && setChunks(r.items))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [doc.id]);

  const t = doc.meta.timings_ms ?? {};
  const indexMs = Object.values(t).reduce((a, b) => a + b, 0);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-rule px-6 pt-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold">{doc.filename}</h2>
            <p className="mt-0.5 text-xs text-ink-soft">
              Split into {doc.num_chunks} passages averaging {Math.round(doc.meta.avg_chunk_tokens ?? 0)} tokens
              {doc.meta.num_headings ? `, ${doc.meta.num_headings} headings detected` : ""}. Indexed in{" "}
              {fmtMs(indexMs)}.
            </p>
          </div>
          <button onClick={onClose} className="rounded px-2 py-1 text-sm text-ink-soft hover:bg-rule/60 hover:text-ink">
            Close
          </button>
        </div>
      </div>
      <div className="pane flex-1 overflow-y-auto px-6 py-4">
        {error && <p className="text-sm text-bad">{error}</p>}
        {!chunks && !error && <p className="text-sm text-ink-soft">Loading passages…</p>}
        <ol className="space-y-4">
          {chunks?.map((c) => (
            <li key={c.id} className="border-l-2 border-rule pl-4">
              <p className="mb-1 text-xs text-ink-soft">
                Passage {c.chunk_index + 1}
                {pageLabel(c) ? `, ${pageLabel(c)}` : ""}
                {c.section ? `, ${c.section}` : ""}
                <span className="text-ink-faint">, {c.token_count} tokens</span>
              </p>
              <div className="space-y-2 font-serif text-[14.5px] leading-relaxed">
                {c.content.split(/\n\s*\n/).map((para, i) => (
                  <p key={i} className={i === 0 && para === c.section?.split("; ")[0] ? "font-sans text-[13px] font-semibold" : ""}>
                    {para}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

