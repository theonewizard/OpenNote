// The web sync engine (roadmap P5-04, sync protocol §§4, 5, 9, 10). Edits land in
// IndexedDB and the outbox at once; the loop pushes the outbox, then pulls by cursor. The
// server does every merge; this side never overwrites or drops content it has not pushed.
import { ApiError } from "@/api/client";
import type { PushOperation, PushResult, SyncEntry } from "@/api/types";
import * as api from "@/sync/api";
import {
  byVault,
  openDatabase,
  request,
  transact,
  type FileRecord,
  type OutboxEntry,
  type RecoveryEntry,
} from "@/sync/db";
import { sha256, uuidv7 } from "@/sync/hash";

const DAY_MS = 86_400_000;
/** Outbox operations older than the tombstone window (90 days) minus a 7-day margin are
 * dropped and replaced by a full reconcile (sync protocol §5). */
export const OUTBOX_MAX_AGE_MS = (90 - 7) * DAY_MS;
const RECOVERY_KEEP_MS = 30 * DAY_MS;
const BATCH_SIZE = 100;
const EDIT_DEBOUNCE_MS = 2_000;
const TIMER_MS = 60_000;

export type SyncState = "idle" | "syncing" | "offline" | "error";

export interface SyncStatus {
  state: SyncState;
  /** Local changes the server does not have yet (pending operations and rejected edits) */
  unsynced: number;
  rejected: number;
}

export const IDLE: SyncStatus = { state: "idle", unsynced: 0, rejected: 0 };

export interface Content {
  bytes: Uint8Array<ArrayBuffer>;
  hash: string;
}

/** What a caller knows about a note before the first sync has seen it (from GET /notes). */
export interface KnownFile {
  id: string;
  path: string;
  revision: number;
  content_hash: string;
}

/** The edit was made on bytes the device no longer holds: nothing was stored. */
export class StaleEdit extends Error {}

type Listener = (vaultId: string, fileIds: string[]) => void;

const key = (vaultId: string, fileId: string) => [vaultId, fileId];
const isOffline = (error: unknown) =>
  error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError") || !navigator.onLine;

function dirty(f: FileRecord, pending: Set<string>): boolean {
  return f.base_revision === 0 || f.local_hash !== f.base_hash || pending.has(f.file_id) || !!f.rejected;
}

/** The server's state for a file after an applied or merged operation. `sent` is the
 * content the operation was about (what was pushed, or the base it was made on). */
function settle(f: FileRecord, r: PushResult, sent: string | null): FileRecord {
  const next: FileRecord = { ...f, path: r.path ?? f.path, rejected: undefined };
  const result = r.content_hash;
  if (f.local_hash === sent) {
    // Nothing typed since: the device takes the server's bytes (merged ones included).
    if (result !== f.local_hash) next.prev = { hash: f.local_hash, base_revision: f.base_revision, base_hash: f.base_hash };
    Object.assign(next, { local_hash: result, base_hash: result, base_revision: r.revision ?? f.base_revision, deleted: result === null });
  } else if (result === sent) {
    Object.assign(next, { base_hash: result, base_revision: r.revision ?? f.base_revision });
  }
  // Otherwise newer local edits sit on bytes the server merged with something else: keep
  // the old base, so their push is merged by the server instead of replacing that merge.
  if ((next.remote_revision ?? 0) <= next.base_revision) {
    delete next.remote_revision;
    delete next.remote_hash;
  }
  return next;
}

/** `duplicate` repeats an earlier result without its status; recover it from the fields. */
function status(r: PushResult): PushResult["status"] {
  if (r.status !== "duplicate") return r.status;
  if (r.problem?.original_file_id) return "conflict";
  return r.problem && r.revision === null ? "rejected" : "applied";
}

function problemText(problem: PushResult["problem"]): { title: string; detail?: string } {
  const title = typeof problem?.title === "string" ? problem.title : "Rejected by the server";
  const detail = typeof problem?.detail === "string" ? problem.detail : undefined;
  return { title, detail };
}

function newEntry(vaultId: string, op: PushOperation): OutboxEntry {
  return { vault_id: vaultId, file_id: op.file_id, op, created_at: Date.now(), sent: false };
}

