import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { composeRant, makePng, PASSWORD, signUp, unique, verifyEmail } from "./helpers";

const shots = process.env.E2E_SHOTS_DIR;

async function axe(page: import("@playwright/test").Page) {
  // Toasts are excluded: axe samples them mid fade-in, when opacity blends their colours.
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).exclude("[data-sonner-toaster]").analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => `${n.target} ${n.failureSummary}`).join(" | ")}`)).toEqual([]);
}

test("landing page is on-brand and accessible @mobile", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/scream it out/i);
  await expect(page.getByRole("link", { name: "Start ranting" })).toBeVisible();
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe("rgb(10, 13, 58)"); // DESIGN.md canvas #0a0d3a
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await axe(page);
  if (shots) await page.screenshot({ path: `${shots}/landing-${info.project.name}.png`, fullPage: true });
});

test("full journey: rant, react, comment, solve, anonymity", async ({ browser }) => {
  const alice = unique("alice");
  const bob = unique("bob");
  const aCtx = await browser.newContext();
  const bCtx = await browser.newContext();
  const a = await aCtx.newPage();
  const b = await bCtx.newPage();

  await signUp(a, alice);
  await verifyEmail(a, `${alice}@example.com`);
  await a.goto("/");
  await expect(a.getByText("Your feed is quiet")).toBeVisible();
  if (shots) await a.screenshot({ path: `${shots}/feed-empty.png` });

  // Image upload goes browser -> storage via presigned URL, then gets processed + moderated.
  const png = join(tmpdir(), "e2e.png");
  writeFileSync(png, makePng());
  await composeRant(a, { title: "Printer jammed during the board meeting", body: "Of course it did. **Every** single time.", image: png });
  const publicUrl = a.url();
  await expect(a.getByRole("img", { name: "Image attached to the rant" })).toBeVisible({ timeout: 30_000 });
  await axe(a);

  await signUp(b, bob);
  await b.goto(publicUrl);
  await expect(b.getByRole("heading", { name: "Printer jammed during the board meeting" })).toBeVisible();
  await b.getByRole("button", { name: /same here/i }).click();
  await expect(b.getByRole("button", { name: /same here/i })).toHaveAttribute("aria-pressed", "true");
  await b.getByLabel("Write a comment").fill("Unplug it and plug it back in. Works every time.");
  await b.getByRole("radio", { name: "Advice" }).click();
  await b.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(b.getByText("Unplug it and plug it back in.")).toBeVisible();

  // Alice pins Bob's answer as the solution.
  await a.reload();
  await a.getByRole("button", { name: "Comment options" }).click();
  await a.getByRole("menuitem", { name: "This solved it" }).click();
  await expect(a.getByText("Helped solve it")).toBeVisible();
  await expect(a.getByText("Solved", { exact: true }).first()).toBeVisible();
  if (shots) await a.screenshot({ path: `${shots}/post-detail.png`, fullPage: true });

  // Notifications reached Alice.
  await a.goto("/notifications");
  await expect(a.getByText(/said "same here"/)).toBeVisible();
  await expect(a.getByText(/responded to/)).toBeVisible();

  // Anonymous rant: Bob must not be able to find Alice anywhere on the page.
  await a.goto("/");
  const secretTitle = `Secret rant about my team lead ${alice.slice(-6)}`;
  await composeRant(a, { title: secretTitle, body: "Nobody can know this is me.", anonymous: true });
  const anonUrl = a.url();
  await b.goto(anonUrl);
  await expect(b.getByText("Anonymous ranter")).toBeVisible();
  const html = await b.content();
  expect(html).not.toContain(alice);
  await b.goto("/latest");
  await expect(b.getByText(secretTitle)).toBeVisible();
  expect(await b.content()).toContain("Anonymous ranter");

  // Profile page shows Bob's Helper Score from the pinned answer.
  await b.goto(`/u/${bob}`);
  await expect(b.getByText("Helper Score")).toBeVisible();
  await expect(b.locator("text=Helper Score").locator("..").getByText("10")).toBeVisible();
  await axe(b);
  if (shots) await b.screenshot({ path: `${shots}/profile.png`, fullPage: true });

  await aCtx.close();
  await bCtx.close();
});

test("auth pages, validation and logout", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("link", { name: /continue with google/i })).toHaveAttribute("href", "/api/v1/auth/google/login");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Enter a valid email")).toBeVisible();
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid email or password");
  await axe(page);
  if (shots) await page.screenshot({ path: `${shots}/login.png` });

  const handle = unique("carol");
  await signUp(page, handle);
  await page.reload(); // session survives reload via the httpOnly refresh cookie
  await expect(page.getByRole("link", { name: /notifications/i })).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Email").fill(`${handle}@example.com`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("link", { name: /notifications/i })).toBeVisible();
  await page.goto("/settings/privacy");
  await page.getByRole("switch", { name: /post anonymously by default/i }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await axe(page);
  if (shots) await page.screenshot({ path: `${shots}/settings.png`, fullPage: true });
});

test("mobile feed has no horizontal scroll @mobile", async ({ page }, info) => {
  await page.goto("/trending");
  await expect(page.getByRole("navigation", { name: "Feed" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  if (shots) await page.screenshot({ path: `${shots}/trending-${info.project.name}.png`, fullPage: true });
});
