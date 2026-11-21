// Roadmap P3-01 (login flow), P3-03 (note list) and P3-07 (attachments) through the
// production build under the production CSP.
import { Buffer } from "node:buffer";
import { expect, test, type Page } from "@playwright/test";

import { mockApi } from "./mock-api";

const notes = [
  { path: "Welcome.md", bytes: Buffer.from("# Welcome\n\nSee [[Plan]].\n") },
  { path: "Plan.md", bytes: Buffer.from("# Plan\n") },
];

// A 1x1 PNG.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");

function cspViolations(page: Page): string[] {
  const seen: string[] = [];
  page.on("console", (m) => m.type() === "error" && /Content Security Policy/.test(m.text()) && seen.push(m.text()));
  return seen;
}

test("login flow: sign in, see the notes, sign out", async ({ page }) => {
  const csp = cspViolations(page);
  const api = await mockApi(page, notes, { signedIn: false });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to OpenNote" })).toBeVisible();
  await page.getByLabel("Username").fill("e2e");
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Wrong username or password.");

  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: /^Welcome/ })).toBeVisible();
  expect(api.rest.signedIn).toBe(true);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to OpenNote" })).toBeVisible();
  expect(api.rest.signedIn).toBe(false);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in to OpenNote" })).toBeVisible();
  expect(csp).toEqual([]);
});

test("note list: create, rename, favorite, archive, delete and restore", async ({ page }) => {
  const csp = cspViolations(page);
  const api = await mockApi(page, notes);
  await page.goto("/");
  const nav = page.getByRole("navigation");
  const list = page.getByRole("region", { name: "Note list" });
  const actions = page.getByRole("toolbar", { name: "Note actions" });

  await nav.getByRole("button", { name: "New note" }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("Ideas");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("main").getByRole("heading", { name: "Ideas" })).toBeVisible();
  await expect(list.getByRole("button", { name: /^Ideas/ })).toBeVisible();

  await actions.getByRole("button", { name: "Rename" }).click();
  await page.getByRole("dialog").getByLabel("Path in the vault").fill("Better ideas");
  await page.getByRole("dialog").getByRole("button", { name: "Rename" }).click();
  await expect(page.getByRole("main").getByRole("heading", { name: "Better ideas" })).toBeVisible();

  await actions.getByRole("button", { name: "☆ Favorite" }).click();
  await expect(actions.getByRole("button", { name: "★ Favorite" })).toHaveAttribute("aria-pressed", "true");
  await nav.getByRole("button", { name: "Favorites" }).click();
  await expect(list.getByRole("button", { name: /^Better ideas/ })).toBeVisible();
  await expect(list.getByRole("button", { name: /^Plan/ })).toHaveCount(0);

  await actions.getByRole("button", { name: "Archive" }).click();
  await nav.getByRole("button", { name: "All notes" }).click();
  await expect(list.getByRole("button", { name: /^Plan/ })).toBeVisible();
  await expect(list.getByRole("button", { name: /^Better ideas/ })).toHaveCount(0);

  await page.getByRole("button", { name: /^Plan/ }).click();
  await actions.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(list.getByRole("button", { name: /^Plan/ })).toHaveCount(0);
  await nav.getByRole("button", { name: "Trash" }).click();
  await list.getByRole("button", { name: "Restore" }).click();
  await expect(list.getByText("Trash is empty")).toBeVisible();
  expect((await api.sync.liveFiles()).map(([, f]) => f.path).sort()).toEqual(["Better ideas.md", "Plan.md", "Welcome.md"]);
  expect(csp).toEqual([]);
});

test("attachments: upload embeds the file and the image shows under the production CSP", async ({ page }) => {
  const csp = cspViolations(page);
  const api = await mockApi(page, notes);
  await page.goto("/");
  await page.getByRole("button", { name: /^Welcome/ }).click();
  await expect(page.getByRole("main").getByRole("textbox", { name: "Note text" })).toBeVisible();
  await page.getByLabel("Attachment file").setInputFiles({ name: "dot.png", mimeType: "image/png", buffer: PNG });
  const text = page.getByRole("main").getByRole("textbox", { name: "Note text" });
  await expect(text).toContainText("![[dot.png]]");
  const image = page.getByTestId("note-editor").locator("img.cm-embed-image");
  await expect(image).toBeVisible();
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);
  expect((await api.sync.liveFiles()).some(([, f]) => f.path === "dot.png" && f.kind === "attachment")).toBe(true);
  expect(csp).toEqual([]);
});

test("search: hints while typing, results with marked matches", async ({ page }) => {
  await mockApi(page, notes);
  await page.goto("/");
  const box = page.getByRole("searchbox", { name: "Search notes" });
  await box.click();
  await expect(page.getByRole("group", { name: "Search syntax" })).toBeVisible();
  await box.fill("Plan");
  await box.press("Enter");
  const list = page.getByRole("region", { name: "Note list" });
  await expect(list.getByRole("heading", { name: "Search: Plan" })).toBeVisible();
  await expect(list.locator("mark").first()).toHaveText("Plan");
});
