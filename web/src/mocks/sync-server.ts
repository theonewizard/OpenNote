// An in-memory stand-in for the sync endpoints (sync protocol §§3-5), shared by the unit
// tests (MSW), `npm run dev:mock` and the Playwright tests (page.route). It speaks the
// Fetch API, so each of them only adapts Request and Response. It does not merge: an
// update on an old base is a conflict copy unless the test supplies `merge`.
import type { Conflict, PushOperation, PushResult, SyncEntry } from "@/api/types";
import { sha256 } from "@/sync/hash";

export interface FakeFile {
  path: string;
  kind: string;
  revision: number;
  hash: string | null;
  size: number;
  deleted: boolean;
}

type Merge = (base: Uint8Array, theirs: Uint8Array, ours: Uint8Array) => Uint8Array | null;

const json = (body: unknown, status = 200) => Response.json(body, { status });
const problem = (status: number, title: string, headers: Record<string, string> = {}) =>
  Response.json({ type: "about:blank", title, status }, { status, headers: { "Content-Type": "application/problem+json", ...headers } });

export class FakeSyncServer {
  readonly files = new Map<string, FakeFile>();
  readonly blobs = new Map<string, Uint8Array<ArrayBuffer>>();
  readonly log: SyncEntry[] = [];
  readonly pushes: PushOperation[][] = [];
  readonly results = new Map<string, PushResult>();
  readonly uploads = new Map<string, Uint8Array<ArrayBuffer>>();
  readonly revisions = new Map<string, string | null>(); // `${file}:${revision}` -> hash
  readonly conflicts: Conflict[] = [];
  /** Cursors before this seq are expired (410) */
  horizon = 0;
  merge?: Merge;
  /** Set to make every sync request fail as if the network were down */
  offline = false;
  private ready: Promise<void> = Promise.resolve();

  /** Adds a file as if another client had pushed it. */
  seed(fileId: string, path: string, bytes: Uint8Array<ArrayBuffer>, kind = "note"): void {
    const previous = this.ready;
    this.ready = (async () => {
      await previous;
      const hash = await sha256(bytes);
      this.blobs.set(hash, bytes);
      this.commit(fileId, { path, kind, revision: 1, hash, size: bytes.length, deleted: false }, "create");
    })();
  }

  /** Changes a file as if another client had pushed the change. */
  async edit(fileId: string, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
    await this.ready;
    const f = this.files.get(fileId)!;
    const hash = await sha256(bytes);
    this.blobs.set(hash, bytes);
    this.commit(fileId, { ...f, revision: f.revision + 1, hash, size: bytes.length, deleted: false }, "update");
  }

  /** Moves a file as if another client had pushed the move. */
  async move(fileId: string, path: string): Promise<void> {
    await this.ready;
    const f = this.files.get(fileId)!;
    this.commit(fileId, { ...f, path, revision: f.revision + 1 }, "move");
  }

  async remove(fileId: string): Promise<void> {
    await this.ready;
    const f = this.files.get(fileId)!;
    this.commit(fileId, { ...f, revision: f.revision + 1, hash: null, size: 0, deleted: true }, "delete");
  }

  async bytes(fileId: string): Promise<Uint8Array | undefined> {
    await this.ready;
    const hash = this.files.get(fileId)?.hash;
    return hash ? this.blobs.get(hash) : undefined;
  }

  async liveFiles(): Promise<[string, FakeFile][]> {
    await this.ready;
    return [...this.files].filter(([, f]) => !f.deleted);
  }

  private commit(fileId: string, f: FakeFile, op: string): SyncEntry {
    this.files.set(fileId, f);
    this.revisions.set(`${fileId}:${f.revision}`, f.hash);
    const entry = { seq: this.log.length + 1, file_id: fileId, revision: f.revision, path: f.path, kind: f.kind, content_hash: f.hash, size: f.size, deleted: f.deleted, device_id: "fake", op };
    this.log.push(entry);
    return entry;
  }

