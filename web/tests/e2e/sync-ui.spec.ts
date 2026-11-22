// Roadmap P5-05 / P5-06 acceptance in the browser: an offline edit that collides with an
// edit from another device becomes a visible conflict that can be resolved, and any
// revision of a note can be restored. Both views pass the WCAG 2.2 AA checks.
import AxeBuilder from "@axe-core/playwright";
import { Buffer } from "node:buffer";
import { expect, test, type Page } from "@playwright/test";

import { mockApi } from "./mock-api";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const violations = async (page: Page) => (await new AxeBuilder({ page }).withTags(WCAG).analyze()).violations.map((v) => v.id);

test("a colliding edit shows as a conflict and is resolved with the copy's text", async ({ page }) => {
  const api = await mockApi(page, [{ path: "Welcome.md", bytes: Buffer.from("# Welcome\n") }]);
  await page.goto("/");
  await page.getByRole("button", { name: /^Welcome/ }).click();
  const text = page.getByRole("main").getByRole("textbox", { name: "Note text" });
  await expect(page.getByRole("contentinfo")).toHaveText("Saved");

  // Edited here while offline, and on another device meanwhile.
  api.offline = true;
  await text.click();
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type("From the browser");
  await page.keyboard.press("ControlOrMeta+s");
  await expect(page.getByRole("contentinfo")).toHaveText("1 change not synced yet (offline)", { timeout: 10_000 });
  await api.sync.edit(api.ids[0], Buffer.from("# Welcome\nFrom the Mac"));
  api.offline = false;
  await page.evaluate(() => dispatchEvent(new Event("online")));

  const nav = page.getByRole("navigation");
  await nav.getByRole("button", { name: /^Conflicts\s*1$/ }).click({ timeout: 15_000 });
  await page.getByRole("region", { name: "Note list" }).getByRole("button", { name: /Copy: Welcome \(conflict/ }).click();
  const diff = page.getByLabel("Differences between note and copy");
  await expect(diff.locator('[data-kind="removed"]')).toHaveText(/From the Mac/);
  await expect(diff.locator('[data-kind="added"]')).toHaveText(/From the browser/);
  expect(await violations(page)).toEqual([]);

  await page.getByRole("toolbar", { name: "Resolve conflict" }).getByRole("button", { name: "Use copy in note" }).click();
  await expect(nav.getByRole("button", { name: /^Conflicts/ })).toHaveCount(0);
  expect(api.sync.conflicts[0].status).toBe("resolved");
  expect(Buffer.from((await api.sync.bytes(api.ids[0]))!).toString()).toBe("# Welcome\nFrom the browser");
  expect((await api.sync.liveFiles()).map(([, f]) => f.path)).toEqual(["Welcome.md"]);
});

test("a note's history shows each revision's changes and restores an old one", async ({ page }) => {
  const api = await mockApi(page, [{ path: "Plan.md", bytes: Buffer.from("# Plan\n\nfirst\n") }]);
  await api.sync.edit(api.ids[0], Buffer.from("# Plan\n\nsecond\n"));
  await page.goto("/");
  await page.getByRole("button", { name: /^Plan/ }).click();
  const main = page.getByRole("main");
  await main.getByRole("toolbar", { name: "Note actions" }).getByRole("button", { name: "History" }).click();

  await expect(main.getByLabel("Changes in this revision").locator('[data-kind="added"]')).toHaveText(/second/);
  expect(await violations(page)).toEqual([]);
  await main.getByRole("list", { name: "Revisions" }).getByRole("button", { name: /Created · revision 1/ }).click();
  await main.getByRole("button", { name: "Restore this revision" }).click();
  await expect(main.getByRole("textbox", { name: "Note text" })).toContainText("first");
  expect(Buffer.from((await api.sync.bytes(api.ids[0]))!).toString()).toBe("# Plan\n\nfirst\n");
});
