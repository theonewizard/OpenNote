import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, errorText, getJson, getNoteContent, putNoteContent } from "@/api/client";
import type { Conflict, NoteMeta } from "@/api/types";
import { Button } from "@/components/ui/button";
import { deleteNote, noteText, setConflictStatus } from "@/features/actions";
import { DiffView } from "@/features/DiffView";
import type { NoteRef } from "@/features/NoteEditor";

interface Props {
  conflict: Conflict;
  canEdit: boolean;
  /** Wraps a REST change: syncs first, refreshes the lists after */
  change: <T>(run: () => Promise<T>) => Promise<T>;
  onOpenNote: (note: NoteRef) => void;
  onResolved: () => void;
}

/** A note and its metadata from the server, or null when it no longer exists. */
async function loadNote(id: string): Promise<{ meta: NoteMeta; text: string } | null> {
  try {
    const meta = await getJson<NoteMeta>(`/api/v1/notes/${id}`);
    return { meta, text: await noteText(`/api/v1/notes/${id}/content`) };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** One conflict (roadmap P5-05): the note that stayed current against its conflict copy,
 * which holds the other edit. Resolving keeps one, or both; history keeps every version. */
export function ConflictView({ conflict, canEdit, change, onOpenNote, onResolved }: Props) {
  const current = useQuery({ queryKey: ["conflict-note", conflict.file_id], queryFn: () => loadNote(conflict.file_id) });
  const copy = useQuery({ queryKey: ["conflict-note", conflict.copy_file_id], queryFn: () => loadNote(conflict.copy_file_id) });
  const [message, setMessage] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (current.isPending || copy.isPending) return <p className="p-4">Loading…</p>;
  if (current.isError || copy.isError) return <p className="p-4">Could not load this conflict.</p>;

  async function resolve(step?: () => Promise<unknown>) {
    setMessage(undefined);
    setBusy(true);
    try {
      await change(async () => {
        await step?.();
        // The conflict's current revision for If-Match.
        await setConflictStatus(await getJson<Conflict>(`/api/v1/conflicts/${conflict.id}`), "resolved");
      });
      onResolved();
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  const fresh = (id: string) => getJson<NoteMeta>(`/api/v1/notes/${id}`);
  const resolved = conflict.status === "resolved";
  const both = current.data && copy.data;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-col gap-1 border-b px-4 py-2">
        <h1 className="font-semibold">Conflict{resolved && " (resolved)"}</h1>
        <p className="text-sm text-muted-foreground">
          Two devices changed the same note. The server kept one edit in the note and the
          other in a conflict copy; nothing was overwritten.
        </p>
      </div>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm">
        <dt className="text-muted-foreground">Note</dt>
        <dd className="flex min-w-0 items-center gap-2">
          <span className="truncate">{current.data?.meta.path ?? "deleted"}</span>
          {current.data && (
            <Button size="sm" variant="ghost" onClick={() => onOpenNote(current.data!.meta)}>
              Open
            </Button>
          )}
        </dd>
        <dt className="text-muted-foreground">Conflict copy</dt>
        <dd className="flex min-w-0 items-center gap-2">
          <span className="truncate">{copy.data?.meta.path ?? "deleted"}</span>
          {copy.data && (
            <Button size="sm" variant="ghost" onClick={() => onOpenNote(copy.data!.meta)}>
              Open
            </Button>
          )}
        </dd>
      </dl>
      {canEdit && !resolved && (
        <div role="toolbar" aria-label="Resolve conflict" className="flex flex-wrap gap-2 border-b px-4 py-2">
          {both && (
            <>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void resolve(async () => deleteNote(await fresh(conflict.copy_file_id)))}>
                Keep note, delete copy
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  void resolve(async () => {
                    const note = await fresh(conflict.file_id);
                    const bytes = new Uint8Array((await getNoteContent(conflict.copy_file_id)).bytes);
                    await putNoteContent(note.id, bytes, `"${note.revision}"`);
                    await deleteNote(await fresh(conflict.copy_file_id));
                  })
                }
              >
                Use copy in note
              </Button>
            </>
          )}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void resolve()}>
            {both ? "Keep both" : "Mark resolved"}
          </Button>
        </div>
      )}
      {message && (
        <p role="alert" className="border-b bg-muted px-4 py-2 text-sm">
          {message}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {both ? (
          <>
            <p className="px-4 pt-2 text-xs text-muted-foreground">Lines marked + are only in the copy, lines marked - only in the note.</p>
            <DiffView before={current.data!.text} after={copy.data!.text} label="Differences between note and copy" />
          </>
        ) : (
          <p className="p-4 text-sm">{current.data ? "The conflict copy" : "The note"} was deleted, so there is nothing left to compare.</p>
        )}
      </div>
    </div>
  );
}
