import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { errorText, getJson } from "@/api/client";
import type { NoteMeta, NoteRevision, NoteRevisionPage } from "@/api/types";
import { Button } from "@/components/ui/button";
import { noteText, query, restoreNote } from "@/features/actions";
import { DiffView } from "@/features/DiffView";
import type { NoteRef } from "@/features/NoteEditor";
import { cn } from "@/lib/utils";

interface Props {
  note: NoteRef;
  canEdit: boolean;
  /** Wraps a REST change: syncs first, refreshes the lists after */
  change: <T>(run: () => Promise<T>) => Promise<T>;
  onRestored: (note: NoteMeta) => void;
  onClose: () => void;
}

const OPS = { create: "Created", update: "Edited", move: "Moved", delete: "Deleted", restore: "Restored" } as const;

const revisionText = (noteId: string, r: NoteRevision | undefined) =>
  !r || r.deleted ? Promise.resolve("") : noteText(`/api/v1/notes/${noteId}/revisions/${r.revision}/content`);

/** A note's revisions (roadmap P5-06), newest first: what each one changed, or how it
 * differs from the note now, and restore. Restoring adds a revision; none is lost. */
export function HistoryView({ note, canEdit, change, onRestored, onClose }: Props) {
  const revisions = useInfiniteQuery({
    queryKey: ["revisions", note.id],
    queryFn: ({ pageParam }) =>
      getJson<NoteRevisionPage>(`/api/v1/notes/${note.id}/revisions?${query({ cursor: pageParam })}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = revisions.data?.pages.flatMap((p) => p.items) ?? [];
  const [picked, setPicked] = useState<number>();
  const [against, setAgainst] = useState<"previous" | "current">("previous");
  const [message, setMessage] = useState<string>();

  const index = Math.max(0, items.findIndex((r) => r.revision === picked));
  const selected = items[index];
  const newest = items[0];
  // The revision before it with content; when it is not loaded yet the diff waits.
  const base = against === "current" ? newest : items.slice(index + 1).find((r) => !r.deleted);
  const texts = useQuery({
    queryKey: ["revision-diff", note.id, selected?.revision, base?.revision ?? 0],
    queryFn: async () => ({ before: await revisionText(note.id, base), after: await revisionText(note.id, selected) }),
    enabled: !!selected,
  });

  async function restore(r: NoteRevision) {
    setMessage(undefined);
    try {
      const restored = await change(async () => {
        const meta = await getJson<NoteMeta>(`/api/v1/notes/${note.id}`);
        return restoreNote(note.id, meta.revision, r.revision);
      });
      onRestored(restored);
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <h1 className="min-w-0 flex-1 truncate font-semibold">History of {note.title}</h1>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Back to note
        </Button>
      </div>
      {message && (
        <p role="alert" className="border-b bg-muted px-4 py-2 text-sm">
          {message}
        </p>
      )}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="max-h-60 overflow-auto border-b md:max-h-none md:w-64 md:shrink-0 md:border-r md:border-b-0">
          {revisions.isError && <p className="p-4">Could not load the history.</p>}
          <ul aria-label="Revisions">
            {items.map((r, i) => (
              <li key={r.revision}>
                <button
                  type="button"
                  aria-current={r === selected ? "true" : undefined}
                  className={cn("flex w-full flex-col border-b px-4 py-2 text-left hover:bg-muted", r === selected && "bg-muted")}
                  onClick={() => setPicked(r.revision)}
                >
                  <span className="text-sm font-medium">
                    {OPS[r.op]} · revision {r.revision}
                    {i === 0 && " (current)"}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(r.committed_at).toLocaleString()} · {r.device_id === "server-fs" ? "on the server" : r.device_id}
                  </span>
                  {r.op === "move" && <span className="truncate text-xs text-muted-foreground">{r.path}</span>}
                </button>
              </li>
            ))}
          </ul>
          {revisions.hasNextPage && (
            <Button variant="ghost" size="sm" className="m-2" disabled={revisions.isFetchingNextPage} onClick={() => void revisions.fetchNextPage()}>
              Load more
            </Button>
          )}
        </div>
        {selected && (
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-sm">
              <select
                aria-label="Compare with"
                className="rounded border bg-background px-1"
                value={against}
                onChange={(e) => setAgainst(e.target.value as "previous" | "current")}
              >
                <option value="previous">Changes in this revision</option>
                <option value="current">Compared with the current note</option>
              </select>
              {canEdit && selected !== newest && !selected.deleted && (
                <Button size="sm" variant="outline" onClick={() => void restore(selected)}>
                  Restore this revision
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {selected.deleted ? (
                <p className="p-4 text-sm">The note was deleted in this revision.</p>
              ) : texts.isError ? (
                <p className="p-4">Could not load this revision.</p>
              ) : texts.data ? (
                // Against the current note, + marks what restoring would bring back.
                <DiffView
                  before={texts.data.before}
                  after={texts.data.after}
                  label={against === "current" ? "Differences from the current note" : "Changes in this revision"}
                />
              ) : (
                <p className="p-4">Loading…</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
