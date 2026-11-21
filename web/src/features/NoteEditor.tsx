import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorText, getJson } from "@/api/client";
import type { Attachment, AttachmentPage, NoteLinks, NoteMeta } from "@/api/types";
import { Button } from "@/components/ui/button";
import { FormDialog, TextField } from "@/components/ui/form-dialog";
import { decodeNote, encodeNote } from "@/editor/bytes";
import { MarkdownEditor } from "@/editor/MarkdownEditor";
import {
  attachmentUrl,
  createNote,
  deleteNote,
  folderOf,
  hasFlag,
  join,
  renameNote,
  resolveAttachment,
  safeFileName,
  setFlag,
  setTags,
  uploadAttachment,
  withoutMd,
} from "@/features/actions";
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

interface EditorProps extends Props {
  /** Wraps a REST change: syncs first, refreshes the lists after */
  change: <T>(run: () => Promise<T>) => Promise<T>;
  onOpenNote: (note: NoteRef) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  /** The note was renamed (new metadata) or deleted (null) here */
  onMoved: (note: NoteMeta | null) => void;
}

const MAX_ATTACHMENT_PAGES = 10;

/** The vault's attachments, for resolving embeds (first 10 pages). */
async function vaultAttachments(vaultId: string): Promise<Attachment[]> {
  const all: Attachment[] = [];
  let cursor: string | null | undefined;
  for (let i = 0; i < MAX_ATTACHMENT_PAGES && cursor !== null; i++) {
    const params = new URLSearchParams({ vault_id: vaultId, limit: "200", ...(cursor ? { cursor } : {}) });
    const page = await getJson<AttachmentPage>(`/api/v1/attachments?${params}`);
    all.push(...page.items);
    cursor = page.next_cursor;
  }
  return all;
}

export function NoteEditor(props: EditorProps) {
  const { note, vaultId, engine, readOnly, onSaveState, change, onOpenNote, onOpenAttachment } = props;
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
  // Unavailable offline: the note's actions are then disabled.
  const meta = useQuery({
    queryKey: ["note-meta", note.id],
    queryFn: () => getJson<NoteMeta>(`/api/v1/notes/${note.id}`),
    retry: false,
  });
  const attachments = useQuery({ queryKey: ["vault-attachments", vaultId], queryFn: () => vaultAttachments(vaultId) });
  const insertRef = useRef<(text: string) => void>(undefined);
  const [message, setMessage] = useState<string>();

  const refetchFile = file.refetch;
  const refetchMeta = meta.refetch;
  useEffect(
    () =>
      engine.subscribe((vault, ids) => {
        if (vault !== vaultId || !ids.includes(note.id)) return;
        void refetchFile();
        void refetchMeta();
      }),
    [engine, vaultId, note.id, refetchFile, refetchMeta],
  );

  const attachmentList = attachments.data;
  const imageUrl = useMemo(
    () =>
      attachmentList &&
      ((target: string) => {
        const found = resolveAttachment(attachmentList, target, note.path);
        return found?.media_type.startsWith("image/") ? attachmentUrl(found.id) : undefined;
      }),
    [attachmentList, note.path],
  );

  const openLink = useCallback(
    async (target: string, embed: boolean) => {
      setMessage(undefined);
      try {
        const isNote = !embed && !/\.[^/.]+$/.test(target.replace(/\.md$/i, ""));
        if (!isNote) {
          const found = resolveAttachment(attachmentList ?? [], target, note.path);
          if (found) return onOpenAttachment(found);
          return setMessage(`No attachment named ${target}`);
        }
        const links = await getJson<NoteLinks>(`/api/v1/notes/${note.id}/links`);
        const resolved = links.outgoing.find((l) => l.target === target && l.resolved)?.resolved;
        // An unresolved link creates its note, as in Obsidian.
        const opened = resolved
          ? await getJson<NoteMeta>(`/api/v1/notes/${resolved.id}`)
          : await change(() => createNote(vaultId, target));
        onOpenNote(opened);
      } catch (error) {
        setMessage(errorText(error));
      }
    },
    [attachmentList, note.id, note.path, vaultId, change, onOpenNote, onOpenAttachment],
  );

  if (content.isPending) return <p className="p-4">Loading…</p>;
  if (content.isError) return <p className="p-4">Could not load this note.</p>;
  if (content.data === null) return <p className="p-4">This note was deleted.</p>;
  const record = file.data;
  return (
    <>
      <NoteActions
        {...props}
        meta={meta.data}
        editable={!readOnly && !!meta.data && !meta.data.read_only}
        insert={(text) => insertRef.current?.(text)}
        onMessage={setMessage}
      />
      {message && (
        <p role="status" className="border-b bg-muted px-4 py-2 text-sm">
          {message}
        </p>
      )}
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
        onOpenLink={(target, embed) => void openLink(target, embed)}
        imageUrl={imageUrl}
        insertRef={insertRef}
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
  onOpenLink,
  imageUrl,
  insertRef,
}: Props & {
  content: Content;
  onReload: () => void;
  onOpenLink: (target: string, embed: boolean) => void;
  imageUrl: ((target: string) => string | undefined) | undefined;
  insertRef: { current?: (text: string) => void };
}) {
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
          onOpenLink={onOpenLink}
          imageUrl={imageUrl}
          insertRef={insertRef}
        />
      </div>
    </div>
  );
}

