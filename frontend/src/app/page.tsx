"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, DocumentInfo, Mode, Stats } from "@/lib/api";
import { Conversation } from "@/components/Conversation";
import { Library } from "@/components/Library";
import { SidePanel } from "@/components/SidePanel";
import { Header } from "@/components/Header";
import type { Turn } from "@/components/types";

const fetchAll = () => Promise.all([api.documents(), api.stats()]);

export default function Home() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [apiDown, setApiDown] = useState(false);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [inspecting, setInspecting] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [selectedTurn, setSelectedTurn] = useState<string | null>(null);
  const [activeRef, setActiveRef] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("hybrid_rerank");
  const [libraryOpen, setLibraryOpen] = useState(false);

  const applyData = useCallback(([d, s]: [DocumentInfo[], Stats]) => {
    setDocs(d);
    setStats(s);
    setApiDown(false);
    setLoaded(true);
    // Drop selections for documents that no longer exist.
    setSelectedDocs((prev) => new Set([...prev].filter((id) => d.some((x) => x.id === id))));
  }, []);
  const markDown = useCallback(() => {
    setApiDown(true);
    setLoaded(true);
  }, []);
  const refresh = useCallback(() => {
    fetchAll().then(applyData, markDown);
  }, [applyData, markDown]);

  useEffect(() => {
    fetchAll().then(applyData, markDown);
  }, [applyData, markDown]);

  // Poll while anything is still being indexed (or while the API is unreachable).
  const indexing = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!indexing && !apiDown) return;
    const t = setInterval(refresh, apiDown ? 4000 : 1500);
    return () => clearInterval(t);
  }, [indexing, apiDown, refresh]);

  const ready = docs.filter((d) => d.status === "ready");
  const busy = turns.some((t) => t.status === "loading");

  async function ask(question: string) {
    const id = crypto.randomUUID();
    const useLLM = stats?.llm_configured !== false;
    const scope = selectedDocs.size ? [...selectedDocs] : undefined;
    const base: Turn = {
      id,
      question,
      mode,
      status: "loading",
      kind: useLLM ? "answer" : "passages",
      results: [],
      cited: new Set(),
      timings: {},
    };
    // Conversation history for follow-up rewriting (answered turns only).
    const history = turns
      .filter((t) => t.status === "done" && t.kind === "answer")
      .slice(-3)
      .flatMap((t) => [
        { role: "user" as const, content: t.question },
        { role: "assistant" as const, content: t.answer ?? "" },
      ]);

    setTurns((ts) => [...ts, base]);
    setInspecting(null);
    const patch = (p: Partial<Turn>) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));

    try {
      if (useLLM) {
        const r = await api.ask({ question, mode, top_k: 5, document_ids: scope, history });
        patch({
          status: "done",
          answer: r.answer,
          standalone: r.standalone_question,
          results: r.citations.map((c) => c.chunk),
          cited: new Set(r.citations.filter((c) => c.cited).map((c) => c.ref)),
          timings: r.timings_ms,
          usage: r.usage,
          claims: r.claims,
          model: r.model,
        });
      } else {
        const r = await api.search({ query: question, mode, top_k: 5, document_ids: scope });
        patch({ status: "done", results: r.results, timings: r.timings_ms });
      }
      setSelectedTurn(id);
      setActiveRef(null);
    } catch (e) {
      const err = e as ApiError;
      // Key missing/invalid at runtime: fall back to retrieval-only for this question.
      if (useLLM && (err.status === 503 || err.status === 502)) {
        try {
          const r = await api.search({ query: question, mode, top_k: 5, document_ids: scope });
          patch({ status: "done", kind: "passages", results: r.results, timings: r.timings_ms });
          setSelectedTurn(id);
          setStats((s) => (s && err.status === 503 ? { ...s, llm_configured: false } : s));
          return;
        } catch {
          /* fall through */
        }
      }
      patch({ status: "error", error: err.message });
    }
  }

  const turn = useMemo(() => turns.find((t) => t.id === selectedTurn) ?? null, [turns, selectedTurn]);
  const inspectDoc = docs.find((d) => d.id === inspecting) ?? null;
  const scopeNote = selectedDocs.size
    ? `Searching ${selectedDocs.size} selected ${selectedDocs.size === 1 ? "document" : "documents"}.`
    : null;

  return (
    <div className="flex h-full flex-col">
      <Header stats={stats} apiDown={apiDown} onToggleLibrary={() => setLibraryOpen((o) => !o)} />
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[17.5rem_minmax(0,1fr)_23rem]">
        <aside
          className={`${libraryOpen ? "block" : "hidden"} min-h-0 border-r border-rule bg-paper lg:block max-lg:absolute max-lg:inset-x-0 max-lg:top-14 max-lg:bottom-0 max-lg:z-20`}
        >
          <Library
            docs={docs}
            loaded={loaded}
            selected={selectedDocs}
            inspecting={inspecting}
            onToggle={(id) =>
              setSelectedDocs((prev) => {
                const next = new Set(prev);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
              })
            }
            onInspect={(id) => {
              setInspecting((cur) => (cur === id ? null : id));
              setLibraryOpen(false);
            }}
            onChanged={refresh}
          />
        </aside>
        <section className="min-h-0 bg-paper">
          <Conversation
            turns={turns}
            selectedId={selectedTurn}
            activeRef={activeRef}
            onSelect={(id) => {
              setSelectedTurn(id);
              setActiveRef(null);
              setInspecting(null);
            }}
            onCite={(tid, ref) => {
              setSelectedTurn(tid);
              setInspecting(null);
              setActiveRef((cur) => (cur === ref && tid === selectedTurn ? null : ref));
            }}
            onAsk={ask}
            mode={mode}
            onMode={setMode}
            busy={busy}
            llmReady={stats ? stats.llm_configured : null}
            hasDocs={ready.length > 0}
            scopeNote={scopeNote}
          />
        </section>
        <aside className="hidden min-h-0 border-l border-rule bg-sheet/60 lg:block">
          <SidePanel
            turn={turn}
            activeRef={activeRef}
            onPickRef={setActiveRef}
            inspectDoc={inspectDoc}
            onCloseInspect={() => setInspecting(null)}
          />
        </aside>
      </main>
    </div>
  );
}
