import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { getJson } from "@/api/client";
import type { Attachment, AttachmentPage, Conflict, ConflictPage, DeletedNotePage, NoteMeta, NotePage, SearchPage, Vault } from "@/api/types";
import { Button } from "@/components/ui/button";
import { folderOf, hasFlag, query, restoreNote, type Sort } from "@/features/actions";
import type { NoteRef } from "@/features/NoteEditor";
import { cn } from "@/lib/utils";
import type { SyncEngine } from "@/sync/engine";

export type ListView =
  | { kind: "folder"; folder?: string }
  | { kind: "tag"; tag: string }
  | { kind: "favorites" }
  | { kind: "archive" }
  | { kind: "trash" }
  | { kind: "conflicts" }
  | { kind: "search"; q: string };

/** The search query behind a view that lists search results. */
function searchQuery(view: ListView): string | undefined {
  if (view.kind === "favorites") return "is:favorite";
  if (view.kind === "archive") return "is:archived";
  if (view.kind === "search") return view.q;
  return undefined;
}

/** Notes cached on this device, for when the note list cannot be loaded (offline). */
async function cachedNotes(engine: SyncEngine, vaultId: string, folder: string | undefined): Promise<NoteRef[]> {
  return (await engine.files(vaultId))
    .filter((f) => f.kind === "note" && !f.deleted && f.local_hash)
    .filter((f) => folder === undefined || folderOf(f.path) === folder)
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((f) => ({
      id: f.file_id,
      path: f.path,
      title: f.path.split("/").at(-1)!.replace(/\.md$/, ""),
      revision: f.base_revision,
      content_hash: f.local_hash!,
      read_only: false,
    }));
}

/** Search snippets mark matches with « and » (backend search HEADLINE). */
function Snippet({ text }: { text: string }) {
  return (
    <span className="w-full text-xs text-muted-foreground">
      {text.split(/(«[^»]*»)/).map((part, i) =>
        part.startsWith("«") ? <mark key={i}>{part.slice(1, -1)}</mark> : part,
      )}
    </span>
  );
}

interface Props {
  vault: Vault;
  view: ListView;
  sort: Sort;
  engine: SyncEngine | undefined;
  selectedId: string | undefined;
  onOpen: (note: NoteRef) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  onOpenConflict: (conflict: Conflict) => void;
  /** Wraps a REST change: syncs first, refreshes the lists after */
  change: <T>(run: () => Promise<T>) => Promise<T>;
}