type Dialog = "rename" | "delete" | "tags" | undefined;

/** Favorite, archive, tags, attach, rename and delete: REST changes that need the server. */
function NoteActions({
  note,
  vaultId,
  meta,
  editable,
  change,
  insert,
  onMoved,
  onMessage,
}: EditorProps & {
  meta: NoteMeta | undefined;
  editable: boolean;
  insert: (text: string) => void;
  onMessage: (text: string | undefined) => void;
}) {
  const [dialog, setDialog] = useState<Dialog>();
  const [path, setPath] = useState("");
  const [updateLinks, setUpdateLinks] = useState(true);
  const [tags, setTagsText] = useState("");
  const file = useRef<HTMLInputElement>(null);

  // Read after change() has synced: pushing an edit raises the revision If-Match needs.
  const current = () => getJson<NoteMeta>(`/api/v1/notes/${note.id}`);

  async function run(action: () => Promise<unknown>) {
    onMessage(undefined);
    try {
      await change(action);
    } catch (error) {
      onMessage(errorText(error));
    }
  }

  async function attach(files: FileList | null) {
    const picked = files?.[0];
    if (!picked) return;
    const name = safeFileName(picked.name);
    await run(async () => {
      await uploadAttachment(vaultId, join(folderOf(note.path), name), picked);
      insert(`![[${name}]]`);
    });
    if (file.current) file.current.value = "";
  }

  const favorite = !!meta && hasFlag(meta, "favorite");
  const archived = !!meta && hasFlag(meta, "archived");
  return (
    <div role="toolbar" aria-label="Note actions" className="flex flex-wrap items-center gap-1 border-b px-2 py-1">
      <Button size="sm" variant="ghost" aria-pressed={favorite} disabled={!editable} onClick={() => void run(async () => setFlag(await current(), "favorite", !favorite))}>
        {favorite ? "★ Favorite" : "☆ Favorite"}
      </Button>
      <Button size="sm" variant="ghost" aria-pressed={archived} disabled={!editable} onClick={() => void run(async () => setFlag(await current(), "archived", !archived))}>
        {archived ? "Unarchive" : "Archive"}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={!editable}
        onClick={() => {
          setTagsText(meta!.tags.join(", "));
          setDialog("tags");
        }}
      >
        Tags
      </Button>
      <Button size="sm" variant="ghost" disabled={!editable} onClick={() => file.current?.click()}>
        Attach
      </Button>
      <input ref={file} type="file" hidden aria-label="Attachment file" onChange={(e) => void attach(e.target.files)} />
      <Button
        size="sm"
        variant="ghost"
        disabled={!editable}
        onClick={() => {
          setPath(withoutMd(meta!.path));
          setDialog("rename");
        }}
      >
        Rename
      </Button>
      <Button size="sm" variant="ghost" disabled={!editable} onClick={() => setDialog("delete")}>
        Delete
      </Button>
      {meta && meta.tags.length > 0 && (
        <ul aria-label="Tags" className="flex flex-wrap gap-1 px-2 text-xs">
          {meta.tags.map((t) => (
            <li key={t} className="rounded bg-muted px-1.5 py-0.5">
              #{t}
            </li>
          ))}
        </ul>
      )}
      <FormDialog
        title="Rename or move note"
        open={dialog === "rename"}
        onOpenChange={(open) => setDialog(open ? "rename" : undefined)}
        submitLabel="Rename"
        onSubmit={async () => onMoved((await change(async () => renameNote(await current(), path, updateLinks))).note)}
      >
        <TextField label="Path in the vault" value={path} onChange={setPath} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={updateLinks} onChange={(e) => setUpdateLinks(e.target.checked)} />
          Update links in other notes
        </label>
      </FormDialog>
      <FormDialog
        title={`Delete ${note.title}?`}
        open={dialog === "delete"}
        onOpenChange={(open) => setDialog(open ? "delete" : undefined)}
        submitLabel="Delete"
        destructive
        onSubmit={async () => {
          await change(async () => deleteNote(await current()));
          onMoved(null);
        }}
      >
        <p className="text-sm">It moves to the Trash, where it can be restored.</p>
      </FormDialog>
      <FormDialog
        title="Tags"
        open={dialog === "tags"}
        onOpenChange={(open) => setDialog(open ? "tags" : undefined)}
        submitLabel="Save tags"
        onSubmit={() =>
          change(async () =>
            setTags(
              await current(),
              tags
                .split(/[,\s]+/)
                .map((t) => t.replace(/^#/, ""))
                .filter(Boolean),
            ),
          )
        }
      >
        <label className="flex flex-col gap-1 text-sm">
          Tags, separated by commas or spaces
          <input className="rounded border bg-background px-2 py-1 text-base" autoFocus value={tags} onChange={(e) => setTagsText(e.target.value)} />
        </label>
      </FormDialog>
    </div>
  );
}
