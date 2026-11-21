import type { ChunkResult, ClaimCheck, Mode } from "@/lib/api";

/** One question and whatever came back for it. */
export interface Turn {
  id: string;
  question: string;
  mode: Mode;
  status: "loading" | "done" | "error";
  /** "answer" = LLM answer with citations; "passages" = retrieval only (no LLM key). */
  kind: "answer" | "passages";
  answer?: string;
  standalone?: string;
  results: ChunkResult[];
  cited: Set<number>;
  timings: Record<string, number>;
  usage?: { prompt_tokens: number; completion_tokens: number };
  claims?: ClaimCheck[];
  model?: string;
  error?: string;
}
