// The web sync engine against the fake sync server (src/mocks/sync-server.ts).
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { createHandlers } from "@/mocks/handlers";
import { FakeSyncServer } from "@/mocks/sync-server";
import * as api from "@/sync/api";
import { OUTBOX_MAX_AGE_MS, StaleEdit, SyncEngine } from "@/sync/engine";
import { sha256 } from "@/sync/hash";
import { server } from "./setup";

const VAULT = "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c";
const A = "018f5a40-2d14-7b9c-8e3a-00000000000a";
const B = "018f5a40-2d14-7b9c-8e3a-00000000000b";
const enc = (text: string) => new TextEncoder().encode(text);
const dec = (bytes: Uint8Array | undefined) => new TextDecoder().decode(bytes);

let sync: FakeSyncServer;
let engine: SyncEngine;

beforeEach(async () => {
  sync = new FakeSyncServer();
  sync.seed(A, "A.md", enc("alpha\n"));
  sync.seed(B, "B.md", enc("beta\n"));
  server.use(...createHandlers([], sync));
  engine = await SyncEngine.open("user-1");
});
afterEach(() => engine.close());

async function readText(fileId: string) {
  return dec((await engine.read(VAULT, fileId))?.bytes);
}

async function editText(fileId: string, text: string) {
  const current = await engine.read(VAULT, fileId);
  return engine.edit(VAULT, fileId, enc(text), current!.hash);
}

it("first sync reads the whole vault from the snapshot and pulls from its cursor", async () => {
  sync.seed("018f5a40-2d14-7b9c-8e3a-00000000000c", "C.md", enc("gamma\n")); // a third page
  await engine.sync(VAULT);
  expect(await readText(A)).toBe("alpha\n");
  expect((await engine.files(VAULT)).map((f) => f.path).sort()).toEqual(["A.md", "B.md", "C.md"]);
  await sync.edit(A, enc("alpha 2\n"));
  await engine.sync(VAULT);
  expect(await readText(A)).toBe("alpha 2\n");
  expect(engine.status(VAULT)).toMatchObject({ state: "idle", unsynced: 0 });
});

it("keeps an offline edit across a reload and pushes it with the CSRF token once online", async () => {
  await engine.sync(VAULT);
  sync.offline = true;
  document.cookie = "opennote_csrf=token-1";
  const tokens: (string | null)[] = [];
  server.use(
    http.post("/api/v1/sync/:vault/push", ({ request }) => {
      tokens.push(request.headers.get("x-csrf-token"));
    }),
  );
  await editText(A, "offline edit\n");
  await expect(engine.sync(VAULT)).rejects.toThrow();
  expect(engine.status(VAULT)).toMatchObject({ state: "offline", unsynced: 1 });

  engine.close(); // a reload
  engine = await SyncEngine.open("user-1");
  expect(await readText(A)).toBe("offline edit\n");
  sync.offline = false;
  await engine.sync(VAULT);
  expect(dec(await sync.bytes(A))).toBe("offline edit\n");
  expect(sync.files.get(A)!.revision).toBe(2);
  expect(sync.pushes.at(-1)).toMatchObject([{ op: "update", file_id: A, base_revision: 1 }]);
  expect(tokens).toEqual(["token-1"]);
  expect(engine.status(VAULT).unsynced).toBe(0);
  document.cookie = "opennote_csrf=; max-age=0";
});

it("coalesces edits made before a push into one update", async () => {
  await engine.sync(VAULT);
  let hash = await editText(A, "one\n");
  hash = await engine.edit(VAULT, A, enc("two\n"), hash);
  await engine.edit(VAULT, A, enc("three\n"), hash);
  await engine.sync(VAULT);
  expect(sync.pushes).toHaveLength(1);
  expect(sync.pushes[0]).toHaveLength(1);
  expect(dec(await sync.bytes(A))).toBe("three\n");
});