function createOp(f: FileRecord): PushOperation {
  return {
    op: "create",
    client_op_id: uuidv7(),
    file_id: f.file_id,
    path: f.path,
    kind: f.kind === "attachment" ? "attachment" : "note",
    content_hash: f.local_hash!,
  };
}

function updateOp(f: FileRecord): PushOperation {
  // base_revision is set when the entry is first sent
  return { op: "update", client_op_id: uuidv7(), file_id: f.file_id, base_revision: 0, content_hash: f.local_hash! };
}

export class SyncEngine {
  private readonly db: IDBDatabase;
  private readonly listeners = new Set<Listener>();
  private readonly statuses = new Map<string, SyncStatus>();
  private readonly running = new Map<string, Promise<void>>();
  private readonly again = new Set<string>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private stopLoop?: () => void;

  private constructor(db: IDBDatabase) {
    this.db = db;
  }

  static async open(userId: string): Promise<SyncEngine> {
    // Ask the browser not to evict the cache and outbox under storage pressure (§10).
    void navigator.storage?.persist?.().catch(() => false);
    return new SyncEngine(await openDatabase(`opennote-sync-${userId}`));
  }

  close(): void {
    this.stop();
    this.db.close();
  }

  // Listeners ------------------------------------------------------------------------------

  /** Called with the files sync changed, and with [] when a status changed. */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  status(vaultId: string): SyncStatus {
    return this.statuses.get(vaultId) ?? IDLE;
  }

  private emit(vaultId: string, fileIds: string[]): void {
    for (const listener of this.listeners) listener(vaultId, fileIds);
  }

  private async setStatus(vaultId: string, state?: SyncState): Promise<void> {
    const [outbox, files] = await transact(this.db, ["outbox", "files"], "readonly", (t) =>
      Promise.all([byVault<OutboxEntry>(t, "outbox", vaultId), byVault<FileRecord>(t, "files", vaultId)]),
    );
    const rejected = files.filter((f) => f.rejected).length;
    const next = { state: state ?? this.status(vaultId).state, unsynced: outbox.length + rejected, rejected };
    const old = this.status(vaultId);
    if (old.state === next.state && old.unsynced === next.unsynced && old.rejected === next.rejected) return;
    this.statuses.set(vaultId, next);
    this.emit(vaultId, []);
  }

  // Loop (§9) ------------------------------------------------------------------------------

  /** Syncs `vaultId` now, when the network comes back, on every change hint, every 60 s
   * and 2 s after a local edit. One vault at a time: starting another stops this one. */
  start(vaultId: string): void {
    this.stop();
    const run = () => this.requestSync(vaultId);
    const interval = setInterval(run, TIMER_MS);
    addEventListener("online", run);
    let events: EventSource | undefined;
    if (typeof EventSource !== "undefined") {
      // Hints are advisory: pull on `ready` (also after every reconnect) and on each change.
      events = new EventSource("/api/v1/events");
      events.addEventListener("ready", run);
      events.addEventListener("change", (event) => {
        try {
          if ((JSON.parse((event as MessageEvent<string>).data) as { vault_id?: string }).vault_id === vaultId) run();
        } catch {
          // a malformed hint changes nothing: the timer still pulls
        }
      });
    }
    this.stopLoop = () => {
      clearInterval(interval);
      removeEventListener("online", run);
      events?.close();
    };
    void this.setStatus(vaultId);
    run();
  }

  stop(): void {
    this.stopLoop?.();
    this.stopLoop = undefined;
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
  }

  private requestSync(vaultId: string, delay = 0): void {
    clearTimeout(this.timers.get(vaultId));
    if (delay) {
      this.timers.set(vaultId, setTimeout(() => this.requestSync(vaultId), delay));
      return;
    }
    this.timers.delete(vaultId);
    void this.sync(vaultId).catch(() => undefined); // the status says what failed
  }

