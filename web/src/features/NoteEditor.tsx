import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import type { NoteMeta } from "@/api/types";
import { Button } from "@/components/ui/button";
import { decodeNote, encodeNote } from "@/editor/bytes";
import { MarkdownEditor } from "@/editor/MarkdownEditor";
import type { SaveState } from "@/features/saveState";
import { StaleEdit, type Content, type SyncEngine } from "@/sync/engine";

// Edits are stored on this device (IndexedDB) and synced from there (roadmap P5-04).
const AUTOSAVE_MS = 500;

export type NoteRef = Pick<NoteMeta, "id" | "path" | "title" | "revision" | "content_hash" | "read_only">;

interface Props {
  note: NoteRef;
  vaultId: string;
  engine: SyncEngine;
  readOnly: boolean;
  onSaveState: (state: SaveState) => void;
}

export function NoteEditor({ note, vaultId, engine, readOnly, onSaveState }: Props) {
  const content = useQuery({
    queryKey: ["note-content", vaultId, note.id],
    queryFn: () => engine.read(vaultId, note.id, note),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const file = useQuery({
    queryKey: ["note-file", vaultId, note.id],
    queryFn: async () => (await engine.file(vaultId, note.id)) ?? null,
    gcTime: 0,
  });
  const refetchFile = file.refetch;
  useEffect(
    () => engine.subscribe((vault, ids) => vault === vaultId && ids.includes(note.id) && void refetchFile()),
    [engine, vaultId, note.id, refetchFile],
  );
  if (content.isPending) return <p className="p-4">Loading…</p>;
  if (content.isError) return <p className="p-4">Could not load this note.</p>;
  if (content.data === null) return <p className="p-4">This note was deleted.</p>;
  const record = file.data;
  return (
    <>
      {record?.rejected && (
        <div role="alert" className="flex flex-wrap items-center gap-2 border-b bg-muted px-4 py-2 text-sm">
          Not synced: {record.rejected.title}. Your edit stays on this device until you change
          the note again or discard the edit.
          <Button
            size="sm"
            variant="outline"
            onClick={() => void engine.discard(vaultId, note.id).then(() => content.refetch())}
          >
            Discard edit
          </Button>
        </div>
      )}
      {record?.notice && (
        <p role="status" className="border-b bg-muted px-4 py-2 text-sm">
          {record.notice}
        </p>
      )}
      <LoadedNote
        key={`${note.id} ${content.dataUpdatedAt}`}
        note={note}
        vaultId={vaultId}
        engine={engine}
        content={content.data}
        readOnly={readOnly}
        onSaveState={onSaveState}
        onReload={() => void content.refetch()}
      />
    </>
  );
}

function LoadedNote({
  note,
  vaultId,
  engine,
  content,
  readOnly,
  onSaveState,
  onReload,
}: Props & { content: Content; onReload: () => void }) {
  const decoded = useMemo(() => decodeNote(content.bytes), [content.bytes]);
  const editable = decoded.editable && !readOnly;
  const text = decoded.editable ? decoded.text : new TextDecoder().decode(content.bytes);

  const [state, setState] = useState<SaveState>(editable ? "saved" : "read-only");
  const current = useRef(text);
  const saved = useRef(text);
  const hash = useRef(content.hash);
  const saving = useRef(false);
  const conflict = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => onSaveState(state), [state, onSaveState]);
  // Sync replaced the bytes: show them, unless edits typed here are not stored yet (their
  // save is then pushed against the revision they were made on, and the server merges).
  useEffect(
    () =>
      engine.subscribe((vault, ids) => {
        if (vault !== vaultId || !ids.includes(note.id)) return;
        void engine.file(vaultId, note.id).then((f) => {
          const idle = !saving.current && current.current === saved.current;
          if (idle && f?.local_hash !== hash.current) onReload();
        });
      }),
    [engine, vaultId, note.id, onReload],
  );
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (state !== "unsaved" && state !== "saving" && state !== "conflict") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [state]);

  async function save(explicit = false) {
    clearTimeout(timer.current);
    if (!editable || saving.current || conflict.current) return;
    if (current.current === saved.current) return;
    const sending = current.current;
    saving.current = true;
    setState("saving");
    try {
      hash.current = await engine.edit(vaultId, note.id, encodeNote(sending), hash.current, explicit);
      saved.current = sending;
      setState(current.current === sending ? "saved" : "unsaved");
      saving.current = false;
      // Edits typed while this save was in flight get their own save.
      if (current.current !== sending) schedule();
    } catch (error) {
      saving.current = false;
      // The bytes changed under the edit in a way sync cannot place: keep the edits here and
      // never overwrite. A failed save is retried by the next edit or the Save button.
      conflict.current = error instanceof StaleEdit;
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
          <Button size="sm" variant="outline" onClick={() => void save(true)} disabled={state !== "unsaved" && state !== "failed"}>
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
          onSave={() => void save(true)}
        />
      </div>
    </div>
  );
}
