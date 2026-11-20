// MSW handlers for the v1 routes the web app uses, following docs/api/api-contract.md.
// Used by the unit tests (msw/node) and by `npm run dev:mock` (msw/browser). Each call to
// createHandlers gets its own in-memory vault so tests do not share state.
import { http, HttpResponse } from "msw";

import type { Folder, NoteMeta, Vault } from "@/api/types";
import { FakeSyncServer } from "@/mocks/sync-server";

const VAULT_ID = "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c";

const vaults: Vault[] = [
  {
    id: VAULT_ID,
    name: "Work",
    role: "owner",
    revision: 1,
    created_at: "2026-11-07T10:00:00.000Z",
    settings: { ai_enabled: false, sync_obsidian_config: false },
  },
];
const folders: Folder[] = [
  { path: "Meetings", name: "Meetings", parent: null, note_count: 1, attachment_count: 0 },
  { path: "Projects", name: "Projects", parent: null, note_count: 0, attachment_count: 0 },
  { path: "Projects/Alpha", name: "Alpha", parent: "Projects", note_count: 1, attachment_count: 0 },
];

const enc = (text: string) => new TextEncoder().encode(text);

export interface MockNote {
  meta: NoteMeta;
  bytes: Uint8Array;
}

function note(n: number, path: string, bytes: Uint8Array): MockNote {
  const title = path.split("/").at(-1)!.replace(/\.md$/, "");
  return {
    meta: {
      id: `018f5a40-2d14-7b9c-8e3a-${String(n).padStart(12, "0")}`,
      vault_id: VAULT_ID,
      path,
      title,
      revision: 1,
      created_at: "2026-11-07T10:00:00.000Z",
      modified_at: "2026-11-07T10:00:00.000Z",
      modified_by_device: "web",
      content_hash: "sha256:0",
      size: bytes.length,
      tags: [],
      aliases: [],
      properties: null,
      frontmatter_error: false,
      path_warning: null,
      has_id_in_file: false,
      read_only: false,
    },
    bytes,
  };
}

export function initialNotes(): MockNote[] {
  return [
    note(1, "Welcome.md", enc("# Welcome\n\nThis is **OpenNote**. See [[Projects/Alpha/Plan]].\n")),
    note(2, "Projects/Alpha/Plan.md", enc("﻿---\r\ntags: [alpha]\r\n---\r\n# Plan\r\n\r\n- [ ] First step\r\n")),
    note(3, "Meetings/Legacy.md", new Uint8Array([0x23, 0x20, 0x43, 0x61, 0x66, 0xe9, 0x0a])),
  ];
}

const USER = { id: "0192a0c4-0000-7000-8000-00000000a11c", display_name: "Dana", email: null, created_at: "2026-11-07T10:00:00.000Z" };

function inFolder(path: string, folder: string | null) {
  if (folder === null) return true;
  return path.slice(0, path.lastIndexOf("/")) === folder;
}

// Notes live in the fake sync server: the note list shows its files, and the editor reads
// and writes them through the sync endpoints, as the app does against the real API.
export function createHandlers(notes: MockNote[] = initialNotes(), sync = new FakeSyncServer()) {
  for (const n of notes) sync.seed(n.meta.id, n.meta.path, n.bytes as Uint8Array<ArrayBuffer>);
  const metas = new Map(notes.map((n) => [n.meta.id, n.meta]));
  return [
    http.all("/api/v1/*", async ({ request }) => {
      try {
        return await sync.handle(request);
      } catch {
        return HttpResponse.error();
      }
    }),
    http.get("/api/v1/me", () => HttpResponse.json(USER)),
    http.get("/api/v1/vaults", () => HttpResponse.json({ items: vaults, next_cursor: null })),
    http.get("/api/v1/folders", () => HttpResponse.json({ items: folders })),
    http.get("/api/v1/notes", async ({ request }) => {
      const params = new URL(request.url).searchParams;
      const all = (await sync.liveFiles())
        .filter(([, f]) => f.kind === "note" && inFolder(f.path, params.get("folder")))
        .map(([id, f]) => ({
          ...(metas.get(id) ?? note(0, f.path, new Uint8Array()).meta),
          id,
          path: f.path,
          title: f.path.split("/").at(-1)!.replace(/\.md$/, ""),
          revision: f.revision,
          content_hash: f.hash!,
          size: f.size,
        }));
      const start = Number(params.get("cursor") ?? 0);
      const end = start + Number(params.get("limit") ?? 50);
      const next_cursor = end < all.length ? String(end) : null;
      return HttpResponse.json({ items: all.slice(start, end), next_cursor });
    }),
  ];
}
