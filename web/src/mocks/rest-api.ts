// An in-memory stand-in for the v1 REST routes the web app uses besides sync (auth, notes,
// folders, tags, search, attachments, vault settings), on top of FakeSyncServer, which
// holds the files. It speaks the Fetch API like FakeSyncServer, so the unit tests (MSW),
// `npm run dev:mock` and Playwright (page.route) share it. It models what the UI relies
// on, not the server's full rules (no frontmatter rewriting, no real search grammar).
import type { Attachment, NoteMeta, User, Vault } from "@/api/types";
import type { FakeSyncServer } from "@/mocks/sync-server";

const json = (body: unknown, status = 200) => Response.json(body, { status });
const problem = (status: number, title: string) =>
  Response.json({ type: "about:blank", title, status }, { status, headers: { "Content-Type": "application/problem+json" } });
const NOW = "2026-11-21T10:00:00.000Z";

export interface RestOptions {
  vault: Vault;
  user: User;
  /** Login accepts this username with the password "correct horse battery" */
  signedIn?: boolean;
  /** Initial tags and frontmatter properties by note id */
  meta?: Map<string, Pick<NoteMeta, "tags" | "properties">>;
  loginMethods?: string[];
}

interface Deleted {
  path: string;
  revision: number;
  last_content_revision: number;
  bytes: Uint8Array<ArrayBuffer>;
}

export class FakeRestApi {
  signedIn: boolean;
  readonly vaults: Vault[];
  readonly user: User;
  readonly loginMethods: string[];
  readonly tags = new Map<string, string[]>();
  readonly properties = new Map<string, Record<string, unknown> | null>();
  readonly folders = new Set<string>();
  readonly deleted = new Map<string, Deleted>();
  readonly mediaTypes = new Map<string, string>();
  members: { user_id: string; username: string; display_name: string; role: string }[];
  devices = [
    { id: "0192a0c4-0000-7000-8000-0000000d0001", name: "Web", platform: "web", created_at: NOW, last_seen_at: NOW, current: true },
    { id: "0192a0c4-0000-7000-8000-0000000d0002", name: "MacBook", platform: "macos", created_at: NOW, last_seen_at: NOW, current: false },
  ];
  readonly users: User[];
  private readonly sync: FakeSyncServer;

  constructor(sync: FakeSyncServer, options: RestOptions) {
    this.sync = sync;
    this.vaults = [options.vault];
    this.user = options.user;
    this.signedIn = options.signedIn ?? true;
    this.loginMethods = options.loginMethods ?? ["password"];
    for (const [id, m] of options.meta ?? []) {
      this.tags.set(id, m.tags);
      this.properties.set(id, m.properties);
    }
    this.members = [{ user_id: options.user.id, username: options.user.username, display_name: options.user.display_name, role: "owner" }];
    this.users = [
      options.user,
      { ...options.user, id: "0192a0c4-0000-7000-8000-00000000b0b0", username: "bob", display_name: "Bob", is_admin: false },
    ];
  }

  private async note(id: string): Promise<NoteMeta | undefined> {
    const f = (await this.sync.liveFiles()).find(([fid, file]) => fid === id && file.kind === "note")?.[1];
    if (!f) return undefined;
    return {
      id,
      vault_id: this.vaults[0].id,
      path: f.path,
      title: f.path.split("/").at(-1)!.replace(/\.md$/, ""),
      revision: f.revision,
      content_hash: f.hash!,
      size: f.size,
      created_at: NOW,
      modified_at: NOW,
      modified_by_device: "web",
      tags: this.tags.get(id) ?? [],
      aliases: [],
      properties: this.properties.get(id) ?? null,
      frontmatter_error: false,
      read_only: false,
      path_warning: null,
      has_id_in_file: false,
    };
  }

  private async notes(): Promise<NoteMeta[]> {
    const ids = (await this.sync.liveFiles()).filter(([, f]) => f.kind === "note").map(([id]) => id);
    return (await Promise.all(ids.map((id) => this.note(id)))).filter((n): n is NoteMeta => !!n);
  }

  private async attachments(): Promise<Attachment[]> {
    return (await this.sync.liveFiles())
      .filter(([, f]) => f.kind === "attachment")
      .map(([id, f]) => ({
        id,
        vault_id: this.vaults[0].id,
        path: f.path,
        revision: f.revision,
        content_hash: f.hash!,
        size: f.size,
        media_type: this.mediaTypes.get(id) ?? "application/octet-stream",
        created_at: NOW,
        modified_at: NOW,
      }));
  }

