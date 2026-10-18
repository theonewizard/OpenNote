import { expect, test } from "@playwright/test";

test("app loads at phone width without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 }); await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  expect(overflow).toBe(false);
});

test("app renders the main pane", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
});
