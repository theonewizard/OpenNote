import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getJson } from "@/api/client";
import type { Folder, NoteMeta, Page, Vault } from "@/api/types";
import { Button } from "@/components/ui/button";
import { NoteEditor } from "@/features/NoteEditor";
import { saveStateText, type SaveState } from "@/features/saveState";
import { cn } from "@/lib/utils";

// Below the md breakpoint one pane shows at a time; selecting moves to the next pane and
// the header's Back button returns (roadmap P3-10: usable at 375 px).
type Pane = "nav" | "list" | "note";

const query = (params: Record<string, string | undefined>) =>
  new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined));

function paneClass(pane: Pane, shown: Pane) {
  return cn("min-h-0 flex-col md:flex", pane === shown ? "flex" : "hidden");
}

export function Layout() {
  const [pane, setPane] = useState<Pane>("nav");
  const [vaultId, setVaultId] = useState<string>();
  const [folder, setFolder] = useState<string>();
  const [note, setNote] = useState<NoteMeta>();
  const [saveState, setSaveState] = useState<SaveState>();

  const vaults = useQuery({
    queryKey: ["vaults"],
    queryFn: () => getJson<Page<Vault>>("/api/v1/vaults"),
  });
  const vault = vaults.data?.items.find((v) => v.id === vaultId) ?? vaults.data?.items[0];

  const folders = useQuery({
    queryKey: ["folders", vault?.id],
    queryFn: () => getJson<{ items: Folder[] }>(`/api/v1/folders?${query({ vault_id: vault!.id })}`),
    enabled: !!vault,
  });
  const notes = useInfiniteQuery({
    queryKey: ["notes", vault?.id, folder],
    queryFn: ({ pageParam }) =>
      getJson<Page<NoteMeta>>(`/api/v1/notes?${query({ vault_id: vault!.id, folder, cursor: pageParam })}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: !!vault,
  });
  const noteItems = notes.data?.pages.flatMap((page) => page.items);

  function openFolder(path: string | undefined) {
    setFolder(path);
    setPane("list");
  }

  let status = "Connecting…";
  if (vaults.isError) status = "Not connected";
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
          {notes.isError && <p className="p-4">Could not load notes.</p>}
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
          {note ? (
            <NoteEditor key={note.id} note={note} readOnly={note.read_only || vault?.role === "viewer"} onSaveState={setSaveState} />
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
