// Roadmap P3-04 acceptance: corpus notes open and save byte-identically through the UI.
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
    if (message.type() === "error") errors.push(message.text()); // CSP violations land here
  });
  const api = await mockApi(page, files);
  await page.goto("/");
  const list = page.getByRole("region", { name: "Note list" });
  const main = page.getByRole("main");

  for (const file of files) {
    const name = file.path.replace(/\.md$/, "");
    await list.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expect(main.getByRole("heading", { name })).toBeVisible();
    if (name.startsWith("enc-")) {
      await expect(main.getByRole("note")).toContainText("not UTF-8");
      continue;
    }
    const before = api.puts.length;
    await main.getByRole("textbox", { name: "Note text" }).click();
    await page.keyboard.press("ControlOrMeta+End");
    await page.keyboard.type("Z");
    await page.keyboard.press("ControlOrMeta+s");
    await expect.poll(() => api.puts.length, { message: name }).toBe(before + 1);
    const put = api.puts.at(-1)!;
    expect(put.ifMatch, name).toBe('"1"');
    expect(put.body.toString("hex"), name).toBe(Buffer.concat([file.bytes, Buffer.from("Z")]).toString("hex"));
    await expect(page.getByRole("contentinfo")).toHaveText("Saved");
  }
  // Nothing else was sent: no PUT for the read-only note, one per editable note.
  expect(api.puts).toHaveLength(files.filter((f) => !f.path.startsWith("enc-")).length);
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
