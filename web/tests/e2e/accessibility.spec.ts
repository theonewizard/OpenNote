// P8-03: WCAG 2.2 AA checks of the web app with axe-core, and keyboard-only use.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { mockApi } from "./mock-api";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function violations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  return violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

const notes = [
  { path: "Plan.md", bytes: Buffer.from("---\ntags: [work]\n---\n# Plan\n\nSee [[Spec]].\n\n- [ ] ship\n") },
  { path: "Spec.md", bytes: Buffer.from("# Spec\n\nBody\n") },
];

for (const [width, theme] of [[1280, "light"], [1280, "dark"], [375, "light"]] as const) {
  test(`no WCAG 2.2 AA violations at ${width} px, ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await mockApi(page, notes);
    await page.goto("/");
    if (theme === "dark") await page.evaluate(() => document.documentElement.classList.add("dark"));
    expect(await violations(page)).toEqual([]);
    if (width < 768) await page.getByRole("button", { name: "All notes" }).click(); // one pane at a time
    expect(await violations(page)).toEqual([]);
    await page.getByRole("button", { name: /^Plan/ }).click();
    await expect(page.getByRole("main").getByRole("heading", { name: "Plan" })).toBeVisible();
    expect(await violations(page)).toEqual([]);
  });
}

test("no WCAG 2.2 AA violations with an empty vault", async ({ page }) => {
  await mockApi(page, []);
  await page.goto("/");
  expect(await violations(page)).toEqual([]);
});

test("a note can be found, opened, edited and saved with the keyboard alone", async ({ page }) => {
  const api = await mockApi(page, notes);
  await page.goto("/");
  await expect(page.getByRole("button", { name: /^Plan/ })).toBeVisible();
  const focused: string[] = [];
  for (let i = 0; i < 10 && !focused.at(-1)?.startsWith("Plan"); i++) {
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const style = getComputedStyle(el);
      return { name: el.innerText || el.getAttribute("aria-label") || el.tagName, shown: style.outlineStyle !== "none" || style.boxShadow !== "none" };
    });
    expect(outline.shown, `focus indicator on ${outline.name}`).toBe(true); // WCAG 2.4.7
    focused.push(outline.name);
  }
  expect(focused.at(-1)).toMatch(/^Plan/);
  await page.keyboard.press("Enter");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Plan" })).toBeVisible();
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Tab");
    // The editor is in a shadow root: document.activeElement is its host, :focus is exact.
    if (await main.getByRole("textbox", { name: "Note text" }).evaluate((el) => el.matches(":focus"))) break;
  }
  await expect(main.getByRole("textbox", { name: "Note text" })).toBeFocused();
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type("Z");
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => api.puts.length).toBe(1);
  await expect(page.getByRole("contentinfo")).toHaveText("Saved");
  await page.keyboard.press("Tab"); // no keyboard trap (WCAG 2.1.2): Tab leaves the editor
  await expect(main.getByRole("textbox", { name: "Note text" })).not.toBeFocused();
});
