"use client";

import { useRef, useState } from "react";
import { api, DocumentInfo, docTitle, fileKind } from "@/lib/api";

const ACCEPT = ".pdf,.docx,.txt,.md";

interface Props {
  docs: DocumentInfo[];
  loaded: boolean;
  selected: Set<string>;
  inspecting: string | null;
  onToggle: (id: string) => void;
  onInspect: (id: string) => void;
  onChanged: () => void;
}

export function Library({ docs, loaded, selected, inspecting, onToggle, onInspect, onChanged }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function upload(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setNotice(null);
    setUploading((n) => n + list.length);
    const messages: string[] = [];
    let failed = false;
    await Promise.all(
      list.map(async (f) => {
        try {
          const res = await api.upload(f);
          if (res.duplicate) messages.push(`${f.name} is already in the library.`);
        } catch (e) {
          failed = true;
          messages.push(`${f.name}: ${(e as Error).message}`);
        } finally {
          setUploading((n) => n - 1);
        }
      }),
    );
    if (messages.length) setNotice({ tone: failed ? "bad" : "ok", text: messages.join(" ") });
    onChanged();
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline justify-between px-5 pt-5 pb-3">
        <h2 className="text-[15px] font-semibold">Library</h2>
        {docs.length > 0 && (
          <span className="text-xs text-ink-faint">
            {docs.length} {docs.length === 1 ? "document" : "documents"}
          </span>
        )}
      </div>

      <div className="px-5">
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            upload(e.dataTransfer.files);
          }}
          className={`w-full rounded-lg border border-dashed px-4 py-4 text-left transition-colors ${
            dragging ? "border-pen bg-pen-soft" : "border-rule bg-sheet hover:border-ink-faint"
          }`}
        >
          <span className="block text-sm font-medium">
            {uploading ? `Uploading ${uploading} ${uploading === 1 ? "file" : "files"}…` : "Add documents"}
          </span>
          <span className="mt-0.5 block text-xs text-ink-soft">Drop files here or click to browse. PDF, DOCX, TXT, MD up to 25 MB.</span>
        </button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) upload(e.target.files);
            e.target.value = "";
          }}
        />
        {notice && (
          <p role="status" className={`mt-2 text-xs ${notice.tone === "bad" ? "text-bad" : "text-ink-soft"}`}>
            {notice.text}
          </p>
        )}
      </div>

      {selected.size > 0 && (
        <p className="mx-5 mt-4 text-xs text-ink-soft">
          Questions search {selected.size} of {docs.length} documents.{" "}
          <button className="text-pen underline-offset-2 hover:underline" onClick={() => selected.forEach(onToggle)}>
            Search all
          </button>
        </p>
      )}

      <ul className="pane mt-3 flex-1 overflow-y-auto px-3 pb-5">
        {!loaded &&
          [0, 1, 2].map((i) => <li key={i} className="mx-2 my-2 h-12 animate-pulse rounded-md bg-rule/50" />)}
        {loaded && docs.length === 0 && (
          <li className="px-2 py-6 text-sm text-ink-soft">
            No documents yet. Add a PDF or Word file above, and you can ask questions about it as soon as it&apos;s
            indexed.
          </li>
        )}
        {docs.map((d) => (
          <DocRow
            key={d.id}
            doc={d}
            checked={selected.has(d.id)}
            active={inspecting === d.id}
            onToggle={() => onToggle(d.id)}
            onInspect={() => onInspect(d.id)}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </div>
  );
}

function DocRow({
  doc,
  checked,
  active,
  onToggle,
  onInspect,
  onChanged,
}: {
  doc: DocumentInfo;
  checked: boolean;
  active: boolean;
  onToggle: () => void;
  onInspect: () => void;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const busy = doc.status === "pending" || doc.status === "processing";

  return (
    <li
      className={`group relative rounded-md px-2 py-2.5 ${active ? "bg-pen-soft" : "hover:bg-sheet"}`}
    >
      <div className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={doc.status !== "ready"}
          aria-label={`Limit questions to ${doc.filename}`}
          title="Limit questions to selected documents"
          className="mt-1 size-3.5 accent-pen"
        />
        <div className="min-w-0 flex-1">
          <button
            onClick={onInspect}
            disabled={doc.status !== "ready"}
            className="line-clamp-2 block w-full text-left text-sm leading-snug font-medium first-letter:uppercase hover:text-pen disabled:cursor-default disabled:hover:text-ink"
            title={doc.status === "ready" ? `${doc.filename}: show how it was split into passages` : doc.filename}
          >
            {docTitle(doc.filename)}
          </button>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-soft">
            <span className="rounded-sm border border-rule px-1 text-[10px] font-semibold tracking-wide text-ink-faint">
              {fileKind(doc.filename)}
            </span>
            {doc.status === "ready" && (
              <span>
                {doc.num_chunks} passages
                {doc.num_pages ? `, ${doc.num_pages} ${doc.num_pages === 1 ? "page" : "pages"}` : ""}
              </span>
            )}
            {busy && (
              <span className="flex items-center gap-1.5 text-wait">
                <span className="size-1.5 animate-pulse rounded-full bg-wait" />
                {doc.status === "pending" ? "Queued" : "Indexing"}
              </span>
            )}
            {doc.status === "failed" && <span className="text-bad">Couldn&apos;t index</span>}
          </div>
          {doc.status === "failed" && doc.error && (
            <p className="mt-1 text-xs text-ink-soft">
              {doc.error}{" "}
              <button
                className="text-pen hover:underline"
                onClick={async () => {
                  await api.reprocess(doc.id);
                  onChanged();
                }}
              >
                Try again
              </button>
            </p>
          )}
        </div>
        <div className={`flex items-center ${confirming ? "" : "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"}`}>
          {confirming ? (
            <>
              <button
                className="rounded px-1.5 py-0.5 text-xs font-medium text-bad hover:bg-bad/10"
                onClick={async () => {
                  await api.remove(doc.id);
                  onChanged();
                }}
              >
                Delete
              </button>
              <button className="rounded px-1.5 py-0.5 text-xs text-ink-soft hover:bg-rule/60" onClick={() => setConfirming(false)}>
                Keep
              </button>
            </>
          ) : (
            <button
              aria-label={`Delete ${doc.filename}`}
              className="rounded p-1 text-ink-faint hover:bg-rule/60 hover:text-ink"
              onClick={() => setConfirming(true)}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
