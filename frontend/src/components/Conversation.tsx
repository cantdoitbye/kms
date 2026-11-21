"use client";

import { useEffect, useRef, useState } from "react";
import { bodyOf, ClaimCheck, Mode, MODES } from "@/lib/api";
import { AnswerText } from "./AnswerText";
import type { Turn } from "./types";

const STARTERS = [
  "How many days of annual leave do I get, and how many can I carry over?",
  "What caused the INC-2047 billing outage?",
  "When are production deploys not allowed?",
  "What should I do if I lose my company laptop?",
  "How much is the Growth plan per year with annual billing?",
];

interface Props {
  turns: Turn[];
  selectedId: string | null;
  activeRef: number | null;
  onSelect: (id: string) => void;
  onCite: (turnId: string, ref: number) => void;
  onAsk: (q: string) => void;
  mode: Mode;
  onMode: (m: Mode) => void;
  busy: boolean;
  llmReady: boolean | null;
  hasDocs: boolean;
  scopeNote: string | null;
}

export function Conversation(p: Props) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const lastStatus = p.turns.at(-1)?.status;
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [p.turns.length, lastStatus]);

  function submit(q = draft) {
    const text = q.trim();
    if (!text || p.busy) return;
    p.onAsk(text);
    setDraft("");
  }

  return (
    <div className="flex h-full flex-col">
      <div className="pane flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[44rem] px-6 py-8 sm:px-10">
          {p.turns.length === 0 ? (
            <Empty hasDocs={p.hasDocs} onPick={(q) => submit(q)} />
          ) : (
            <ol className="space-y-10">
              {p.turns.map((t) => (
                <TurnView
                  key={t.id}
                  turn={t}
                  selected={p.selectedId === t.id}
                  activeRef={p.selectedId === t.id ? p.activeRef : null}
                  onSelect={() => p.onSelect(t.id)}
                  onCite={(r) => p.onCite(t.id, r)}
                />
              ))}
            </ol>
          )}
          <div ref={end} />
        </div>
      </div>

      <div className="border-t border-rule bg-paper/95 backdrop-blur">
        <div className="mx-auto max-w-[44rem] px-6 pt-3 pb-4 sm:px-10">
          {p.llmReady === false && (
            <p className="mb-3 rounded-md bg-highlight-soft px-3 py-2 text-xs leading-relaxed text-ink">
              Written answers are off because no LLM key is set, so you&apos;ll get the most relevant passages instead. To
              turn answers on, add a free Groq key as <code className="font-semibold">LLM_API_KEY</code> in{" "}
              <code className="font-semibold">backend/.env</code> and restart the API.
            </p>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="rounded-xl border border-rule bg-sheet shadow-[0_1px_0_var(--color-rule)] focus-within:border-pen"
          >
            <label htmlFor="question" className="sr-only">
              Ask a question
            </label>
            <textarea
              id="question"
              ref={box}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={2}
              placeholder={p.hasDocs ? "Ask about your documents…" : "Add a document to start asking questions"}
              className="block w-full resize-none bg-transparent px-4 pt-3 font-serif text-[16px] leading-snug outline-none placeholder:text-ink-faint"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 px-2.5 pb-2.5">
              <ModeSwitch mode={p.mode} onMode={p.onMode} />
              <button
                type="submit"
                disabled={!draft.trim() || p.busy}
                className="rounded-lg bg-pen px-4 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-35"
              >
                {p.llmReady === false ? "Search" : "Ask"}
              </button>
            </div>
          </form>
          {p.scopeNote && <p className="mt-2 text-xs text-ink-soft">{p.scopeNote}</p>}
        </div>
      </div>
    </div>
  );
}

function ModeSwitch({ mode, onMode }: { mode: Mode; onMode: (m: Mode) => void }) {
  return (
    <div role="radiogroup" aria-label="Search mode" className="flex rounded-lg bg-paper p-0.5">
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          role="radio"
          aria-checked={mode === m.value}
          title={m.hint}
          onClick={() => onMode(m.value)}
          className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
            mode === m.value ? "bg-sheet font-medium text-ink shadow-[0_0_0_1px_var(--color-rule)]" : "text-ink-soft hover:text-ink"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

function Empty({ hasDocs, onPick }: { hasDocs: boolean; onPick: (q: string) => void }) {
  return (
    <div className="pt-[4vh]">
      <h1 className="font-serif text-[2rem] sm:text-[2.6rem] leading-[1.1] tracking-[-0.01em] text-ink">
        Ask your documents.
        <br />
        <span className="text-ink-soft">Every answer shows its sources.</span>
      </h1>
      <p className="mt-5 max-w-[34rem] text-[15px] leading-relaxed text-ink-soft">
        Margin searches your files by meaning and by exact keywords, reranks the best passages, and writes an answer
        that cites the file, page and section each claim comes from.
      </p>
      {hasDocs && (
        <div className="mt-10">
          <h2 className="mb-3 text-sm font-medium">Try a question about the Northwind Labs demo files</h2>
          <ul className="divide-y divide-rule border-y border-rule">
            {STARTERS.map((q) => (
              <li key={q}>
                <button
                  onClick={() => onPick(q)}
                  className="group flex w-full items-center justify-between gap-4 py-3 text-left font-serif text-[16.5px] text-ink hover:text-pen"
                >
                  {q}
                  <svg width="16" height="16" viewBox="0 0 16 16" className="shrink-0 text-ink-faint group-hover:text-pen" aria-hidden>
                    <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-soft">
            After an answer, ask a follow-up like &ldquo;who owns the action items?&rdquo; to see the question get
            rewritten using the conversation.
          </p>
        </div>
      )}
    </div>
  );
}

function TurnView({
  turn,
  selected,
  activeRef,
  onSelect,
  onCite,
}: {
  turn: Turn;
  selected: boolean;
  activeRef: number | null;
  onSelect: () => void;
  onCite: (ref: number) => void;
}) {
  return (
    <li className="scroll-mt-6">
      <p className="text-[15px] font-medium text-ink">{turn.question}</p>
      <div
        onClick={turn.status === "done" ? onSelect : undefined}
        className={`relative mt-3 border-l-2 pl-5 ${selected && turn.status === "done" ? "border-pen" : "border-rule"} ${
          turn.status === "done" && !selected ? "cursor-pointer" : ""
        }`}
      >
        {turn.status === "loading" && (
          <p className="thinking flex items-center gap-1 py-1 text-sm text-ink-soft" aria-live="polite">
            {turn.kind === "passages" ? "Searching" : "Searching and writing"}
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </p>
        )}
        {turn.status === "error" && (
          <p className="text-sm text-bad" role="alert">
            {turn.error}
          </p>
        )}
        {turn.status === "done" && turn.kind === "answer" && (
          <div className="font-serif text-[17px] leading-[1.6] text-ink">
            <AnswerText text={turn.answer ?? ""} onCite={onCite} activeRef={activeRef} />
          </div>
        )}
        {turn.status === "done" && turn.kind === "passages" && (
          <div className="space-y-3">
            {turn.results.length === 0 && <p className="text-sm text-ink-soft">No passages matched this question.</p>}
            {turn.results.slice(0, 3).map((c, i) => (
              <button key={c.id} onClick={() => onCite(i + 1)} className="block text-left">
                <span className="text-xs text-ink-soft">
                  [{i + 1}] {c.filename}
                  {c.section ? `, ${c.section}` : ""}
                </span>
                <span className="mt-0.5 line-clamp-3 font-serif text-[15.5px] leading-relaxed">{bodyOf(c)}</span>
              </button>
            ))}
          </div>
        )}
        {turn.status === "done" && turn.kind === "answer" && turn.claims && turn.claims.length > 0 && (
          <ClaimSummary claims={turn.claims} onCite={onCite} />
        )}
        {turn.status === "done" && (
          <p className="mt-3 text-xs text-ink-faint">
            {turn.results.length} passages retrieved in {Math.round(turn.timings.total_retrieval ?? 0)} ms
            {turn.timings.generate ? `, answer written in ${(turn.timings.generate / 1000).toFixed(1)} s` : ""}
          </p>
        )}
      </div>
    </li>
  );
}

/** One-line result of the claim-level citation check, expandable to show flagged sentences. */
function ClaimSummary({ claims, onCite }: { claims: ClaimCheck[]; onCite: (ref: number) => void }) {
  const [open, setOpen] = useState(false);
  const checked = claims.filter((c) => c.verdict === "supported" || c.verdict === "unsupported");
  const unsupported = claims.filter((c) => c.verdict === "unsupported");
  const uncited = claims.filter((c) => c.verdict === "uncited");
  const flagged = [...unsupported, ...uncited];
  if (!checked.length && !uncited.length) return null;

  const tone = unsupported.length ? "text-bad" : "text-ok";
  const summary = unsupported.length
    ? `${unsupported.length} of ${checked.length} cited ${checked.length === 1 ? "claim isn't" : "claims aren't"} supported by ${unsupported.length === 1 ? "its source" : "their sources"}`
    : `${checked.length} cited ${checked.length === 1 ? "claim" : "claims"} checked against ${checked.length === 1 ? "its source" : "their sources"}`;

  return (
    <div className="mt-4 font-sans text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!flagged.length}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-left disabled:cursor-default"
      >
        <span className={`size-1.5 shrink-0 rounded-full ${unsupported.length ? "bg-bad" : "bg-ok"}`} />
        <span>
          <span className={tone}>{summary}</span>
          {uncited.length > 0 && (
            <span className="text-ink-soft">
              , {uncited.length} {uncited.length === 1 ? "sentence has" : "sentences have"} no citation
            </span>
          )}
        </span>
        {flagged.length > 0 && <span className="text-pen">{open ? "Hide" : "Show"}</span>}
      </button>
      {open && (
        <ul className="mt-2 space-y-2 border-l border-rule pl-3">
          {flagged.map((c, i) => (
            <li key={i}>
              <p className="font-serif text-[14px] text-ink">&ldquo;{c.text}&rdquo;</p>
              <p className={c.verdict === "unsupported" ? "text-bad" : "text-ink-soft"}>
                {c.verdict === "unsupported" ? "Not supported" : "No citation"}
                {c.reason && c.verdict === "unsupported" ? `: ${c.reason}` : ""}
                {c.refs.map((r) => (
                  <button key={r} onClick={() => onCite(r)} className="ml-1.5 text-pen hover:underline">
                    source {r}
                  </button>
                ))}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
