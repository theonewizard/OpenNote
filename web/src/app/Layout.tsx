import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { ApiError, getJson } from "@/api/client";
import type { Attachment, FolderList, TagPage, User, VaultPage } from "@/api/types";
import { SESSION_KEY } from "@/app/session";
import { Button } from "@/components/ui/button";
import { FormDialog, TextField } from "@/components/ui/form-dialog";
import { SORTS, createFolder, createNote, deleteFolder, folderOf, join, moveFolder, query, type Sort } from "@/features/actions";
import { AttachmentView } from "@/features/AttachmentView";
import { NoteEditor, type NoteRef } from "@/features/NoteEditor";
import { NoteList, type ListView } from "@/features/NoteList";
import { saveStateText, type SaveState } from "@/features/saveState";
import { SearchBox } from "@/features/SearchBox";
import { Settings } from "@/features/Settings";
import { cn } from "@/lib/utils";
import type { SyncEngine, SyncStatus } from "@/sync/engine";
import { signOut, useSyncEngine, useSyncStatus } from "@/sync/useSync";

// Below the md breakpoint one pane shows at a time; selecting moves to the next pane and
// the header's Back button returns (roadmap P3-10: usable at 375 px).
type Pane = "nav" | "list" | "note";
type Main = { kind: "note"; note: NoteRef } | { kind: "attachment"; attachment: Attachment } | { kind: "settings" };
type Dialog = "new-note" | "new-folder" | "rename-folder" | "delete-folder";

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

function syncText(sync: SyncStatus): string | undefined {
  if (sync.rejected) return `${sync.rejected} not synced: rejected by the server`;
  const offline = sync.state === "offline" ? " (offline)" : "";
  if (sync.unsynced) return `${sync.unsynced} ${sync.unsynced === 1 ? "change" : "changes"} not synced yet${offline}`;
  if (sync.state === "offline") return "Offline";
  if (sync.state === "error") return "Sync failed, retrying";
  return undefined;
}

function viewTitle(view: ListView): string {
  switch (view.kind) {
    case "folder":
      return view.folder?.split("/").at(-1) ?? "All notes";
    case "tag":
      return `#${view.tag}`;
    case "favorites":
      return "Favorites";
    case "archive":
      return "Archive";
    case "trash":
      return "Trash";
    case "search":
      return `Search: ${view.q}`;
  }
}

const sameView = (a: ListView, b: ListView) => JSON.stringify(a) === JSON.stringify(b);

