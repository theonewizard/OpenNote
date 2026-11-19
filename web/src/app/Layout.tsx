import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, getJson } from "@/api/client";
import type { FolderList, NotePage, VaultPage } from "@/api/types";
import { Button } from "@/components/ui/button";
import { NoteEditor, type NoteRef } from "@/features/NoteEditor";
import { saveStateText, type SaveState } from "@/features/saveState";
import { cn } from "@/lib/utils";
import type { SyncEngine, SyncStatus } from "@/sync/engine";
import { useSyncEngine, useSyncStatus } from "@/sync/useSync";

// Below the md breakpoint one pane shows at a time; selecting moves to the next pane and
// the header's Back button returns (roadmap P3-10: usable at 375 px).
type Pane = "nav" | "list" | "note";

const query = (params: Record<string, string | undefined>) =>
  new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined));

function paneClass(pane: Pane, shown: Pane) {
  return cn("min-h-0 flex-col md:flex", pane === shown ? "flex" : "hidden");
}

/** The vault list, or the one cached on this device when the server cannot be reached. */
async function loadVaults(engine: SyncEngine | undefined): Promise<VaultPage> {
  try {
    const page = await getJson<VaultPage>("/api/v1/vaults");
    await engine?.remember("vaults", page);
    return page;
  } catch (error) {
    const cached = error instanceof ApiError ? undefined : await engine?.recall<VaultPage>("vaults");
    if (!cached) throw error;
    return cached;
  }
}

