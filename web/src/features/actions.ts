// REST changes the web UI makes besides editing note text (plan R-P3-001). They need the
// server; the sync engine pulls their result into the device cache afterwards.
import { request, sendJson } from "@/api/client";
import type { Attachment, NoteMeta, RenameResult } from "@/api/types";

export const SORTS = {
  path: "Path",
  title: "Title",
  "-modified_at": "Recently modified",
  "-created_at": "Recently created",
} as const;
export type Sort = keyof typeof SORTS;

export const query = (params: Record<string, string | undefined>) =>
  new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined));

export const ifMatch = (revision: number) => ({ "If-Match": `"${revision}"` });

/** The folder part of a vault path ("" at the root). */
export const folderOf = (path: string) => path.slice(0, Math.max(path.lastIndexOf("/"), 0));
export const join = (folder: string | undefined, name: string) => (folder ? `${folder}/${name}` : name);
export const withoutMd = (path: string) => path.replace(/\.md$/i, "");

export function createNote(vaultId: string, path: string): Promise<NoteMeta> {
  return sendJson<NoteMeta>("/api/v1/notes", "POST", { vault_id: vaultId, path: `${withoutMd(path)}.md` });
}

export function renameNote(note: Pick<NoteMeta, "id" | "revision">, path: string, updateLinks: boolean) {
  return sendJson<RenameResult>(
    `/api/v1/notes/${note.id}/rename`,
    "POST",
    { path: `${withoutMd(path)}.md`, update_links: updateLinks },
    ifMatch(note.revision),
  );
}

export function deleteNote(note: Pick<NoteMeta, "id" | "revision">) {
  return sendJson(`/api/v1/notes/${note.id}`, "DELETE", undefined, ifMatch(note.revision));
}

export function restoreNote(id: string, revision: number, fromRevision: number) {
  return sendJson<NoteMeta>(`/api/v1/notes/${id}/restore`, "POST", { from_revision: fromRevision }, ifMatch(revision));
}

type Flag = "favorite" | "archived";

/** The note's `opennote:` frontmatter mapping, or {} when it has none. */
export function opennoteProps(note: Pick<NoteMeta, "properties">): Record<string, unknown> {
  const value = note.properties?.opennote;
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export const hasFlag = (note: Pick<NoteMeta, "properties">, flag: Flag) => opennoteProps(note)[flag] === true;

/** Sets or clears `opennote.<flag>`; PATCH replaces the whole namespace, so the other keys
 * are sent back unchanged. Clearing removes the key instead of writing `false`. */
export function setFlag(note: NoteMeta, flag: Flag, on: boolean) {
  const rest = { ...opennoteProps(note) };
  delete rest[flag];
  return sendJson<NoteMeta>(`/api/v1/notes/${note.id}`, "PATCH", { opennote: on ? { ...rest, [flag]: true } : rest }, ifMatch(note.revision));
}

export function setTags(note: NoteMeta, tags: string[]) {
  return sendJson<NoteMeta>(`/api/v1/notes/${note.id}`, "PATCH", { tags }, ifMatch(note.revision));
}

/** A file name safe as one vault path segment: no separators or control characters. */
export function safeFileName(name: string): string {
  // eslint-disable-next-line no-control-regex -- control characters are what is removed
  const cleaned = name.replace(/[\\/\u0000-\u001f\u007f]/g, "_").trim();
  return cleaned && cleaned !== "." && cleaned !== ".." ? cleaned : "attachment";
}

export async function uploadAttachment(vaultId: string, path: string, file: Blob): Promise<Attachment> {
  const form = new FormData();
  form.set("vault_id", vaultId);
  form.set("path", path);
  form.set("file", file);
  return (await (await request("/api/v1/attachments", { method: "POST", body: form })).json()) as Attachment;
}

export const attachmentUrl = (id: string) => `/api/v1/attachments/${id}/content`;

/** The attachment an embed names, as Obsidian finds it: the vault path, then next to the
 * note, then the file name anywhere (shortest path first). */
export function resolveAttachment(attachments: Attachment[], target: string, notePath: string): Attachment | undefined {
  const exact = attachments.find((a) => a.path === target) ?? attachments.find((a) => a.path === join(folderOf(notePath), target));
  if (exact) return exact;
  const name = target.split("/").at(-1);
  return attachments
    .filter((a) => a.path.split("/").at(-1) === name)
    .sort((a, b) => a.path.length - b.path.length)[0];
}

export function createFolder(vaultId: string, path: string) {
  return sendJson("/api/v1/folders", "POST", { vault_id: vaultId, path });
}

export function moveFolder(vaultId: string, path: string, newPath: string) {
  return sendJson("/api/v1/folders", "PATCH", { vault_id: vaultId, path, new_path: newPath });
}

export function deleteFolder(vaultId: string, path: string) {
  const query = new URLSearchParams({ vault_id: vaultId, path });
  return sendJson(`/api/v1/folders?${query}`, "DELETE");
}