  /** Push the outbox, then pull until the server has nothing newer. Resolves when done; a
   * call while a sync runs makes that sync run once more. */
  sync(vaultId: string): Promise<void> {
    const current = this.running.get(vaultId);
    if (current) {
      this.again.add(vaultId);
      return current;
    }
    const pass = async () => {
      do {
        this.again.delete(vaultId);
        await this.setStatus(vaultId, "syncing");
        await this.push(vaultId);
        await this.pull(vaultId);
        await this.push(vaultId); // operations a reconcile queued
        await this.fetchMissing(vaultId);
        await this.collectGarbage();
      } while (this.again.has(vaultId));
    };
    const run = (async () => {
      try {
        // Tabs of one user share the database: one of them syncs a vault at a time.
        if (navigator.locks) await navigator.locks.request(`opennote-sync-${vaultId}`, pass);
        else await pass();
        await this.setStatus(vaultId, "idle");
      } catch (error) {
        await this.setStatus(vaultId, isOffline(error) ? "offline" : "error");
        throw error;
      } finally {
        this.running.delete(vaultId);
      }
    })();
    this.running.set(vaultId, run);
    return run;
  }

  // Reading and editing --------------------------------------------------------------------

  /** The file's bytes on this device, downloading them when they are not cached yet.
   * `known` registers a note the first sync has not reached. Null for a deleted file. */
  async read(vaultId: string, fileId: string, known?: KnownFile): Promise<Content | null> {
    const [f, cached] = await transact(this.db, ["files", "contents"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      let f = (await request(files.get(key(vaultId, fileId)))) as FileRecord | undefined;
      if (!f && known) {
        f = {
          vault_id: vaultId,
          file_id: fileId,
          path: known.path,
          kind: "note",
          base_revision: known.revision,
          base_hash: known.content_hash,
          local_hash: known.content_hash,
          deleted: false,
        };
        await request(files.put(f));
      }
      const hash = f?.local_hash;
      return [f, hash ? ((await request(t.objectStore("contents").get(hash))) as Uint8Array<ArrayBuffer> | undefined) : undefined];
    });
    const hash = f?.local_hash;
    if (!hash) return null;
    if (cached) return { bytes: cached, hash };
    const bytes = await api.getBlob(vaultId, hash);
    await transact(this.db, ["contents"], "readwrite", (t) => request(t.objectStore("contents").put(bytes, hash)));
    return { bytes, hash };
  }

  async file(vaultId: string, fileId: string): Promise<FileRecord | undefined> {
    return transact(this.db, ["files"], "readonly", (t) => request(t.objectStore("files").get(key(vaultId, fileId))));
  }

  async files(vaultId: string): Promise<FileRecord[]> {
    return transact(this.db, ["files"], "readonly", (t) => byVault<FileRecord>(t, "files", vaultId));
  }

  /** Stores an edit and queues it. `expected` is the hash of the bytes the edit was made on;
   * if sync replaced them meanwhile, the edit is pushed against the revision it was made
   * on, so the server merges it with the newer one instead of overwriting it. It is
   * synced 2 s later, or at once with `syncNow` (an explicit save). */
  async edit(vaultId: string, fileId: string, bytes: Uint8Array<ArrayBuffer>, expected: string, syncNow = false): Promise<string> {
    const hash = await sha256(bytes);
    await transact(this.db, ["files", "outbox", "contents"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      const outbox = t.objectStore("outbox");
      const f = (await request(files.get(key(vaultId, fileId)))) as FileRecord | undefined;
      if (!f || f.deleted) throw new StaleEdit("The note is not on this device");
      if (f.local_hash !== expected) {
        if (f.prev?.hash !== expected) throw new StaleEdit("The note changed under the edit");
        f.base_revision = f.prev.base_revision;
        f.base_hash = f.prev.base_hash;
      }
      await request(t.objectStore("contents").put(bytes, hash));
      Object.assign(f, { local_hash: hash, prev: undefined, rejected: undefined, notice: undefined });
      const entries = (await byVault<OutboxEntry>(t, "outbox", vaultId)).filter((e) => e.file_id === fileId);
      const last = entries.at(-1);
      if (last && !last.sent && (last.op.op === "create" || last.op.op === "update")) {
        // Coalesce: one unsent operation per file carries the newest bytes.
        if (last.op.op === "update" && hash === f.base_hash) await request(outbox.delete(last.id!));
        else await request(outbox.put({ ...last, op: { ...last.op, content_hash: hash } }));
      } else if (f.base_revision === 0) {
        await request(outbox.add(newEntry(vaultId, createOp(f))));
      } else if (hash !== f.base_hash || entries.length) {
        await request(outbox.add(newEntry(vaultId, updateOp(f))));
      }
      await request(files.put(f));
    });
    void this.setStatus(vaultId);
    this.requestSync(vaultId, syncNow ? 0 : EDIT_DEBOUNCE_MS);
    return hash;
  }

