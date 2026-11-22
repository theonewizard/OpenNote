import { useMemo } from "react";

import { lineDiff } from "@/lib/diff";
import { cn } from "@/lib/utils";

const MARK = { same: " ", added: "+", removed: "-" } as const;

/** The lines of `after` against `before`: added lines marked +, removed lines marked -. */
export function DiffView({ before, after, label }: { before: string; after: string; label: string }) {
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  if (!lines) return <p className="p-4 text-sm">These versions differ in too many lines to compare here.</p>;
  if (before === after) return <p className="p-4 text-sm text-muted-foreground">No differences.</p>;
  return (
    <pre aria-label={label} className="overflow-auto p-2 font-mono text-xs leading-5">
      {lines.map((line, i) => (
        <div
          key={i}
          data-kind={line.kind}
          className={cn(
            "whitespace-pre-wrap",
            line.kind === "added" && "bg-green-500/15",
            line.kind === "removed" && "bg-red-500/15 line-through decoration-red-500/40",
          )}
        >
          <span aria-hidden className="inline-block w-4 select-none text-muted-foreground">
            {MARK[line.kind]}
          </span>
          {line.kind === "added" && <span className="sr-only">Added: </span>}
          {line.kind === "removed" && <span className="sr-only">Removed: </span>}
          {line.text}
        </div>
      ))}
    </pre>
  );
}