it("runs again when a sync is requested as a run reports idle", async () => {
  await engine.sync(VAULT);
  const getChanges = vi.spyOn(api, "getChanges");
  let asked = false;
  const off = engine.subscribe(() => {
    // The run says idle before it lets go of the vault: an explicit save in that gap
    // must still be pushed, not wait for the 60 s timer.
    if (asked || engine.status(VAULT).state !== "idle") return;
    asked = true;
    void engine.sync(VAULT);
  });
  await engine.sync(VAULT);
  off();
  await vi.waitFor(() => expect(getChanges).toHaveBeenCalledTimes(2));
  getChanges.mockRestore();
});

it("never touches an unpushed edit when a pull brings a newer revision", async () => {
  await engine.sync(VAULT);
  await sync.edit(A, enc("theirs\n"));
  // The edit lands after this sync's push and before its pull.
  const getChanges = api.getChanges;
  vi.spyOn(api, "getChanges").mockImplementationOnce(async (...args) => {
    await editText(A, "mine\n");
    return getChanges(...args);
  });
  await engine.sync(VAULT);
  // The pull kept the edit; the next push sends it on base 1. The fake server does not
  // merge, so the edit becomes a conflict copy and nothing is lost.
  await engine.sync(VAULT);
  expect(sync.pushes.at(-1)).toMatchObject([{ op: "update", base_revision: 1 }]);
  const files = await engine.files(VAULT);
  const copy = files.find((f) => f.path.startsWith("A (conflict"))!;
  expect(dec(await sync.bytes(copy.file_id))).toBe("mine\n");
  expect(await readText(copy.file_id)).toBe("mine\n");
  expect(await readText(A)).toBe("theirs\n");
  expect((await engine.file(VAULT, A))!.notice).toContain(copy.path);
});

it("keeps the conflict notice when the pull then brings the server's revision", async () => {
  await engine.sync(VAULT);
  await editText(A, "mine\n");
  await sync.edit(A, enc("theirs\n")); // not pulled before the push
  await engine.sync(VAULT);
  expect(await readText(A)).toBe("theirs\n");
  expect((await engine.file(VAULT, A))!.notice).toContain("A (conflict web");
  await editText(A, "theirs, then mine\n"); // acting on the note clears it
  expect((await engine.file(VAULT, A))!.notice).toBeUndefined();
});

it("takes the server's merged bytes when nothing was typed since the push", async () => {
  sync.merge = (_base, theirs, ours) => enc(dec(theirs) + dec(ours));
  await engine.sync(VAULT);
  await sync.edit(A, enc("theirs\n"));
  await editText(A, "mine\n");
  await engine.sync(VAULT);
  expect(await readText(A)).toBe("theirs\nmine\n");
  expect((await engine.file(VAULT, A))!.base_revision).toBe(3);
});

it("pushes an edit made on bytes sync replaced against the revision it was made on", async () => {
  await engine.sync(VAULT);
  const stale = (await engine.read(VAULT, A))!.hash;
  await sync.edit(A, enc("theirs\n"));
  await engine.sync(VAULT); // the editor still shows "alpha"
  await engine.edit(VAULT, A, enc("alpha mine\n"), stale);
  await engine.sync(VAULT);
  expect(sync.pushes.at(-1)).toMatchObject([{ op: "update", base_revision: 1 }]);
  // An edit on bytes the device never held is refused, nothing stored.
  await expect(engine.edit(VAULT, A, enc("x"), "sha256:unknown")).rejects.toBeInstanceOf(StaleEdit);
});

it("flags a rejected edit, never retries it, and pushes again after the next edit", async () => {
  await engine.sync(VAULT);
  sync.files.delete(A); // the server no longer knows the file: update is rejected
  await editText(A, "orphan\n");
  await engine.sync(VAULT);
  expect((await engine.file(VAULT, A))!.rejected?.title).toBe("File not found");
  expect(engine.status(VAULT)).toMatchObject({ rejected: 1, unsynced: 1 });
  await engine.sync(VAULT);
  expect(sync.pushes).toHaveLength(1);
  expect(await readText(A)).toBe("orphan\n");

  await engine.discard(VAULT, A);
  expect(await readText(A)).toBe("alpha\n");
  expect(engine.status(VAULT).unsynced).toBe(0);
});

