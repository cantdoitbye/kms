"use client";

import { useEffect, useRef, useState } from "react";
import type { Stats } from "@/lib/api";

const PIPELINE = [
  ["Extract", "PyMuPDF and python-docx pull text with page numbers and headings; repeated headers and footers are removed."],
  ["Chunk", "Text is split by section, then packed into passages of up to 400 tokens with 60 tokens of sentence overlap."],
  ["Embed", "Each passage, prefixed with its document title and section, is embedded locally with bge-small-en-v1.5."],
  ["Store", "Vectors go into Postgres with pgvector (HNSW index); a generated tsvector column plus term statistics power BM25 keyword search."],
  ["Retrieve", "Your question runs through vector search and BM25 keyword search (computed in SQL); Reciprocal Rank Fusion merges the two rankings."],
  ["Rerank", "A cross-encoder rescores the top 20 candidates against the question and keeps the best 5."],
  ["Answer", "The LLM answers only from those passages and must cite them; follow-ups are rewritten into standalone questions first."],
  ["Verify", "A second LLM pass checks each cited sentence against the exact passages it cites and flags anything they don't support."],
] as const;

export function Header({
  stats,
  apiDown,
  onToggleLibrary,
}: {
  stats: Stats | null;
  apiDown: boolean;
  onToggleLibrary: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !panel.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-4 border-b border-rule bg-sheet px-5">
      <button onClick={onToggleLibrary} className="rounded p-1 text-ink-soft hover:bg-rule/60 lg:hidden" aria-label="Show library">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 5h12M3 9h12M3 13h12" strokeLinecap="round" />
        </svg>
      </button>
      <div className="flex items-baseline gap-3">
        <span className="font-serif text-[22px] font-medium italic tracking-tight">Margin</span>
        <span className="hidden text-sm text-ink-soft sm:inline">Knowledge base with cited answers</span>
      </div>

      <div className="ml-auto flex items-center gap-5 text-xs text-ink-soft">
        {apiDown ? (
          <span className="flex items-center gap-1.5 text-bad">
            <span className="size-1.5 rounded-full bg-bad" />
            API offline. Start the backend on port 8000.
          </span>
        ) : (
          stats && (
            <span className="hidden items-center gap-4 md:flex">
              <span>
                <b className="font-semibold text-ink">{stats.documents_ready}</b> documents
              </span>
              <span>
                <b className="font-semibold text-ink">{stats.chunks}</b> passages indexed
              </span>
              <span className="flex items-center gap-1.5" title={stats.llm_configured ? "LLM connected" : "No LLM key set"}>
                <span className={`size-1.5 rounded-full ${stats.llm_configured ? "bg-ok" : "bg-wait"}`} />
                {stats.llm_configured ? stats.llm_model : "Search only"}
              </span>
            </span>
          )
        )}
        <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" className="hidden hover:text-ink sm:inline">
          API docs
        </a>
        <div className="relative" ref={panel}>
          <button
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="rounded-md border border-rule px-2.5 py-1 font-medium text-ink hover:border-ink-faint"
          >
            How it works
          </button>
          {open && (
            <div className="absolute right-0 mt-2 w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-rule bg-sheet p-5 text-sm shadow-[0_12px_40px_-12px_rgba(23,35,58,0.25)]">
              <p className="mb-4 text-ink-soft">What happens between uploading a file and getting an answer:</p>
              <ol className="space-y-3">
                {PIPELINE.map(([title, body], i) => (
                  <li key={title} className="grid grid-cols-[1.25rem_1fr] gap-x-2">
                    <span className="pt-px text-xs font-semibold text-pen tabular-nums">{i + 1}</span>
                    <div>
                      <p className="font-medium text-ink">{title}</p>
                      <p className="text-[13px] leading-snug text-ink-soft">{body}</p>
                    </div>
                  </li>
                ))}
              </ol>
              {stats && (
                <p className="mt-4 border-t border-rule pt-3 text-xs text-ink-soft">
                  Models: {stats.embedding_model}, {stats.reranker_model}, {stats.llm_model}.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
