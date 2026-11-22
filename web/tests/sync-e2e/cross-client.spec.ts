// Roadmap P5-09: the web app and the Apple sync engine against one real server, in the
// order a person would meet them (milestone M5: offline edits sync, a concurrent edit is
// never overwritten, direct edits in the server's vault propagate). The Apple side is
// `opennote-sync`, one SyncEngine round from the command line over the Apple package's
// code, until the Apple apps exist (Phase 4). Started by scripts/sync-e2e.sh.
import { execFile } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const env = (name: string) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set (scripts/sync-e2e.sh sets it)`);
  return value;
};
const API = process.env.OPENNOTE_E2E_API ?? "http://127.0.0.1:8000";
const USER = env("OPENNOTE_E2E_USER");
const PASSWORD = env("OPENNOTE_E2E_PASSWORD");

let api: APIRequestContext;
let csrf: string;
let vault: { id: string; name: string };
let serverDir: string; // the vault's folder on the server, as Obsidian would edit it
let mac: { root: string; support: string; token: string };
let page: Page;

/** One sync round of the Apple engine; returns what it printed (flagged files). */
async function macSync(): Promise<string> {
  const { stdout } = await promisify(execFile)(env("OPENNOTE_SYNC_CLI"), [API, vault.id, mac.root, mac.support], {
    env: { ...process.env, OPENNOTE_TOKEN: mac.token },
    timeout: 60_000,
  });
  return stdout;
}

const onMac = (name: string) => path.join(mac.root, name);
const macText = (name: string) => readFile(onMac(name), "utf8");

/** The note's bytes on the server, by path. */
async function serverText(notePath: string): Promise<string | undefined> {
  const notes = (await (await api.get(`/api/v1/notes?vault_id=${vault.id}&limit=200`)).json()) as { items: { id: string; path: string }[] };
  const note = notes.items.find((n) => n.path === notePath);
  return note && (await api.get(`/api/v1/notes/${note.id}/content`)).text();
}

const list = () => page.getByRole("region", { name: "Note list" });
const editor = () => page.getByRole("main").getByRole("textbox", { name: "Note text" });

async function openNote(title: string) {
  await page.getByRole("navigation").getByRole("button", { name: "All notes" }).click();
  await list().getByRole("button", { name: new RegExp(`^${title}`) }).first().click();
  await expect(editor()).toBeVisible();
}

/** Replaces `from` with `to` in the open note, then saves. */
async function editInBrowser(from: string, to: string) {
  await editor().locator(".cm-line", { hasText: from }).click();
  await page.keyboard.press("End");
  await page.keyboard.press("Shift+Home");
  await page.keyboard.type(to);
  await page.keyboard.press("ControlOrMeta+s");
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  api = await request.newContext({ baseURL: API });
  const login = await api.post("/api/v1/auth/login", { data: { username: USER, password: PASSWORD } });
  expect(login.ok(), await login.text()).toBe(true);
  csrf = ((await login.json()) as { csrf_token: string }).csrf_token;

  // A vault in a folder the test knows, so it can edit the server's copy directly.
  const name = `e2e-${Date.now()}`;
  serverDir = path.join(env("OPENNOTE_E2E_VAULT_ROOT"), name);
  await mkdir(serverDir);
  const created = await api.post("/api/v1/vaults", { data: { name, directory: name }, headers: { "X-CSRF-Token": csrf } });
  expect(created.ok(), await created.text()).toBe(true);
  vault = await created.json();

  // The Mac signs in as the Apple app does: authorization code with PKCE, then a device token.
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const query = new URLSearchParams({
    response_type: "code",
    client_id: "opennote-apple",
    redirect_uri: "opennote://auth/callback",
    code_challenge: challenge,
    code_challenge_method: "S256",
    state: "e2e",
  });
  const authorize = await api.get(`/api/v1/auth/authorize?${query}`, { maxRedirects: 0 });
  const code = new URL(authorize.headers().location).searchParams.get("code");
  expect(code, `authorize answered ${authorize.status()}`).toBeTruthy();
  const token = await api.post("/api/v1/auth/token", {
    form: {
      grant_type: "authorization_code",
      client_id: "opennote-apple",
      code: code!,
      code_verifier: verifier,
      redirect_uri: "opennote://auth/callback",
      device_name: "E2E Mac",
      device_platform: "macos",
    },
  });
  expect(token.ok(), await token.text()).toBe(true);
  const base = await mkdtemp(path.join(tmpdir(), "opennote-mac-"));
  mac = { root: path.join(base, "vault"), support: path.join(base, "support"), token: ((await token.json()) as { access_token: string }).access_token };
  await mkdir(mac.root);
  await mkdir(mac.support);

  page = await browser.newPage();
  await page.goto("/");
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const picker = page.getByRole("combobox", { name: "Vault" });
  await expect(picker.or(page.getByRole("heading", { name }))).toBeVisible();
  if (await picker.isVisible()) await picker.selectOption({ label: name });
  await expect(page.getByRole("navigation").getByRole("heading", { name })).toBeVisible();
});

test.afterAll(async () => {
  await page?.close();
  await api?.dispose();
});

test("a note written on the Mac shows in the web app without a reload", async () => {
  await writeFile(onMac("Mac note.md"), "# Mac note\n\nwritten on the Mac\n\nlast line\n");
  expect(await macSync()).toBe("");
  // The server's change hint wakes the web engine, which pulls and refreshes the list.
  await expect(list().getByRole("button", { name: /^Mac note/ })).toBeVisible();
  await openNote("Mac note");
  await expect(editor()).toContainText("written on the Mac");
});

test("an edit in the web app reaches the Mac", async () => {
  await editInBrowser("last line", "last line, edited in the browser");
  await expect.poll(() => serverText("Mac note.md")).toContain("edited in the browser");
  await macSync();
  expect(await macText("Mac note.md")).toBe("# Mac note\n\nwritten on the Mac\n\nlast line, edited in the browser\n");
});

test("edits to different lines on both sides are merged, on both sides", async () => {
  await writeFile(onMac("Mac note.md"), "# Mac note\n\nwritten on the Mac, then changed on the Mac\n\nlast line, edited in the browser\n");
  await editInBrowser("last line, edited in the browser", "last line, edited in the browser twice");
  await expect.poll(() => serverText("Mac note.md")).toContain("edited in the browser twice");
  await macSync(); // the Mac's edit was made on the older revision: the server merges it
  await macSync();
  const merged = "# Mac note\n\nwritten on the Mac, then changed on the Mac\n\nlast line, edited in the browser twice\n";
  expect(await macText("Mac note.md")).toBe(merged);
  expect(await serverText("Mac note.md")).toBe(merged);
  await expect(editor()).toContainText("then changed on the Mac");
});

test("the same line changed on both while the browser is offline: a conflict copy, nothing lost", async () => {
  await page.context().setOffline(true);
  await editInBrowser("written on the Mac, then changed on the Mac", "the browser's version of this line");
  await expect(page.getByRole("contentinfo")).toContainText("not synced");
  await writeFile(onMac("Mac note.md"), "# Mac note\n\nthe Mac's version of this line\n\nlast line, edited in the browser twice\n");
  await macSync();
  await page.context().setOffline(false);
  await page.evaluate(() => dispatchEvent(new Event("online")));

  const conflicts = page.getByRole("navigation").getByRole("button", { name: /^Conflicts\s*1$/ });
  await expect(conflicts).toBeVisible();
  await macSync();
  const copies = (await readdir(mac.root)).filter((f) => f.startsWith("Mac note (conflict"));
  expect(copies).toHaveLength(1);
  expect(await macText("Mac note.md")).toContain("the Mac's version of this line");
  expect(await macText(copies[0])).toContain("the browser's version of this line");

  // Resolved in the web app with the browser's text; the Mac follows.
  await conflicts.click();
  await list().getByRole("button", { name: /Copy: Mac note \(conflict/ }).click();
  await page.getByRole("toolbar", { name: "Resolve conflict" }).getByRole("button", { name: "Use copy in note" }).click();
  await expect(conflicts).toHaveCount(0);
  await macSync();
  expect(await macText("Mac note.md")).toContain("the browser's version of this line");
  expect(existsSync(onMac(copies[0]))).toBe(false);
});

test("a note written straight into the server's vault (Obsidian there) reaches both", async () => {
  await page.getByRole("navigation").getByRole("button", { name: "All notes" }).click();
  await writeFile(path.join(serverDir, "Obsidian.md"), "# Obsidian\n\nwritten on the server\n");
  await expect(list().getByRole("button", { name: /^Obsidian/ })).toBeVisible({ timeout: 30_000 }); // vault watcher, then hint
  await expect
    .poll(async () => (await macSync(), existsSync(onMac("Obsidian.md"))), { timeout: 30_000 })
    .toBe(true);
  expect(await macText("Obsidian.md")).toBe("# Obsidian\n\nwritten on the server\n");
});

test("a move on the Mac and a delete in the web app reach the other side", async () => {
  await mkdir(onMac("Moved"));
  await rename(onMac("Obsidian.md"), onMac("Moved/Obsidian.md"));
  await macSync();
  await expect.poll(() => serverText("Moved/Obsidian.md")).toContain("written on the server");
  await expect(page.getByRole("navigation").getByRole("button", { name: "Moved" })).toBeVisible();
  expect(existsSync(path.join(serverDir, "Moved", "Obsidian.md"))).toBe(true);

  await openNote("Obsidian");
  await page.getByRole("toolbar", { name: "Note actions" }).getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(list().getByRole("button", { name: /^Obsidian/ })).toHaveCount(0);
  await expect.poll(() => serverText("Moved/Obsidian.md")).toBeUndefined();
  await macSync();
  expect(existsSync(onMac("Moved/Obsidian.md"))).toBe(false);
});