/** Notes cached on this device, for when the note list cannot be loaded (offline). */
async function cachedNotes(engine: SyncEngine, vaultId: string, folder: string | undefined): Promise<NoteRef[]> {
  return (await engine.files(vaultId))
    .filter((f) => f.kind === "note" && !f.deleted && f.local_hash)
    .filter((f) => folder === undefined || f.path.slice(0, Math.max(f.path.lastIndexOf("/"), 0)) === folder)
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

function syncText(sync: SyncStatus): string | undefined {
  if (sync.rejected) return `${sync.rejected} not synced: rejected by the server`;
  const offline = sync.state === "offline" ? " (offline)" : "";
  if (sync.unsynced) return `${sync.unsynced} ${sync.unsynced === 1 ? "change" : "changes"} not synced yet${offline}`;
  if (sync.state === "offline") return "Offline";
  if (sync.state === "error") return "Sync failed, retrying";
  return undefined;
}

export function Layout() {
  const [pane, setPane] = useState<Pane>("nav");
  const [vaultId, setVaultId] = useState<string>();
  const [folder, setFolder] = useState<string>();
  const [note, setNote] = useState<NoteRef>();
  const [saveState, setSaveState] = useState<SaveState>();

  const engine = useSyncEngine();
  const vaults = useQuery({
    queryKey: ["vaults"],
    queryFn: () => loadVaults(engine.data),
    enabled: !engine.isPending,
  });
  const vault = vaults.data?.items.find((v) => v.id === vaultId) ?? vaults.data?.items[0];
  const sync = useSyncStatus(engine.data, vault?.id);
  useEffect(() => {
    if (!engine.data || !vault) return;
    engine.data.start(vault.id);
    return () => engine.data.stop();
  }, [engine.data, vault]);

  const folders = useQuery({
    queryKey: ["folders", vault?.id],
    queryFn: () => getJson<FolderList>(`/api/v1/folders?${query({ vault_id: vault!.id })}`),
    enabled: !!vault,
  });
  const notes = useInfiniteQuery({
    queryKey: ["notes", vault?.id, folder],
    queryFn: ({ pageParam }) =>
      getJson<NotePage>(`/api/v1/notes?${query({ vault_id: vault!.id, folder, cursor: pageParam })}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: !!vault,
  });
  const offlineNotes = useQuery({
    queryKey: ["offline-notes", vault?.id, folder],
    queryFn: () => cachedNotes(engine.data!, vault!.id, folder),
    enabled: notes.isError && !!engine.data && !!vault,
  });
  const noteItems: NoteRef[] | undefined = notes.data?.pages.flatMap((page) => page.items) ?? offlineNotes.data;

  function openFolder(path: string | undefined) {
    setFolder(path);
    setPane("list");
  }

  let status = "Connecting…";
  if (vaults.isError) status = "Not connected";
  else if (note && saveState && saveState !== "saved") status = saveStateText[saveState];
  else if (syncText(sync)) status = syncText(sync)!;
  else if (note && saveState) status = saveStateText[saveState];
  else if (vaults.isSuccess) status = "Connected";

  return (
    <div className="flex h-svh flex-col">
      <header className="flex items-center gap-2 border-b px-4 py-2">
        {pane !== "nav" && (
          <Button
            variant="ghost"
            size="sm"
            className="md:hidden"
            onClick={() => setPane(pane === "note" ? "list" : "nav")}
          >
            Back
          </Button>
        )}
        <span className="font-semibold">OpenNote</span>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Vaults and folders"
          className={cn(paneClass("nav", pane), "gap-2 overflow-auto p-4 md:w-60 md:shrink-0 md:border-r")}
        >
          {vaults.data && vaults.data.items.length > 1 && (
            <select
              aria-label="Vault"
              className="rounded border bg-background px-2 py-1"
              value={vault?.id}
              onChange={(e) => {
                setVaultId(e.target.value);
                setFolder(undefined);
              }}
            >
              {vaults.data.items.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          )}
          {vault && <h2 className="font-semibold">{vault.name}</h2>}
          <Button variant="outline" size="sm" disabled className="self-start">
            New note
          </Button>
          <ul className="flex flex-col">
            {vault && (
              <li>
                <FolderButton label="All notes" depth={0} active={folder === undefined} onClick={() => openFolder(undefined)} />
              </li>
            )}
            {folders.data?.items.map((f) => (
              <li key={f.path}>
                <FolderButton
                  label={f.name}
                  depth={f.path.split("/").length}
                  active={folder === f.path}
                  onClick={() => openFolder(f.path)}
                />
              </li>
            ))}
          </ul>
        </nav>
        <section
          aria-label="Note list"
          className={cn(paneClass("list", pane), "overflow-auto md:w-80 md:shrink-0 md:border-r")}
        >
          {notes.isError && !offlineNotes.data?.length && <p className="p-4">Could not load notes.</p>}
          {noteItems?.length === 0 && <p className="p-4 text-muted-foreground">No notes here</p>}
          <ul>
            {noteItems?.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  aria-current={n.id === note?.id ? "true" : undefined}
                  className={cn(
                    "flex w-full flex-col items-start border-b px-4 py-2 text-left hover:bg-muted",
                    n.id === note?.id && "bg-muted",
                  )}
                  onClick={() => {
                    setNote(n);
                    setPane("note");
                  }}
                >
                  <span className="w-full truncate font-medium">{n.title}</span>
                  <span className="w-full truncate text-xs text-muted-foreground">{n.path}</span>
                </button>
              </li>
            ))}
          </ul>
          {notes.hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="m-2 self-center"
              disabled={notes.isFetchingNextPage}
              onClick={() => void notes.fetchNextPage()}
            >
              Load more
            </Button>
          )}
        </section>
        <main className={cn(paneClass("note", pane), "min-w-0 flex-1")}>
          {engine.isError && <p className="p-4">This browser cannot keep notes on this device, so they cannot be edited.</p>}
          {note && vault && engine.data ? (
            <NoteEditor
              key={note.id}
              note={note}
              vaultId={vault.id}
              engine={engine.data}
              readOnly={note.read_only || vault.role === "viewer"}
              onSaveState={setSaveState}
            />
          ) : (
            <p className="p-4">No note selected</p>
          )}
        </main>
      </div>
      <footer className="border-t px-4 py-1 text-sm">{status}</footer>
    </div>
  );
}

function FolderButton(props: { label: string; depth: number; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-current={props.active ? "true" : undefined}
      className={cn("w-full truncate rounded px-2 py-1 text-left hover:bg-muted", props.active && "bg-muted")}
      style={{ paddingLeft: `${0.5 + props.depth * 0.75}rem` }}
      onClick={props.onClick}
    >
      {props.label}
    </button>
  );
}
