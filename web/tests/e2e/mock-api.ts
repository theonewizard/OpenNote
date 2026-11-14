// Serves the v1 routes the web app uses from memory through page.route, so the
// Playwright tests run the production build without a backend.
import type { Page } from "@playwright/test";

export interface E2ENote {
  path: string;
  bytes: Buffer;
  revision: number;
}

export interface MockApi {
  notes: Map<string, E2ENote>;
  puts: { id: string; ifMatch: string | null; body: Buffer }[];
}

const VAULT = { id: "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c", name: "Corpus", role: "owner", revision: 1 };

export async function mockApi(page: Page, files: { path: string; bytes: Buffer }[]): Promise<MockApi> {
  const api: MockApi = { notes: new Map(), puts: [] };
  files.forEach((f, i) => api.notes.set(`018f5a40-2d14-7b9c-8e3a-${String(i).padStart(12, "0")}`, { ...f, revision: 1 }));
  const meta = (id: string, n: E2ENote) => ({
    id,
    vault_id: VAULT.id,
    path: n.path,
    title: n.path.split("/").at(-1)!.replace(/\.md$/, ""),
    revision: n.revision,
    modified_at: "2026-11-07T10:00:00.000Z",
    tags: [],
    read_only: false,
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const content = /^\/api\/v1\/notes\/([^/]+)\/content$/.exec(url.pathname);
    if (url.pathname === "/api/v1/vaults") return route.fulfill({ json: { items: [VAULT], next_cursor: null } });
    if (url.pathname === "/api/v1/folders") return route.fulfill({ json: { items: [] } });
    if (url.pathname === "/api/v1/notes") {
      const items = [...api.notes].map(([id, n]) => meta(id, n));
      return route.fulfill({ json: { items, next_cursor: null } });
    }
    const note = content && api.notes.get(content[1]);
    if (note && request.method() === "GET") {
      return route.fulfill({
        body: note.bytes,
        headers: { "Content-Type": "text/markdown; charset=utf-8", ETag: `"${note.revision}"` },
      });
    }
    if (note && request.method() === "PUT") {
      const ifMatch = request.headers()["if-match"] ?? null;
      api.puts.push({ id: content[1], ifMatch, body: request.postDataBuffer() ?? Buffer.alloc(0) });
      if (ifMatch !== `"${note.revision}"`) return route.fulfill({ status: 412, body: "" });
      note.bytes = request.postDataBuffer() ?? Buffer.alloc(0);
      note.revision += 1;
      return route.fulfill({ json: meta(content[1], note), headers: { ETag: `"${note.revision}"` } });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  return api;
}