  /** Answers a sync request, or undefined for any other route. */
  async handle(request: Request): Promise<Response | undefined> {
    const url = new URL(request.url);
    const blob = /^\/api\/v1\/blobs\/([0-9a-f]{64})$/.exec(url.pathname);
    const sync = /^\/api\/v1\/sync\/[^/]+\/(changes|snapshot|push)$/.exec(url.pathname);
    if (!blob && !sync) return undefined;
    await this.ready;
    if (this.offline) throw new TypeError("Failed to fetch");
    if (blob) return this.blob(request, `sha256:${blob[1]}`);
    if (sync![1] === "changes") return this.changes(url.searchParams.get("cursor") ?? "0");
    if (sync![1] === "snapshot") return this.snapshot(url.searchParams.get("page"));
    const { operations } = (await request.json()) as { operations: PushOperation[] };
    this.pushes.push(operations);
    const results = [];
    for (const op of operations) results.push(await this.apply(op));
    return json({ results });
  }

  private async blob(request: Request, hash: string): Promise<Response> {
    const stored = this.blobs.get(hash);
    if (request.method === "GET") return stored ? new Response(stored.slice()) : problem(404, "Blob not found");
    if (request.method === "HEAD") {
      return stored ? new Response(null) : problem(404, "Blob not found", { "Upload-Offset": String(this.uploads.get(hash)?.length ?? 0) });
    }
    if (stored) return new Response(null, { status: 204 });
    const body = new Uint8Array(await request.arrayBuffer());
    const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(request.headers.get("Content-Range") ?? "");
    let whole = body;
    if (range) {
      const [first, , total] = range.slice(1).map(Number);
      const have = this.uploads.get(hash) ?? new Uint8Array();
      if (first !== have.length) return problem(409, "Upload offset mismatch", { "Upload-Offset": String(have.length) });
      whole = new Uint8Array(have.length + body.length);
      whole.set(have);
      whole.set(body, have.length);
      if (whole.length < total) {
        this.uploads.set(hash, whole);
        return new Response(null, { status: 202, headers: { "Upload-Offset": String(whole.length) } });
      }
      this.uploads.delete(hash);
    }
    if ((await sha256(whole)) !== hash) return problem(422, "Hash mismatch");
    this.blobs.set(hash, whole);
    return new Response(null, { status: 204 });
  }

  private changes(cursor: string): Response {
    const after = Number(cursor);
    if (after < this.horizon) return problem(410, "Cursor expired");
    const entries = this.log.filter((e) => e.seq > after).slice(0, 500);
    const last = entries.at(-1)?.seq ?? after;
    return json({ entries, next_cursor: String(last), has_more: last < this.log.length });
  }

  private snapshot(page: string | null): Response {
    // Two files per page, so the tests exercise paging.
    const live = [...this.files].filter(([, f]) => !f.deleted).sort(([, a], [, b]) => (a.path < b.path ? -1 : 1));
    const start = Number(page ?? 0);
    const entries = live.slice(start, start + 2).map(([id]) => ({ ...this.log.findLast((e) => e.file_id === id)! }));
    const next_page = start + 2 < live.length ? String(start + 2) : null;
    return json({ entries, cursor: String(this.log.length), next_page });
  }

  private async apply(op: PushOperation): Promise<PushResult> {
    const prior = this.results.get(op.client_op_id);
    if (prior) return { ...prior, status: "duplicate" };
    const result = await this.plan(op);
    this.results.set(op.client_op_id, result);
    return result;
  }

  private ok(fileId: string, entry: SyncEntry | undefined, status: "applied" | "merged" = "applied", problem: PushResult["problem"] = null): PushResult {
    const f = this.files.get(fileId)!;
    return { status, file_id: fileId, revision: f.revision, seq: entry?.seq ?? null, content_hash: f.hash, path: f.path, problem };
  }