  private async taken(path: string) {
    return (await this.sync.liveFiles()).some(([, f]) => f.path.toLowerCase() === path.toLowerCase());
  }

  private stale(request: Request, revision: number) {
    return request.headers.get("If-Match") !== `"${revision}"`;
  }

  /** Answers a REST request, or undefined for a route it does not serve. */
  async handle(request: Request): Promise<Response | undefined> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const params = url.searchParams;
    const method = request.method;
    const route = (m: string, pattern: RegExp) => (method === m ? pattern.exec(path) : null);
    let match: RegExpExecArray | null;

    if (route("GET", /^\/meta$/)) {
      return json({ server_version: "0.0.0-mock", api_versions: ["v1"], sync_protocol_versions: [1], login_methods: this.loginMethods });
    }
    if (route("POST", /^\/auth\/login$/)) {
      const body = (await request.json()) as { username: string; password: string; auth_request?: string };
      if (body.username !== this.user.username || body.password !== "correct horse battery") return problem(401, "Invalid credentials");
      this.signedIn = true;
      const redirect_to = body.auth_request ? `/native-callback?code=mock&state=${body.auth_request}` : null;
      return json({ user: this.user, csrf_token: "csrf", redirect_to });
    }
    if (!this.signedIn) return /^\/(sync|blobs)\//.test(path) ? undefined : problem(401, "Not authenticated");
    if (route("POST", /^\/auth\/logout$/)) {
      this.signedIn = false;
      return new Response(null, { status: 204 });
    }
    if (route("GET", /^\/me$/)) return json(this.user);

    // Vaults, members, users, devices
    if (route("GET", /^\/vaults$/)) return json({ items: this.vaults, next_cursor: null });
    if (route("POST", /^\/vaults$/)) {
      const body = (await request.json()) as { name: string };
      const vault = { ...this.vaults[0], id: crypto.randomUUID(), name: body.name, revision: 1 };
      this.vaults.push(vault);
      return json(vault, 201);
    }
    if ((match = route("PATCH", /^\/vaults\/([^/]+)$/))) {
      const vault = this.vaults.find((v) => v.id === match![1]);
      if (!vault) return problem(404, "Vault not found");
      if (this.stale(request, vault.revision)) return problem(412, "Precondition failed");
      const body = (await request.json()) as { name?: string; settings?: Partial<Vault["settings"]> };
      Object.assign(vault, { name: body.name ?? vault.name, settings: { ...vault.settings, ...body.settings }, revision: vault.revision + 1 });
      return json(vault);
    }
    if ((match = route("DELETE", /^\/vaults\/([^/]+)$/))) {
      const index = this.vaults.findIndex((v) => v.id === match![1]);
      if (index < 0) return problem(404, "Vault not found");
      this.vaults.splice(index, 1);
      return new Response(null, { status: 204 });
    }
    if (route("GET", /^\/vaults\/[^/]+\/members$/)) return json({ items: this.members, next_cursor: null });
    if ((match = route("PUT", /^\/vaults\/[^/]+\/members\/([^/]+)$/))) {
      const { role } = (await request.json()) as { role: string };
      const existing = this.members.find((m) => m.user_id === match![1]);
      const user = this.users.find((u) => u.id === match![1]);
      if (existing) existing.role = role;
      else if (user) this.members.push({ user_id: user.id, username: user.username, display_name: user.display_name, role });
      else return problem(404, "User not found");
      return json(this.members.find((m) => m.user_id === match![1]));
    }
    if ((match = route("DELETE", /^\/vaults\/[^/]+\/members\/([^/]+)$/))) {
      this.members = this.members.filter((m) => m.user_id !== match![1]);
      return new Response(null, { status: 204 });
    }
    if (route("GET", /^\/users$/)) return this.user.is_admin ? json({ items: this.users, next_cursor: null }) : problem(403, "Forbidden");
    if (route("GET", /^\/devices$/)) return json({ items: this.devices, next_cursor: null });
    if ((match = route("DELETE", /^\/devices\/([^/]+)$/))) {
      this.devices = this.devices.filter((d) => d.id !== match![1]);
      return new Response(null, { status: 204 });
    }

