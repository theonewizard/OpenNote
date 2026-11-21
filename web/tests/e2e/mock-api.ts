// Serves the v1 routes the web app uses from memory through page.route, so the
// Playwright tests run the production build without a backend. Notes live in the fake
// sync server (src/mocks/sync-server.ts), which the editor reads and writes through; the
// other routes come from the fake REST API (src/mocks/rest-api.ts) on top of it.
import type { Page } from "@playwright/test";

import type { PushOperation, User, Vault } from "@/api/types";
import { FakeRestApi } from "@/mocks/rest-api";
import { FakeSyncServer } from "@/mocks/sync-server";

export interface MockApi {
  sync: FakeSyncServer;
  rest: FakeRestApi;
  ids: string[];
  /** Every pushed operation, in order */
  ops: () => PushOperation[];
  /** While true, every API request fails as if the network were down */
  offline: boolean;
}

const VAULT: Vault = {
  id: "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c",
  name: "Corpus",
  role: "owner",
  revision: 1,
  created_at: "2026-11-07T10:00:00.000Z",
  settings: { ai_enabled: false, sync_obsidian_config: false },
};
const USER: User = {
  id: "0192a0c4-0000-7000-8000-00000000e2e0",
  username: "e2e",
  display_name: "E2E",
  email: null,
  is_admin: false,
  created_at: "2026-11-07T10:00:00.000Z",
};

export async function mockApi(page: Page, files: { path: string; bytes: Buffer }[], options: { signedIn?: boolean } = {}): Promise<MockApi> {
  const sync = new FakeSyncServer();
  const ids = files.map((f, i) => {
    const id = `018f5a40-2d14-7b9c-8e3a-${String(i).padStart(12, "0")}`;
    sync.seed(id, f.path, new Uint8Array(f.bytes));
    return id;
  });
  const rest = new FakeRestApi(sync, { vault: VAULT, user: USER, signedIn: options.signedIn });

  const api: MockApi = { sync, rest, ids, ops: () => sync.pushes.flat(), offline: false };
  await page.route("**/api/v1/**", async (route) => {
    if (api.offline) return route.abort("internetdisconnected");
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/events") {
      // One `ready` hint, then the stream ends; the browser reconnects after `retry`.
      const body = `retry: 600000\n\nevent: ready\ndata: {"vaults":["${VAULT.id}"]}\n\n`;
      return route.fulfill({ headers: { "Content-Type": "text/event-stream" }, body });
    }
    const body = request.postDataBuffer();
    const fetchRequest = () =>
      new Request(url, { method: request.method(), headers: request.headers(), body: body ? new Uint8Array(body) : undefined });
    const answer = await sync
      .handle(fetchRequest())
      .then((a) => a ?? rest.handle(fetchRequest()))
      .catch(() => undefined);
    if (answer) {
      return route.fulfill({ status: answer.status, headers: Object.fromEntries(answer.headers), body: Buffer.from(await answer.arrayBuffer()) });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  return api;
}
