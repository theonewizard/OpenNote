import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, getNoteContent, putNoteContent, type NoteContent } from "@/api/client";
import type { NoteMeta } from "@/api/types";
import { Button } from "@/components/ui/button";
import { decodeNote, encodeNote } from "@/editor/bytes";
import { MarkdownEditor } from "@/editor/MarkdownEditor";
import type { SaveState } from "@/features/saveState";

const AUTOSAVE_MS = 1500;

interface Props {
  note: NoteMeta;
  readOnly: boolean;
  onSaveState: (state: SaveState) => void;
}

export function NoteEditor({ note, readOnly, onSaveState }: Props) {
  const content = useQuery({
    queryKey: ["note-content", note.id],
    queryFn: () => getNoteContent(note.id),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  if (content.isPending) return <p className="p-4">Loading…</p>;
  if (content.isError) return <p className="p-4">Could not load this note.</p>;
  return (
    <LoadedNote
      key={`${note.id} ${content.dataUpdatedAt}`}
      note={note}
      content={content.data}
      readOnly={readOnly}
      onSaveState={onSaveState}
      onReload={() => void content.refetch()}
    />
  );
}

function LoadedNote({
  note,
  content,
  readOnly,
  onSaveState,
  onReload,
}: Props & { content: NoteContent; onReload: () => void }) {
  const decoded = useMemo(() => decodeNote(content.bytes), [content.bytes]);
  const editable = decoded.editable && !readOnly;
  const text = decoded.editable ? decoded.text : new TextDecoder().decode(content.bytes);

  const [state, setState] = useState<SaveState>(editable ? "saved" : "read-only");
  const current = useRef(text);
  const saved = useRef(text);
  const etag = useRef(content.etag);
  const saving = useRef(false);
  const conflict = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => onSaveState(state), [state, onSaveState]);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (state !== "unsaved" && state !== "saving" && state !== "conflict") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [state]);

  async function save() {
    clearTimeout(timer.current);
    if (!editable || saving.current || conflict.current) return;
    if (current.current === saved.current) return;
    const sending = current.current;
    saving.current = true;
    setState("saving");
    try {
      etag.current = await putNoteContent(note.id, encodeNote(sending), etag.current);
      saved.current = sending;
      setState(current.current === sending ? "saved" : "unsaved");
      saving.current = false;
      // Edits typed while this save was in flight get their own save.
      if (current.current !== sending) schedule();
    } catch (error) {
      saving.current = false;
      // A 412 means another client saved first: keep the edits here and never overwrite.
      // A failed save is retried by the next edit or the Save button, not in a loop.
      conflict.current = error instanceof ApiError && error.status === 412;
      setState(conflict.current ? "conflict" : "failed");
    }
  }

  function change(next: string) {
    current.current = next;
    if (conflict.current) return;
    setState(next === saved.current ? "saved" : "unsaved");
    schedule();
  }

  function schedule() {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(), AUTOSAVE_MS);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <h1 className="min-w-0 flex-1 truncate font-semibold">{note.title}</h1>
        {editable && (
          <Button size="sm" variant="outline" onClick={() => void save()} disabled={state !== "unsaved" && state !== "failed"}>
            Save
          </Button>
        )}
      </div>
      {!decoded.editable && (
        <p role="note" className="border-b bg-muted px-4 py-2 text-sm">
          This note is not UTF-8 text. It is shown read-only so its bytes are never changed.
        </p>
      )}
      {state === "conflict" && (
        <div role="alert" className="flex flex-wrap items-center gap-2 border-b bg-muted px-4 py-2 text-sm">
          This note was changed elsewhere. Your edits are still here and were not saved; copy
          them before reloading.
          <Button size="sm" variant="outline" onClick={onReload}>
            Reload note
          </Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <MarkdownEditor
          text={text}
          lineSeparator={decoded.editable ? decoded.lineSeparator : "\n"}
          readOnly={!editable}
          onChange={change}
          onSave={() => void save()}
        />
      </div>
    </div>
  );
}