  /** Drops a rejected edit: the device takes the server's bytes again. */
  async discard(vaultId: string, fileId: string): Promise<void> {
    await transact(this.db, ["files"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      const f = (await request(files.get(key(vaultId, fileId)))) as FileRecord | undefined;
      if (!f?.rejected) return;
      if (f.base_revision === 0) await request(files.delete(key(vaultId, fileId)));
      else await request(files.put({ ...f, local_hash: f.base_hash, rejected: undefined }));
    });
    await this.setStatus(vaultId);
    this.emit(vaultId, [fileId]);
  }

  // Push (§5) ------------------------------------------------------------------------------

  private async push(vaultId: string): Promise<void> {
    for (;;) {
      const entries = await transact(this.db, ["outbox"], "readonly", (t) => byVault<OutboxEntry>(t, "outbox", vaultId));
      if (!entries.length) return;
      if (entries.some((e) => Date.now() - e.created_at > OUTBOX_MAX_AGE_MS)) {
        await this.dropExpired(vaultId);
        await this.reconcile(vaultId);
        continue;
      }
      const batch: OutboxEntry[] = [];
      for (const e of entries) {
        // One operation per file per batch: the next one needs this one's revision.
        if (batch.length === BATCH_SIZE || batch.some((b) => b.file_id === e.file_id)) break;
        batch.push(e);
      }
      const frozen = await this.freeze(vaultId, batch);
      if (!frozen.length) continue;
      const contents = await transact(this.db, ["contents"], "readonly", (t) =>
        Promise.all(
          frozen.map((e) =>
            "content_hash" in e.op ? (request(t.objectStore("contents").get(e.op.content_hash)) as Promise<Uint8Array<ArrayBuffer> | undefined>) : undefined,
          ),
        ),
      );
      for (const [i, e] of frozen.entries()) {
        const bytes = contents[i];
        if ("content_hash" in e.op && bytes) await api.putBlob(vaultId, e.op.content_hash, bytes);
      }
      const { results } = await api.push(vaultId, frozen.map((e) => e.op));
      const changed = await this.applyResults(vaultId, frozen, results);
      await this.setStatus(vaultId);
      this.emit(vaultId, changed);
    }
  }

  /** Fixes each entry's base revision when it is first sent; a retry sends the same op. */
  private freeze(vaultId: string, batch: OutboxEntry[]): Promise<OutboxEntry[]> {
    return transact(this.db, ["files", "outbox", "contents"], "readwrite", async (t) => {
      const out: OutboxEntry[] = [];
      for (const e of batch) {
        const f = (await request(t.objectStore("files").get(key(vaultId, e.file_id)))) as FileRecord | undefined;
        const hasBytes = !("content_hash" in e.op) || (await request(t.objectStore("contents").getKey(e.op.content_hash))) !== undefined;
        if (!e.sent && "base_revision" in e.op) e.op.base_revision = f?.base_revision ?? 0;
        if (!f || !hasBytes || ("base_revision" in e.op && e.op.base_revision < 1)) {
          // Nothing the server could accept (its create was rejected, or the bytes are gone):
          // the content stays on the device, flagged.
          await request(t.objectStore("outbox").delete(e.id!));
          if (f) await request(t.objectStore("files").put({ ...f, rejected: { title: "Could not be sent" } }));
          continue;
        }
        if (!e.sent) await request(t.objectStore("outbox").put({ ...e, sent: true }));
        out.push({ ...e, sent: true });
      }
      return out;
    });
  }

