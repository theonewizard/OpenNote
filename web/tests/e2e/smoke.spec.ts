import { expect, test } from "@playwright/test";

test("app loads at phone width without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 }); await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  expect(overflow).toBe(false);
});

test("app renders the main pane", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) problems.push(`${response.status()} ${response.url()}`);
  });
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  expect(problems).toEqual([]);
});
