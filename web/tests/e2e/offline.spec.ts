// Roadmap P3-08 / P5-04 acceptance: an offline edit survives a reload and syncs when online.
import { Buffer } from "node:buffer";
import { expect, test } from "@playwright/test";

import { mockApi } from "./mock-api";

const file = { path: "Welcome.md", bytes: Buffer.from("# Welcome\n") };

test("an offline edit survives a reload and syncs when the network is back", async ({ page }) => {
  const api = await mockApi(page, [file]);
  await page.goto("/");
  await page.getByRole("button", { name: /^Welcome/ }).click();
  const text = page.getByRole("main").getByRole("textbox", { name: "Note text" });
  await expect(text).toBeVisible();
  await expect(page.getByRole("contentinfo")).toHaveText("Saved");

  api.offline = true;
  await text.click();
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type("Z");
  await page.keyboard.press("ControlOrMeta+s");
  await expect(page.getByRole("contentinfo")).toHaveText("1 change not synced yet (offline)", { timeout: 10_000 });

  await page.reload();
  await page.getByRole("button", { name: /^Welcome/ }).click();
  await expect(page.getByRole("main").getByRole("textbox", { name: "Note text" })).toContainText("Z");
  expect(api.ops()).toHaveLength(0);

  api.offline = false;
  await page.evaluate(() => dispatchEvent(new Event("online")));
  await expect.poll(() => api.ops().length).toBe(1);
  expect(Buffer.from((await api.sync.bytes(api.ids[0]))!).toString()).toBe("# Welcome\nZ");
  await expect(page.getByRole("contentinfo")).toHaveText("Saved");
});
