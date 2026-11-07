// Roadmap P3-10 acceptance: usable at 375 px and installable.
import { Buffer } from "node:buffer";
import { expect, test } from "@playwright/test";

import { mockApi } from "./mock-api";

const files = [
  { path: "Welcome.md", bytes: Buffer.from("# Welcome\n\nA [[wiki link]] and a long line ".repeat(8) + "\n") },
];

test("phone width: one pane at a time, no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await mockApi(page, files);
  await page.goto("/");
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth);

  await page.getByRole("button", { name: "All notes" }).click();
  await expect(page.getByRole("navigation")).toBeHidden();
  await page.getByRole("button", { name: /^Welcome/ }).click();
  await expect(page.getByRole("region", { name: "Note list" })).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Note text" })).toBeVisible();
  expect(await overflow()).toBe(false);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("region", { name: "Note list" })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  expect(await overflow()).toBe(false);
});

test("installable: manifest with icons, and a service worker that serves the shell offline", async ({
  page,
  context,
}) => {
  await mockApi(page, files);
  await page.goto("/");

  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  const manifest = await (await page.request.get(href!)).json();
  expect(manifest).toMatchObject({ name: "OpenNote", start_url: "/", display: "standalone" });
  const sizes = manifest.icons.map((icon: { sizes: string }) => icon.sizes);
  expect(sizes).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  for (const icon of manifest.icons) expect((await page.request.get(icon.src)).ok()).toBe(true);

  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.unrouteAll(); // the API mock would answer even offline
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText("OpenNote", { exact: true })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toHaveText("Not connected");
});