  private rejected(fileId: string, title: string): PushResult {
    return { status: "rejected", file_id: fileId, revision: null, seq: null, content_hash: null, path: null, problem: { type: "about:blank", title, status: 409 } };
  }

  private taken(path: string): boolean {
    return [...this.files.values()].some((f) => !f.deleted && f.path.toLowerCase() === path.toLowerCase());
  }

  private copyPath(path: string): string {
    const dot = path.lastIndexOf(".");
    const [stem, ext] = dot > path.lastIndexOf("/") ? [path.slice(0, dot), path.slice(dot)] : [path, ""];
    let candidate = `${stem} (conflict web 2026-11-19)${ext}`;
    for (let n = 2; this.taken(candidate); n++) candidate = `${stem} (conflict web 2026-11-19) ${n}${ext}`;
    return candidate;
  }

  private copy(original: string, path: string, kind: string, hash: string, baseRevision: number): PushResult {
    const id = crypto.randomUUID();
    const entry = this.commit(id, { path: this.copyPath(path), kind, revision: 1, hash, size: this.blobs.get(hash)!.length, deleted: false }, "create");
    this.conflicts.push({
      id: crypto.randomUUID(),
      vault_id: "",
      file_id: original,
      copy_file_id: id,
      base_revision: baseRevision,
      their_revision: this.files.get(original)!.revision,
      status: "open",
      revision: 1,
      created_at: "2026-11-21T10:00:00.000Z",
      resolved_at: null,
    });
    return { ...this.ok(id, entry), status: "conflict", problem: { type: "about:blank", title: "Edit kept as a conflict copy", status: 409, original_file_id: original } };
  }

  private async plan(op: PushOperation): Promise<PushResult> {
    const f = this.files.get(op.file_id);
    if ("content_hash" in op && !this.blobs.has(op.content_hash)) return this.rejected(op.file_id, "Blob missing");
    switch (op.op) {
      case "create": {
        if (f) return this.rejected(op.file_id, "File id already exists");
        const size = this.blobs.get(op.content_hash)!.length;
        if (!this.taken(op.path)) {
          return this.ok(op.file_id, this.commit(op.file_id, { path: op.path, kind: op.kind, revision: 1, hash: op.content_hash, size, deleted: false }, "create"));
        }
        const entry = this.commit(op.file_id, { path: this.copyPath(op.path), kind: op.kind, revision: 1, hash: op.content_hash, size, deleted: false }, "create");
        return { ...this.ok(op.file_id, entry), status: "conflict", problem: { title: "Edit kept as a conflict copy", original_file_id: "other" } };
      }
      case "update": {
        if (!f) return this.rejected(op.file_id, "File not found");
        let hash = op.content_hash;
        let status: "applied" | "merged" = "applied";
        if (f.deleted) {
          if (this.taken(f.path)) return this.copy(op.file_id, f.path, f.kind, hash, op.base_revision);
        } else if (op.base_revision < f.revision && hash !== f.hash) {
          const base = this.blobs.get(this.revisions.get(`${op.file_id}:${op.base_revision}`) ?? "");
          const merged = base && this.merge?.(base, this.blobs.get(f.hash!)!, this.blobs.get(hash)!);
          if (!merged) return this.copy(op.file_id, f.path, f.kind, hash, op.base_revision);
          hash = await sha256(merged as Uint8Array<ArrayBuffer>);
          this.blobs.set(hash, merged as Uint8Array<ArrayBuffer>);
          status = "merged";
        }
        if (hash === f.hash && !f.deleted) return this.ok(op.file_id, undefined);
        const size = this.blobs.get(hash)!.length;
        return this.ok(op.file_id, this.commit(op.file_id, { ...f, revision: f.revision + 1, hash, size, deleted: false }, "update"), status);
      }
      default:
        return this.rejected(op.file_id, "Unknown operation");
    }
  }
}