    // Folders
    if (route("GET", /^\/folders$/)) {
      const paths = new Set(this.folders);
      for (const [, f] of await this.sync.liveFiles()) {
        const parts = f.path.split("/").slice(0, -1);
        parts.forEach((_, i) => paths.add(parts.slice(0, i + 1).join("/")));
      }
      const items = [...paths].sort().map((p) => ({
        path: p,
        name: p.split("/").at(-1)!,
        parent: p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : null,
        note_count: 0,
        attachment_count: 0,
      }));
      return json({ items });
    }
    if (route("POST", /^\/folders$/)) {
      const body = (await request.json()) as { path: string };
      this.folders.add(body.path);
      return json({ path: body.path, name: body.path.split("/").at(-1), parent: null, note_count: 0, attachment_count: 0 }, 201);
    }
    if (route("PATCH", /^\/folders$/)) {
      const body = (await request.json()) as { path: string; new_path: string };
      for (const [id, f] of await this.sync.liveFiles()) {
        if (f.path.startsWith(`${body.path}/`)) await this.sync.move(id, body.new_path + f.path.slice(body.path.length));
      }
      if (this.folders.delete(body.path)) this.folders.add(body.new_path);
      return json({ path: body.new_path, name: body.new_path.split("/").at(-1), parent: null, note_count: 0, attachment_count: 0 });
    }
    if (route("DELETE", /^\/folders$/)) {
      const folder = params.get("path")!;
      if ((await this.sync.liveFiles()).some(([, f]) => f.path.startsWith(`${folder}/`))) return problem(409, "Folder not empty");
      this.folders.delete(folder);
      return new Response(null, { status: 204 });
    }

    // Notes
    if (route("GET", /^\/notes$/)) {
      const folder = params.get("folder");
      const tag = params.get("tag");
      const sort = params.get("sort") ?? "path";
      const key = sort.replace(/^-/, "") as "path" | "title";
      const items = (await this.notes())
        .filter((n) => folder === null || n.path.slice(0, Math.max(n.path.lastIndexOf("/"), 0)) === folder)
        .filter((n) => tag === null || n.tags.includes(tag))
        .sort((a, b) => String(a[key]).localeCompare(String(b[key])) * (sort.startsWith("-") ? -1 : 1));
      const start = Number(params.get("cursor") ?? 0);
      const end = start + Number(params.get("limit") ?? 50);
      return json({ items: items.slice(start, end), next_cursor: end < items.length ? String(end) : null });
    }
    if (route("POST", /^\/notes$/)) {
      const body = (await request.json()) as { path: string; content?: string | null };
      if (await this.taken(body.path)) return problem(409, "A file with this path exists");
      const id = crypto.randomUUID();
      this.sync.seed(id, body.path, new TextEncoder().encode(body.content ?? ""));
      return json(await this.note(id), 201);
    }
    if ((match = route("GET", /^\/notes\/([^/]+)$/))) {
      const note = await this.note(match[1]);
      return note ? json(note) : problem(404, "Note not found");
    }
    if ((match = /^\/notes\/([^/]+)(?:\/(rename|restore|links))?$/.exec(path))) {
      const id = match[1];
      const action = match[2];
      if (method === "POST" && action === "restore") {
        const gone = this.deleted.get(id);
        if (!gone) return problem(404, "Note not found");
        if (this.stale(request, gone.revision)) return problem(412, "Precondition failed");
        await this.sync.edit(id, gone.bytes);
        this.deleted.delete(id);
        return json(await this.note(id));
      }
      const note = await this.note(id);
      if (!note) return problem(404, "Note not found");
      if (method === "GET" && action === "links") return json(await this.links(note));
      if (this.stale(request, note.revision)) return problem(412, "Precondition failed");
      if (method === "DELETE" && !action) {
        const bytes = (await this.sync.bytes(id)) as Uint8Array<ArrayBuffer>;
        await this.sync.remove(id);
        this.deleted.set(id, { path: note.path, revision: note.revision + 1, last_content_revision: note.revision, bytes });
        return new Response(null, { status: 204 });
      }
      if (method === "POST" && action === "rename") {
        const body = (await request.json()) as { path: string };
        if (await this.taken(body.path)) return problem(409, "A file with this path exists");
        await this.sync.move(id, body.path);
        return json({ note: await this.note(id), updated: [], skipped: [] });
      }
      if (method === "PATCH" && !action) {
        const body = (await request.json()) as { tags?: string[]; opennote?: Record<string, unknown> };
        if (body.tags) this.tags.set(id, body.tags);
        if (body.opennote) this.properties.set(id, { ...(note.properties ?? {}), opennote: body.opennote });
        await this.sync.edit(id, (await this.sync.bytes(id)) as Uint8Array<ArrayBuffer>); // a new revision
        return json(await this.note(id));
      }
    }
    if (route("GET", /^\/vaults\/[^/]+\/deleted-notes$/)) {
      const items = [...this.deleted].map(([id, d]) => ({ id, vault_id: this.vaults[0].id, path: d.path, revision: d.revision, last_content_revision: d.last_content_revision, deleted_at: NOW }));
      return json({ items, next_cursor: null });
    }