/** `user` is undefined when the app started offline with a remembered user's cache. */
export function Layout({ user }: { user?: User }) {
  const client = useQueryClient();
  const [pane, setPane] = useState<Pane>("nav");
  const [vaultId, setVaultId] = useState<string>();
  const [view, setView] = useState<ListView>({ kind: "folder" });
  const [sort, setSort] = useState<Sort>("path");
  const [main, setMain] = useState<Main>();
  const [saveState, setSaveState] = useState<SaveState>();
  const [dialog, setDialog] = useState<Dialog>();
  const [name, setName] = useState("");

  const engine = useSyncEngine();
  const vaults = useQuery({
    queryKey: ["vaults"],
    queryFn: () => loadVaults(engine.data),
    enabled: !engine.isPending,
  });
  const vault = vaults.data?.items.find((v) => v.id === vaultId) ?? vaults.data?.items[0];
  const canEdit = !!vault && vault.role !== "viewer";
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
  const tags = useQuery({
    queryKey: ["tags", vault?.id],
    queryFn: () => getJson<TagPage>(`/api/v1/tags?${query({ vault_id: vault!.id, limit: "200" })}`),
    enabled: !!vault,
  });

  // REST changes (plan R-P3-001): edits not synced yet go first, so the change applies to
  // the newest text; afterwards the lists are read again and the device cache pulls.
  const change = useCallback(
    async <T,>(run: () => Promise<T>): Promise<T> => {
      if (engine.data && vault) await engine.data.sync(vault.id).catch(() => undefined);
      try {
        return await run();
      } finally {
        const keep = new Set(["session", "sync-engine", "note-content", "meta"]);
        await client.invalidateQueries({ predicate: (q) => !keep.has(String(q.queryKey[0])) });
        if (engine.data && vault) void engine.data.sync(vault.id).catch(() => undefined);
      }
    },
    [client, engine.data, vault],
  );

  function show(next: ListView) {
    setView(next);
    setPane("list");
  }
  const openNote = useCallback((note: NoteRef) => {
    setMain({ kind: "note", note });
    setPane("note");
  }, []);
  const openAttachment = useCallback((attachment: Attachment) => {
    setMain({ kind: "attachment", attachment });
    setPane("note");
  }, []);

  const folder = view.kind === "folder" ? view.folder : undefined;
  const note = main?.kind === "note" ? main.note : undefined;

  let status = "Connecting…";
  if (vaults.isError) status = "Not connected";
  else if (note && saveState && saveState !== "saved") status = saveStateText[saveState];
  else if (syncText(sync)) status = syncText(sync)!;
  else if (note && saveState) status = saveStateText[saveState];
  else if (vaults.isSuccess) status = "Connected";

  const navItem = (label: string, target: ListView, depth = 0) => (
    <FolderButton label={label} depth={depth} active={sameView(view, target)} onClick={() => show(target)} />
  );

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
        {vault ? <SearchBox onSearch={(q) => show({ kind: "search", q })} /> : <span className="flex-1" />}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setMain({ kind: "settings" });
            setPane("note");
          }}
        >
          Settings
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            void signOut(engine.data).then(() => {
              client.setQueryData(SESSION_KEY, null);
              client.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
            })
          }
        >
          Sign out
        </Button>
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
                setView({ kind: "folder" });
                setMain(undefined);
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
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!canEdit}
              onClick={() => {
                setName("");
                setDialog("new-note");
              }}
            >
              New note
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!canEdit}
              onClick={() => {
                setName("");
                setDialog("new-folder");
              }}
            >
              New folder
            </Button>
          </div>
          {vault && (
            <ul className="flex flex-col">
              <li>{navItem("All notes", { kind: "folder" })}</li>
              <li>{navItem("Favorites", { kind: "favorites" })}</li>
              <li>{navItem("Archive", { kind: "archive" })}</li>
              <li>{navItem("Trash", { kind: "trash" })}</li>
            </ul>
          )}
          {!!folders.data?.items.length && (
            <>
              <h3 className="pt-2 text-xs font-semibold text-muted-foreground uppercase">Folders</h3>
              <ul className="flex flex-col">
                {folders.data.items.map((f) => (
                  <li key={f.path}>{navItem(f.name, { kind: "folder", folder: f.path }, f.path.split("/").length)}</li>
                ))}
              </ul>
            </>
          )}
          {!!tags.data?.items.length && (
            <>
              <h3 className="pt-2 text-xs font-semibold text-muted-foreground uppercase">Tags</h3>
              <ul aria-label="Tags" className="flex flex-col">
                {tags.data.items.map((t) => (
                  <li key={t.name}>
                    <FolderButton
                      label={`#${t.name}`}
                      count={t.count}
                      depth={0}
                      active={sameView(view, { kind: "tag", tag: t.name })}
                      onClick={() => show({ kind: "tag", tag: t.name })}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </nav>
        <section
          aria-label="Note list"
          className={cn(paneClass("list", pane), "overflow-auto md:w-80 md:shrink-0 md:border-r")}
        >
          {vault && (
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
              <h2 className="min-w-0 basis-full truncate font-semibold">{viewTitle(view)}</h2>
              {(view.kind === "folder" || view.kind === "tag") && (
                <select
                  aria-label="Sort"
                  className="rounded border bg-background px-1 text-sm"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as Sort)}
                >
                  {Object.entries(SORTS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              )}
              {folder !== undefined && canEdit && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setName(folder);
                      setDialog("rename-folder");
                    }}
                  >
                    Rename
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDialog("delete-folder")}>
                    Delete
                  </Button>
                </>
              )}
            </div>
          )}
          {vault && (
            <NoteList
              vault={vault}
              view={view}
              sort={sort}
              engine={engine.data}
              selectedId={note?.id}
              onOpen={openNote}
              onOpenAttachment={openAttachment}
              change={change}
            />
          )}
        </section>
        <main className={cn(paneClass("note", pane), "min-w-0 flex-1")}>
          {engine.isError && main?.kind !== "settings" && (
            <p className="p-4">This browser cannot keep notes on this device, so they cannot be edited.</p>
          )}
          {main?.kind === "settings" ? (
            <Settings user={user} vault={vault} onVaultCreated={(v) => setVaultId(v.id)} />
          ) : main?.kind === "attachment" && vault ? (
            <AttachmentView
              key={main.attachment.id}
              attachment={main.attachment}
              canEdit={canEdit}
              change={change}
              onDeleted={() => setMain(undefined)}
            />
          ) : note && vault && engine.data ? (
            <NoteEditor
              key={note.id}
              note={note}
              vaultId={vault.id}
              engine={engine.data}
              readOnly={note.read_only || vault.role === "viewer"}
              onSaveState={setSaveState}
              change={change}
              onOpenNote={openNote}
              onOpenAttachment={openAttachment}
              onMoved={(moved) => setMain(moved ? { kind: "note", note: moved } : undefined)}
            />
          ) : (
            <p className="p-4">No note selected</p>
          )}
        </main>
      </div>
      <footer className="border-t px-4 py-1 text-sm">{status}</footer>
      {vault && (
        <>
          <FormDialog
            title={folder ? `New note in ${folder}` : "New note"}
            open={dialog === "new-note"}
            onOpenChange={(open) => setDialog(open ? "new-note" : undefined)}
            submitLabel="Create"
            onSubmit={async () => openNote(await change(() => createNote(vault.id, join(folder, name))))}
          >
            <TextField label="Name" value={name} onChange={setName} placeholder="Meeting notes" />
          </FormDialog>
          <FormDialog
            title={folder ? `New folder in ${folder}` : "New folder"}
            open={dialog === "new-folder"}
            onOpenChange={(open) => setDialog(open ? "new-folder" : undefined)}
            submitLabel="Create"
            onSubmit={async () => {
              const path = join(folder, name);
              await change(() => createFolder(vault.id, path));
              show({ kind: "folder", folder: path });
            }}
          >
            <TextField label="Name" value={name} onChange={setName} />
          </FormDialog>
          <FormDialog
            title="Rename or move folder"
            open={dialog === "rename-folder"}
            onOpenChange={(open) => setDialog(open ? "rename-folder" : undefined)}
            submitLabel="Rename"
            onSubmit={async () => {
              await change(() => moveFolder(vault.id, folder!, name));
              setView({ kind: "folder", folder: name });
              if (note && `${folderOf(note.path)}/`.startsWith(`${folder}/`)) setMain(undefined);
            }}
          >
            <TextField label="Path in the vault" value={name} onChange={setName} />
          </FormDialog>
          <FormDialog
            title={`Delete folder ${folder}?`}
            open={dialog === "delete-folder"}
            onOpenChange={(open) => setDialog(open ? "delete-folder" : undefined)}
            submitLabel="Delete"
            destructive
            onSubmit={async () => {
              await change(() => deleteFolder(vault.id, folder!));
              setView({ kind: "folder" });
            }}
          >
            <p className="text-sm">Only an empty folder can be deleted.</p>
          </FormDialog>
        </>
      )}
    </div>
  );
}

function FolderButton(props: { label: string; depth: number; active: boolean; count?: number; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-current={props.active ? "true" : undefined}
      className={cn("flex w-full gap-2 truncate rounded px-2 py-1 text-left hover:bg-muted", props.active && "bg-muted")}
      style={{ paddingLeft: `${0.5 + props.depth * 0.75}rem` }}
      onClick={props.onClick}
    >
      <span className="min-w-0 flex-1 truncate">{props.label}</span>
      {props.count !== undefined && <span className="text-xs text-muted-foreground">{props.count}</span>}
    </button>
  );
}