it("retries an operation whose response was lost and accepts the duplicate result", async () => {
  await engine.sync(VAULT);
  await editText(A, "once\n");
  let lose = true;
  server.use(
    http.post("/api/v1/sync/:vault/push", async ({ request }) => {
      if (!lose) return;
      lose = false;
      await sync.handle(request.clone()); // the server commits, the client never hears
      return HttpResponse.error();
    }),
  );
  await expect(engine.sync(VAULT)).rejects.toThrow();
  await engine.sync(VAULT);
  expect(sync.pushes).toHaveLength(2);
  expect(sync.pushes[1][0].client_op_id).toBe(sync.pushes[0][0].client_op_id);
  expect(sync.files.get(A)!.revision).toBe(2);
  expect(await engine.file(VAULT, A)).toMatchObject({ base_revision: 2, rejected: undefined });
  expect(engine.status(VAULT).unsynced).toBe(0);
});

it("reconciles from the snapshot when the cursor expired", async () => {
  await engine.sync(VAULT);
  await sync.remove(B); // deleted, and the tombstone expires before the device pulls
  await sync.edit(A, enc("alpha 2\n"));
  sync.horizon = sync.log.length;
  sync.files.delete(B);
  await engine.sync(VAULT);
  expect(await readText(A)).toBe("alpha 2\n");
  expect(await engine.file(VAULT, B)).toMatchObject({ deleted: true, local_hash: null });
});

it("pushes an edit to a file deleted elsewhere as a new file after a reconcile", async () => {
  await engine.sync(VAULT);
  await editText(B, "kept\n"); // offline for longer than the retention margin
  await sync.remove(B);
  sync.horizon = sync.log.length;
  sync.files.delete(B);
  vi.spyOn(Date, "now").mockReturnValue(Date.now() + OUTBOX_MAX_AGE_MS + 1);
  await engine.sync(VAULT);
  vi.restoreAllMocks();
  const restored = (await sync.liveFiles()).find(([, f]) => f.path === "B.md");
  expect(restored).toBeDefined();
  expect(restored![0]).not.toBe(B);
  expect(dec(await sync.bytes(restored![0]))).toBe("kept\n");
  expect((await engine.file(VAULT, restored![0]))!.notice).toContain("deleted elsewhere");
});

it("drops outbox operations older than the retention margin and pushes the edit afresh", async () => {
  await engine.sync(VAULT);
  await editText(A, "old edit\n");
  vi.spyOn(api, "push").mockRejectedValueOnce(new TypeError("Failed to fetch"));
  await expect(engine.sync(VAULT)).rejects.toThrow();
  const firstOp = sync.pushes.length;
  vi.spyOn(Date, "now").mockReturnValue(Date.now() + OUTBOX_MAX_AGE_MS + 1);
  await engine.sync(VAULT);
  vi.restoreAllMocks();
  expect(firstOp).toBe(0);
  expect(sync.pushes).toHaveLength(1);
  expect(dec(await sync.bytes(A))).toBe("old edit\n");
});

it("uploads a large blob in 8 MiB chunks and resumes at the server's offset", async () => {
  const bytes = new Uint8Array(api.CHUNK_BYTES * 2 + 5).fill(7);
  const hash = await sha256(bytes);
  let fail = true;
  server.use(
    http.put("/api/v1/blobs/:hash", async ({ request }) => {
      if (request.headers.get("content-range")?.startsWith(`bytes ${api.CHUNK_BYTES}-`) && fail) {
        fail = false;
        await sync.handle(request.clone()); // stored, but the answer is lost
        return HttpResponse.error();
      }
    }),
  );
  await expect(api.putBlob(VAULT, hash, bytes)).rejects.toThrow();
  await api.putBlob(VAULT, hash, bytes); // HEAD gives the offset after the second chunk
  expect(sync.blobs.get(hash)?.length).toBe(bytes.length);
  await api.putBlob(VAULT, hash, bytes); // present: HEAD answers 200 and nothing is sent
});

it("never pulls its own change back as an edit", async () => {
  await engine.sync(VAULT);
  await editText(A, "mine\n");
  await engine.sync(VAULT);
  await engine.sync(VAULT);
  expect(sync.pushes).toHaveLength(1);
  expect(await engine.file(VAULT, A)).toMatchObject({ base_revision: 2, local_hash: sync.files.get(A)!.hash });
});