    // Tags and search
    if (route("GET", /^\/tags$/)) {
      const counts = new Map<string, number>();
      for (const n of await this.notes()) for (const t of n.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
      return json({ items: [...counts].sort().map(([name, count]) => ({ name, count })), next_cursor: null });
    }
    if (route("GET", /^\/search$/)) return json({ items: await this.search(params.get("q") ?? ""), next_cursor: null });

    // Attachments
    if (route("GET", /^\/attachments$/)) {
      const folder = params.get("folder");
      const items = (await this.attachments()).filter((a) => folder === null || a.path.slice(0, Math.max(a.path.lastIndexOf("/"), 0)) === folder);
      return json({ items, next_cursor: null });
    }
    if (route("POST", /^\/attachments$/)) {
      const form = await request.formData();
      const file = form.get("file") as File;
      const filePath = String(form.get("path"));
      if (await this.taken(filePath)) return problem(409, "A file with this path exists");
      const id = crypto.randomUUID();
      this.mediaTypes.set(id, file.type || "application/octet-stream");
      this.sync.seed(id, filePath, new Uint8Array(await file.arrayBuffer()), "attachment");
      return json((await this.attachments()).find((a) => a.id === id), 201);
    }
    if ((match = route("GET", /^\/attachments\/([^/]+)\/content$/))) {
      const bytes = await this.sync.bytes(match[1]);
      if (!bytes) return problem(404, "Attachment not found");
      return new Response(bytes.slice(), { headers: { "Content-Type": this.mediaTypes.get(match[1]) ?? "application/octet-stream" } });
    }
    if ((match = route("DELETE", /^\/attachments\/([^/]+)$/))) {
      await this.sync.remove(match[1]);
      return new Response(null, { status: 204 });
    }
    return undefined;
  }

  private async links(note: NoteMeta) {
    const text = new TextDecoder().decode(await this.sync.bytes(note.id));
    const all = await this.notes();
    const outgoing = [...text.matchAll(/(!?)\[\[([^\]\r\n]+)\]\]/g)].map((m) => {
      const target = m[2].split("|")[0].split("#")[0].trim();
      const found = all.find((n) => n.path === `${target}.md` || n.path === target || n.title === target);
      return { target, alias: null, heading: null, block: null, embed: m[1] === "!", resolved: found ? { id: found.id, path: found.path, title: found.title } : null };
    });
    return { outgoing, incoming: [], unresolved: outgoing.filter((o) => !o.resolved).map((o) => o.target) };
  }

  private async search(q: string) {
    const terms = q.split(/\s+/).filter(Boolean);
    const hits = [];
    for (const n of await this.notes()) {
      const text = new TextDecoder().decode(await this.sync.bytes(n.id));
      let snippet: string | null = null;
      const ok = terms.every((term) => {
        const [key, value] = term.includes(":") ? term.split(":", 2) : ["", term];
        if (key === "is") return (n.properties?.opennote as Record<string, unknown> | undefined)?.[value] === true;
        if (key === "tag") return n.tags.includes(value);
        const at = text.toLowerCase().indexOf(term.toLowerCase());
        if (at < 0 && !n.title.toLowerCase().includes(term.toLowerCase())) return false;
        if (at >= 0) snippet = `${text.slice(Math.max(0, at - 20), at)}«${text.slice(at, at + term.length)}»${text.slice(at + term.length, at + term.length + 20)}`;
        return true;
      });
      if (ok) hits.push({ note: n, snippet, score: 1 });
    }
    return hits;
  }
}
