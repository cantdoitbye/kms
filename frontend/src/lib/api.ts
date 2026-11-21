export type DocStatus = "pending" | "processing" | "ready" | "failed";
export type Mode = "vector" | "keyword" | "hybrid" | "hybrid_rerank";

export const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "vector", label: "Vector", hint: "Semantic similarity only (pgvector HNSW)" },
  { value: "keyword", label: "Keyword", hint: "Postgres full-text search only" },
  { value: "hybrid", label: "Hybrid", hint: "Vector + keyword merged with Reciprocal Rank Fusion" },
  {
    value: "hybrid_rerank",
    label: "Hybrid + rerank",
    hint: "Hybrid candidates re-scored by a cross-encoder (default)",
  },
];

export interface DocumentInfo {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocStatus;
  error: string | null;
  num_pages: number | null;
  num_chunks: number;
  meta: {
    timings_ms?: Record<string, number>;
    avg_chunk_tokens?: number;
    num_headings?: number;
    total_tokens?: number;
  };
  created_at: string;
}

export interface ChunkResult {
  id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  content: string;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
  score: number;
  scores: Partial<
    Record<
      "vector_sim" | "vector_rank" | "keyword_rank" | "keyword_rank_score" | "rrf" | "rrf_rank" | "rerank" | "rerank_rank",
      number
    >
  >;
}

export interface Citation {
  ref: number;
  chunk: ChunkResult;
  cited: boolean;
}

export interface ClaimCheck {
  text: string;
  refs: number[];
  verdict: "supported" | "unsupported" | "uncited" | "unchecked";
  reason: string;
}

export interface AskResponse {
  question: string;
  standalone_question: string;
  answer: string;
  citations: Citation[];
  claims: ClaimCheck[];
  timings_ms: Record<string, number>;
  usage: { prompt_tokens: number; completion_tokens: number };
  model: string;
}

export interface SearchResponse {
  query: string;
  mode: Mode;
  results: ChunkResult[];
  timings_ms: Record<string, number>;
}

export interface Stats {
  documents: number;
  documents_ready: number;
  chunks: number;
  embedding_model: string;
  reranker_model: string;
  llm_model: string;
  llm_configured: boolean;
}

export interface ChunkPreview {
  id: string;
  chunk_index: number;
  content: string;
  token_count: number;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError("Can't reach the API. Is the backend running on port 8000?", 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error (e.g. proxy failure) */
      if (res.status >= 500) detail = "The API isn't responding. Is the backend running on port 8000?";
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  stats: () => request<Stats>("/stats"),
  documents: () => request<DocumentInfo[]>("/documents"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ document: DocumentInfo; duplicate: boolean }>("/documents", { method: "POST", body: form });
  },
  remove: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  reprocess: (id: string) => request<DocumentInfo>(`/documents/${id}/reprocess`, { method: "POST" }),
  chunks: (id: string) => request<{ total: number; items: ChunkPreview[] }>(`/documents/${id}/chunks?limit=200`),
  search: (body: { query: string; mode: Mode; top_k?: number; document_ids?: string[] }) =>
    request<SearchResponse>("/search", json(body)),
  ask: (body: {
    question: string;
    mode: Mode;
    top_k?: number;
    document_ids?: string[];
    history?: { role: "user" | "assistant"; content: string }[];
  }) => request<AskResponse>("/ask", json(body)),
};

export function pageLabel(c: { page_start: number | null; page_end: number | null }) {
  if (!c.page_start) return null;
  return c.page_start === c.page_end ? `p. ${c.page_start}` : `pp. ${c.page_start}–${c.page_end}`;
}

export function fileKind(filename: string) {
  return filename.split(".").pop()?.toUpperCase() ?? "";
}

/** "northwind_employee_handbook.pdf" -> "northwind employee handbook" */
export function docTitle(filename: string) {
  return filename.replace(/\.[^.]+$/, "").replace(/_+/g, " ");
}

/** Passages start with their section heading; drop it when we already show the section. */
export function bodyOf(c: { content: string; section: string | null }) {
  const first = c.section?.split("; ")[0];
  if (first && c.content.startsWith(first)) return c.content.slice(first.length).trim();
  return c.content;
}