  private applyResults(vaultId: string, entries: OutboxEntry[], results: PushResult[]): Promise<string[]> {
    return transact(this.db, ["files", "outbox"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      const changed: string[] = [];
      for (const [i, e] of entries.entries()) {
        const r = results[i];
        if (!r) break; // never sent back: the entry stays and is retried
        await request(t.objectStore("outbox").delete(e.id!));
        const f = (await request(files.get(key(vaultId, e.file_id)))) as FileRecord | undefined;
        if (!f) continue;
        const op = e.op;
        const sent = "content_hash" in op ? op.content_hash : op.op === "delete" ? null : f.base_hash;
        const s = status(r);
        if (s === "rejected") {
          await request(files.put({ ...f, rejected: problemText(r.problem) }));
        } else if (s === "conflict" && r.file_id !== f.file_id) {
          // The edit is now the conflict copy; this file goes back to the server's bytes.
          await request(
            files.put({
              vault_id: vaultId,
              file_id: r.file_id,
              path: r.path ?? f.path,
              kind: f.kind,
              base_revision: r.revision ?? 1,
              base_hash: r.content_hash,
              local_hash: r.content_hash,
              deleted: false,
              notice: "Conflict copy: holds an edit made on this device",
            }),
          );
          const next: FileRecord = { ...f, notice: `Changed elsewhere: your edit was kept as ${r.path ?? "a conflict copy"}` };
          if (f.local_hash === sent) {
            next.prev = { hash: f.local_hash, base_revision: f.base_revision, base_hash: f.base_hash };
            if ((f.remote_revision ?? 0) > f.base_revision) {
              Object.assign(next, { base_revision: f.remote_revision, base_hash: f.remote_hash, local_hash: f.remote_hash, deleted: f.remote_hash === null });
              delete next.remote_revision;
              delete next.remote_hash;
            } else {
              next.local_hash = f.base_hash; // the pull brings the server's revision
            }
          }
          await request(files.put(next));
          changed.push(r.file_id);
        } else {
          await request(files.put(settle(f, r, sent)));
        }
        changed.push(f.file_id);
      }
      return changed;
    });
  }

  private dropExpired(vaultId: string): Promise<void> {
    return transact(this.db, ["outbox"], "readwrite", async (t) => {
      for (const e of await byVault<OutboxEntry>(t, "outbox", vaultId)) {
        if (Date.now() - e.created_at > OUTBOX_MAX_AGE_MS) await request(t.objectStore("outbox").delete(e.id!));
      }
    });
  }

  // Pull (§4) ------------------------------------------------------------------------------

  private async pull(vaultId: string, reconcileOnExpiry = true): Promise<void> {
    let cursor = await transact(this.db, ["meta"], "readonly", (t) => request(t.objectStore("meta").get(`cursor:${vaultId}`)) as Promise<string | undefined>);
    if (cursor === undefined) return this.reconcile(vaultId); // first sync, or the cache was evicted
    for (;;) {
      let page;
      try {
        page = await api.getChanges(vaultId, cursor);
      } catch (error) {
        if (reconcileOnExpiry && error instanceof ApiError && error.status === 410) return this.reconcile(vaultId);
        throw error;
      }
      // Download first, so a note is never shown without its bytes; the newest entry per file.
      const latest = new Map(page.entries.map((e) => [e.file_id, e]));
      await this.download(vaultId, this.noteHashes([...latest.values()]));
      const changed = await this.applyEntries(vaultId, page.entries, page.next_cursor);
      if (changed.length) this.emit(vaultId, changed);
      cursor = page.next_cursor;
      if (!page.has_more) return;
    }
  }

  /** Note bytes are cached eagerly; attachments only when read. */
  private noteHashes(entries: { kind: string; deleted?: boolean; content_hash?: string | null; local_hash?: string | null }[]): Set<string> {
    return new Set(entries.filter((e) => e.kind === "note" && !e.deleted).map((e) => e.content_hash ?? e.local_hash).filter((h): h is string => !!h));
  }

