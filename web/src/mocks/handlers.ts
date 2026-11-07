// MSW handlers for the v1 routes the web app uses, following docs/api/api-contract.md.
// Used by the unit tests (msw/node) and by `npm run dev:mock` (msw/browser). Each call to
// createHandlers gets its own in-memory vault so tests do not share state.
import { http, HttpResponse } from "msw";

import type { Folder, NoteMeta, Vault } from "@/api/types";

const VAULT_ID = "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c";

const vaults: Vault[] = [{ id: VAULT_ID, name: "Work", role: "owner", revision: 1 }];
const folders: Folder[] = [
  { path: "Meetings", name: "Meetings", parent: null },
  { path: "Projects", name: "Projects", parent: null },
  { path: "Projects/Alpha", name: "Alpha", parent: "Projects" },
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
      modified_at: "2026-11-07T10:00:00.000Z",
      tags: [],
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

const problem = (status: number, title: string) =>
  HttpResponse.json(
    { type: "about:blank", title, status },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );

const etag = (n: MockNote) => `"${n.meta.revision}"`;

function inFolder(path: string, folder: string | null) {
  if (folder === null) return true;
  return path.slice(0, path.lastIndexOf("/")) === folder;
}

export function createHandlers(notes: MockNote[] = initialNotes()) {
  const find = (id: unknown) => notes.find((n) => n.meta.id === id);
  return [
    http.get("/api/v1/vaults", () => HttpResponse.json({ items: vaults, next_cursor: null })),
    http.get("/api/v1/folders", () => HttpResponse.json({ items: folders })),
    http.get("/api/v1/notes", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const all = notes.filter((n) => inFolder(n.meta.path, params.get("folder"))).map((n) => n.meta);
      const start = Number(params.get("cursor") ?? 0);
      const end = start + Number(params.get("limit") ?? 50);
      const next_cursor = end < all.length ? String(end) : null;
      return HttpResponse.json({ items: all.slice(start, end), next_cursor });
    }),
    http.get("/api/v1/notes/:id/content", ({ params }) => {
      const n = find(params.id);
      if (!n) return problem(404, "Not Found");
      return new HttpResponse(n.bytes.slice(), {
        headers: { "Content-Type": "text/markdown; charset=utf-8", ETag: etag(n) },
      });
    }),
    http.put("/api/v1/notes/:id/content", async ({ params, request }) => {
      const n = find(params.id);
      if (!n) return problem(404, "Not Found");
      const ifMatch = request.headers.get("if-match");
      if (!ifMatch) return problem(428, "Precondition Required");
      if (ifMatch !== etag(n)) return problem(412, "Precondition Failed");
      n.bytes = new Uint8Array(await request.arrayBuffer());
      n.meta = { ...n.meta, revision: n.meta.revision + 1 };
      return HttpResponse.json(n.meta, { headers: { ETag: etag(n) } });
    }),
  ];
}
