// MSW handlers for the v1 routes the web app uses, following docs/api/api-contract.md.
// Used by the unit tests (msw/node) and by `npm run dev:mock` (msw/browser). Each call to
// createHandlers gets its own in-memory vault so tests do not share state.
import { http, HttpResponse } from "msw";

import type { NoteMeta, User, Vault } from "@/api/types";
import { FakeRestApi, type RestOptions } from "@/mocks/rest-api";
import { FakeSyncServer } from "@/mocks/sync-server";

const VAULT_ID = "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c";

const vault = (): Vault => ({
  id: VAULT_ID,
  name: "Work",
  role: "owner",
  revision: 1,
  created_at: "2026-11-07T10:00:00.000Z",
  settings: { ai_enabled: false, sync_obsidian_config: false },
});
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

const withTags = (n: MockNote, tags: string[]): MockNote => ({ ...n, meta: { ...n.meta, tags } });

export function initialNotes(): MockNote[] {
  return [
    note(1, "Welcome.md", enc("# Welcome\n\nThis is **OpenNote**. See [[Projects/Alpha/Plan]].\n")),
    withTags(note(2, "Projects/Alpha/Plan.md", enc("﻿---\r\ntags: [alpha]\r\n---\r\n# Plan\r\n\r\n- [ ] First step\r\n")), ["alpha"]),
    note(3, "Meetings/Legacy.md", new Uint8Array([0x23, 0x20, 0x43, 0x61, 0x66, 0xe9, 0x0a])),
  ];
}

const USER: User = {
  id: "0192a0c4-0000-7000-8000-00000000a11c",
  username: "dana",
  display_name: "Dana",
  email: null,
  is_admin: true,
  created_at: "2026-11-07T10:00:00.000Z",
};

/** The REST routes over the notes in `sync` (see FakeRestApi). */
export function createRest(notes: MockNote[], sync: FakeSyncServer, options: Partial<RestOptions> = {}) {
  const meta = new Map(notes.map((n) => [n.meta.id, { tags: n.meta.tags, properties: n.meta.properties }]));
  return new FakeRestApi(sync, { vault: vault(), user: USER, meta, ...options });
}

// Notes live in the fake sync server: the note list shows its files, and the editor reads
// and writes them through the sync endpoints, as the app does against the real API.
export function createHandlers(notes: MockNote[] = initialNotes(), sync = new FakeSyncServer(), rest = createRest(notes, sync)) {
  for (const n of notes) sync.seed(n.meta.id, n.meta.path, n.bytes as Uint8Array<ArrayBuffer>);
  return [
    http.all("/api/v1/*", async ({ request }) => {
      try {
        return (await sync.handle(request)) ?? (await rest.handle(request));
      } catch {
        return HttpResponse.error();
      }
    }),
  ];
}