  private async download(vaultId: string, hashes: Set<string>): Promise<void> {
    const missing = await transact(this.db, ["contents"], "readonly", async (t) => {
      const out: string[] = [];
      for (const hash of hashes) if ((await request(t.objectStore("contents").getKey(hash))) === undefined) out.push(hash);
      return out;
    });
    for (const hash of missing) {
      const bytes = await api.getBlob(vaultId, hash);
      await transact(this.db, ["contents"], "readwrite", (t) => request(t.objectStore("contents").put(bytes, hash)));
    }
  }

  private applyEntries(vaultId: string, entries: SyncEntry[], cursor: string): Promise<string[]> {
    return transact(this.db, ["files", "outbox", "meta", "recovery"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      const pending = new Set((await byVault<OutboxEntry>(t, "outbox", vaultId)).map((e) => e.file_id));
      const changed: string[] = [];
      for (const e of entries) {
        const f = (await request(files.get(key(vaultId, e.file_id)))) as FileRecord | undefined;
        if (!f) {
          await request(files.put(this.fromEntry(vaultId, e)));
          changed.push(e.file_id);
        } else if (e.revision <= f.base_revision) {
          continue; // already at this revision or newer
        } else if (dirty(f, pending)) {
          // Never touch unpushed content: the push is merged against this revision.
          await request(files.put({ ...f, remote_revision: e.revision, remote_hash: e.content_hash }));
        } else {
          await request(files.put(await this.adopt(t, f, e)));
          changed.push(e.file_id);
        }
      }
      await request(t.objectStore("meta").put(cursor, `cursor:${vaultId}`));
      return changed;
    });
  }

  private fromEntry(vaultId: string, e: SyncEntry): FileRecord {
    const hash = e.deleted ? null : e.content_hash;
    return { vault_id: vaultId, file_id: e.file_id, path: e.path, kind: e.kind, base_revision: e.revision, base_hash: hash, local_hash: hash, deleted: e.deleted };
  }

  /** A clean file takes the server's state; a deleted one moves to the recovery store. */
  private async adopt(t: IDBTransaction, f: FileRecord, e: SyncEntry): Promise<FileRecord> {
    const next: FileRecord = { ...this.fromEntry(f.vault_id, e), notice: f.notice };
    if (e.deleted && f.local_hash) {
      const entry: RecoveryEntry = { vault_id: f.vault_id, file_id: f.file_id, path: f.path, hash: f.local_hash, removed_at: Date.now() };
      await request(t.objectStore("recovery").add(entry));
    }
    if (next.local_hash !== f.local_hash) next.prev = { hash: f.local_hash, base_revision: f.base_revision, base_hash: f.base_hash };
    return next;
  }

