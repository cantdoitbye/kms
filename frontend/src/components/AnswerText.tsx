"use client";

import { Fragment, ReactNode } from "react";

/**
 * Minimal markdown renderer for LLM answers: paragraphs, bullet/numbered lists,
 * **bold**, `code`, and [n] citation markers turned into clickable chips.
 */
export function AnswerText({
  text,
  onCite,
  activeRef,
}: {
  text: string;
  onCite?: (ref: number) => void;
  activeRef?: number | null;
}) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const isList = lines.length > 0 && lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l));
        if (isList) {
          const ordered = /^\s*\d/.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={i} className={`space-y-1.5 pl-5 ${ordered ? "list-decimal" : "list-disc"} marker:text-ink-faint`}>
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), onCite, activeRef)}</li>
              ))}
            </Tag>
          );
        }
        return <p key={i}>{inline(lines.join(" "), onCite, activeRef)}</p>;
      })}
    </div>
  );
}

function inline(text: string, onCite?: (ref: number) => void, activeRef?: number | null): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g);
  return parts.map((part, i) => {
    if (!part) return null;
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const n = Number(cite[1]);
      return (
        <button
          key={i}
          onClick={() => onCite?.(n)}
          aria-label={`Show source ${n}`}
          className={`mx-px inline-flex h-[1.15rem] min-w-[1.15rem] -translate-y-px items-center justify-center rounded-[4px] px-1 align-middle font-sans text-[11px] font-semibold transition-colors ${
            activeRef === n ? "bg-highlight text-ink" : "bg-pen-soft text-pen hover:bg-highlight hover:text-ink"
          }`}
        >
          {n}
        </button>
      );
    }
    if (part.startsWith("**")) return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`"))
      return (
        <code key={i} className="rounded bg-rule/50 px-1 py-px font-sans text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      );
    return <Fragment key={i}>{part}</Fragment>;
  });
}