export function NoteList({ vault, view, sort, engine, selectedId, onOpen, onOpenAttachment, onOpenConflict, change }: Props) {
  const q = searchQuery(view);
  const folder = view.kind === "folder" ? view.folder : undefined;
  const tag = view.kind === "tag" ? view.tag : undefined;
  const listed = view.kind === "folder" || view.kind === "tag";

  const notes = useInfiniteQuery({
    queryKey: ["notes", vault.id, folder, tag, sort],
    queryFn: ({ pageParam }) =>
      getJson<NotePage>(`/api/v1/notes?${query({ vault_id: vault.id, folder, tag, sort, cursor: pageParam })}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: listed,
  });
  const offlineNotes = useQuery({
    queryKey: ["offline-notes", vault.id, folder],
    queryFn: () => cachedNotes(engine!, vault.id, folder),
    enabled: view.kind === "folder" && notes.isError && !!engine,
  });
  const search = useInfiniteQuery({
    queryKey: ["search", vault.id, q],
    queryFn: ({ pageParam }) =>
      getJson<SearchPage>(`/api/v1/search?${query({ q, vault_id: vault.id, cursor: pageParam })}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: q !== undefined,
  });
  const attachments = useQuery({
    queryKey: ["attachments", vault.id, folder],
    queryFn: () => getJson<AttachmentPage>(`/api/v1/attachments?${query({ vault_id: vault.id, folder })}`),
    enabled: folder !== undefined,
  });
  const trash = useQuery({
    queryKey: ["deleted", vault.id],
    queryFn: () => getJson<DeletedNotePage>(`/api/v1/vaults/${vault.id}/deleted-notes`),
    enabled: view.kind === "trash",
  });

  const conflicts = useQuery({
    queryKey: ["conflicts", vault.id, "open"],
    queryFn: () => getJson<ConflictPage>(`/api/v1/conflicts?${query({ vault_id: vault.id, limit: "200" })}`),
    enabled: view.kind === "conflicts",
  });
  // Paths from the device cache, so the list needs no request per conflict.
  const paths = useQuery({
    queryKey: ["file-paths", vault.id, conflicts.dataUpdatedAt],
    queryFn: async () => new Map((await engine!.files(vault.id)).map((f) => [f.file_id, f.path])),
    enabled: view.kind === "conflicts" && !!engine,
  });

  if (view.kind === "conflicts") {
    if (conflicts.isError) return <p className="p-4">Could not load conflicts.</p>;
    if (conflicts.data?.items.length === 0) return <p className="p-4 text-muted-foreground">No conflicts</p>;
    return (
      <ul>
        {conflicts.data?.items.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              aria-current={c.id === selectedId ? "true" : undefined}
              className={cn("flex w-full flex-col items-start border-b px-4 py-2 text-left hover:bg-muted", c.id === selectedId && "bg-muted")}
              onClick={() => onOpenConflict(c)}
            >
              <span className="w-full truncate font-medium">{paths.data?.get(c.file_id) ?? "Note"}</span>
              <span className="w-full truncate text-xs text-muted-foreground">
                Copy: {paths.data?.get(c.copy_file_id) ?? "deleted"} · {new Date(c.created_at).toLocaleString()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    );
  }

  if (view.kind === "trash") {
    if (trash.isError) return <p className="p-4">Could not load deleted notes.</p>;
    if (trash.data?.items.length === 0) return <p className="p-4 text-muted-foreground">Trash is empty</p>;
    return (
      <ul>
        {trash.data?.items.map((d) => (
          <li key={d.id} className="flex items-center gap-2 border-b px-4 py-2">
            <span className="min-w-0 flex-1 truncate">{d.path}</span>
            {vault.role !== "viewer" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void change(() => restoreNote(d.id, d.revision, d.last_content_revision)).catch(() => undefined)}
              >
                Restore
              </Button>
            )}
          </li>
        ))}
      </ul>
    );
  }

  const active = listed ? notes : search;
  // Archived notes only show in the Archive view (plan R-P3-002).
  const items: { note: NoteRef; snippet?: string | null }[] | undefined = listed
    ? (notes.data?.pages.flatMap((p) => p.items).filter((n) => !hasFlag(n, "archived")) ?? offlineNotes.data)?.map((note) => ({ note }))
    : search.data?.pages.flatMap((p) => p.items.map((hit) => ({ note: hit.note as NoteMeta, snippet: hit.snippet })));

  return (
    <>
      {active.isError && !offlineNotes.data?.length && (
        <p className="p-4">{view.kind === "search" ? "Search failed." : "Could not load notes."}</p>
      )}
      {items?.length === 0 && !attachments.data?.items.length && (
        <p className="p-4 text-muted-foreground">{q ? "Nothing found" : "No notes here"}</p>
      )}
      <ul>
        {items?.map(({ note, snippet }) => (
          <li key={note.id}>
            <button
              type="button"
              aria-current={note.id === selectedId ? "true" : undefined}
              className={cn(
                "flex w-full flex-col items-start border-b px-4 py-2 text-left hover:bg-muted",
                note.id === selectedId && "bg-muted",
              )}
              onClick={() => onOpen(note)}
            >
              <span className="w-full truncate font-medium">{note.title}</span>
              <span className="w-full truncate text-xs text-muted-foreground">{note.path}</span>
              {snippet && <Snippet text={snippet} />}
            </button>
          </li>
        ))}
      </ul>
      {active.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="m-2 self-center"
          disabled={active.isFetchingNextPage}
          onClick={() => void active.fetchNextPage()}
        >
          Load more
        </Button>
      )}
      {!!attachments.data?.items.length && (
        <>
          <h3 className="px-4 pt-3 pb-1 text-xs font-semibold text-muted-foreground uppercase">Attachments</h3>
          <ul aria-label="Attachments">
            {attachments.data.items.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  className="w-full truncate border-b px-4 py-2 text-left hover:bg-muted"
                  onClick={() => onOpenAttachment(a)}
                >
                  {a.path.split("/").at(-1)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