  /** Full reconcile (§4): after a 410, an expired outbox, or with no cursor at all. Reads
   * every snapshot page, turns local differences into operations, then pulls from the
   * snapshot's cursor. Never deletes unpushed content and never resurrects a deleted file. */
  private async reconcile(vaultId: string): Promise<void> {
    const remote = new Map<string, SyncEntry>();
    let page: string | null = null;
    let cursor = "";
    do {
      const snapshot = await api.getSnapshot(vaultId, page);
      for (const e of snapshot.entries) remote.set(e.file_id, e);
      cursor = snapshot.cursor;
      page = snapshot.next_page;
    } while (page);
    await this.download(vaultId, this.noteHashes([...remote.values()]));
    const changed = await transact(this.db, ["files", "outbox", "meta", "recovery"], "readwrite", async (t) => {
      const files = t.objectStore("files");
      const outbox = t.objectStore("outbox");
      const entries = await byVault<OutboxEntry>(t, "outbox", vaultId);
      const pending = new Set(entries.map((e) => e.file_id));
      const changed: string[] = [];
      for (const f of await byVault<FileRecord>(t, "files", vaultId)) {
        const e = remote.get(f.file_id);
        remote.delete(f.file_id);
        if (f.rejected || (f.deleted && !e && !pending.has(f.file_id))) continue;
        if (!e) {
          if (f.base_revision === 0) {
            if (!pending.has(f.file_id) && f.local_hash) await request(outbox.add(newEntry(vaultId, createOp(f))));
          } else if (!dirty(f, pending)) {
            // Deleted on the server and its tombstone expired: like a pulled tombstone.
            const tombstone = { ...f, revision: f.base_revision, deleted: true, content_hash: null, seq: 0, size: 0, device_id: "", op: "delete" };
            await request(files.put(await this.adopt(t, f, tombstone)));
            changed.push(f.file_id);
          } else if (f.local_hash) {
            // Edited here, deleted there and the tombstone expired: the edit wins as a new file.
            for (const old of entries.filter((x) => x.file_id === f.file_id)) await request(outbox.delete(old.id!));
            const copy: FileRecord = { ...f, file_id: uuidv7(), base_revision: 0, base_hash: null, notice: "Restored: it was deleted elsewhere while edited here" };
            delete copy.remote_revision;
            delete copy.remote_hash;
            await request(files.put(copy));
            await request(outbox.add(newEntry(vaultId, createOp(copy))));
            await request(files.put({ ...f, deleted: true, local_hash: null, base_hash: null }));
            changed.push(f.file_id, copy.file_id);
          }
        } else if (!dirty(f, pending)) {
          if (e.revision !== f.base_revision || e.content_hash !== f.local_hash || e.path !== f.path) {
            await request(files.put(await this.adopt(t, f, e)));
            changed.push(f.file_id);
          }
        } else if (f.local_hash === e.content_hash && f.base_revision > 0) {
          // Already converged: unsent updates have nothing left to say.
          for (const old of entries.filter((x) => x.file_id === f.file_id && !x.sent && x.op.op === "update")) await request(outbox.delete(old.id!));
          await request(files.put({ ...f, base_revision: e.revision, base_hash: e.content_hash, path: e.path }));
        } else {
          await request(files.put({ ...f, remote_revision: e.revision, remote_hash: e.content_hash }));
          if (!pending.has(f.file_id) && f.local_hash) await request(outbox.add(newEntry(vaultId, f.base_revision === 0 ? createOp(f) : updateOp(f))));
        }
      }
      for (const e of remote.values()) {
        await request(files.put(this.fromEntry(vaultId, e)));
        changed.push(e.file_id);
      }
      await request(t.objectStore("meta").put(cursor, `cursor:${vaultId}`));
      return changed;
    });
    if (changed.length) this.emit(vaultId, changed);
    await this.pull(vaultId, false);
  }

  // Housekeeping ---------------------------------------------------------------------------

  /** Downloads note bytes a push result named but the device does not hold yet. */
  private async fetchMissing(vaultId: string): Promise<void> {
    await this.download(vaultId, this.noteHashes(await this.files(vaultId)));
  }

  /** Removes cached bytes nothing refers to, and recovery entries older than 30 days. */
  private collectGarbage(): Promise<void> {
    return transact(this.db, ["files", "outbox", "contents", "recovery"], "readwrite", async (t) => {
      const keep = new Set<unknown>();
      for (const f of (await request(t.objectStore("files").getAll())) as FileRecord[]) keep.add(f.local_hash).add(f.base_hash).add(f.prev?.hash);
      for (const e of (await request(t.objectStore("outbox").getAll())) as OutboxEntry[]) if ("content_hash" in e.op) keep.add(e.op.content_hash);
      const recovery = t.objectStore("recovery");
      for (const r of (await request(recovery.getAll())) as RecoveryEntry[]) {
        if (Date.now() - r.removed_at > RECOVERY_KEEP_MS) await request(recovery.delete(r.id!));
        else keep.add(r.hash);
      }
      const contents = t.objectStore("contents");
      for (const hash of await request(contents.getAllKeys())) if (!keep.has(hash)) await request(contents.delete(hash));
    });
  }

  // Cached values for offline start --------------------------------------------------------

  remember(name: string, value: unknown): Promise<void> {
    return transact(this.db, ["meta"], "readwrite", async (t) => void (await request(t.objectStore("meta").put(value, name))));
  }

  recall<T>(name: string): Promise<T | undefined> {
    return transact(this.db, ["meta"], "readonly", (t) => request(t.objectStore("meta").get(name)) as Promise<T | undefined>);
  }
}
