// Roadmap P3-04 acceptance: corpus notes open and save byte-identically through the UI
// (through the sync engine since P5-04).
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

import { mockApi } from "./mock-api";

const corpus = path.resolve(import.meta.dirname, "../../../tests/compatibility/vaults");
const files = readdirSync(corpus)
  .filter((name) => existsSync(path.join(corpus, name, "note.md")))
  .map((name) => ({ path: `${name}.md`, bytes: readFileSync(path.join(corpus, name, "note.md")) }));

test("every corpus note saves with its original bytes plus the typed text", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("console", (message) => {
    // CSP violations land here. A blob HEAD answers 404 before every upload (sync protocol §3).
    if (message.type() === "error" && !message.location().url.includes("/api/v1/blobs/")) errors.push(message.text() + " @ " + message.location().url);
  });
  const api = await mockApi(page, files);
  await page.goto("/");
  const list = page.getByRole("region", { name: "Note list" });
  const main = page.getByRole("main");

  for (const [i, file] of files.entries()) {
    const name = file.path.replace(/\.md$/, "");
    await list.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expect(main.getByRole("heading", { name })).toBeVisible();
    if (name.startsWith("enc-")) {
      await expect(main.getByRole("note")).toContainText("not UTF-8");
      continue;
    }
    const before = api.ops().length;
    await main.getByRole("textbox", { name: "Note text" }).click();
    await page.keyboard.press("ControlOrMeta+End");
    await page.keyboard.type("Z");
    await page.keyboard.press("ControlOrMeta+s");
    await expect.poll(() => api.ops().length, { message: name, timeout: 10_000 }).toBe(before + 1);
    expect(api.ops().at(-1), name).toMatchObject({ op: "update", file_id: api.ids[i], base_revision: 1 });
    const saved = Buffer.from((await api.sync.bytes(api.ids[i]))!);
    expect(saved.toString("hex"), name).toBe(Buffer.concat([file.bytes, Buffer.from("Z")]).toString("hex"));
    await expect(page.getByRole("contentinfo")).toHaveText("Saved");
  }
  // Nothing else was sent: no push for the read-only note, one update per editable note.
  expect(api.ops()).toHaveLength(files.filter((f) => !f.path.startsWith("enc-")).length);
  expect(errors).toEqual([]);
});

test("the editor is styled under the production CSP", async ({ page }) => {
  await mockApi(page, [{ path: "Styled.md", bytes: Buffer.from("# Heading\n\nSee [[Other note]].\n") }]);
  await page.goto("/");
  await page.getByRole("button", { name: /^Styled/ }).click();
  const link = page.getByTestId("note-editor").locator(".cm-wikilink");
  await expect(link).toHaveCSS("text-decoration-line", "underline");
  const heading = page.getByTestId("note-editor").locator(".cm-line").first().locator("span").first();
  await expect(heading).toHaveCSS("font-weight", "700");
});

test("frontmatter is not styled as a heading", async ({ page }) => {
  await mockApi(page, [{ path: "Front.md", bytes: Buffer.from("---\ntags: [a]\n---\nBody\n") }]);
  await page.goto("/");
  await page.getByRole("button", { name: /^Front/ }).click();
  const editor = page.getByTestId("note-editor");
  await expect(editor.locator(".cm-line").nth(1)).toHaveText("tags: [a]");
  for (const span of await editor.locator(".cm-line").nth(1).locator("span").all()) {
    await expect(span).not.toHaveCSS("font-weight", "700");
  }
});
