import { readFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Correct-Horse-Battery-9";

export function unique(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

export async function signUp(page: Page, handle: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Display name").fill(handle.replace("_", " "));
  await page.getByLabel("Handle").fill(handle);
  await page.getByLabel("Email").fill(`${handle}@example.com`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("link", { name: /notifications/i })).toBeVisible();
}

/** Dev emails are printed by the worker; read the newest verification link for an address. */
export async function verifyEmail(page: Page, email: string): Promise<void> {
  const log = process.env.E2E_EMAIL_LOG;
  if (!log) throw new Error("Set E2E_EMAIL_LOG to the worker log path");
  let link: string | undefined;
  for (let i = 0; i < 20 && !link; i++) {
    const lines = readFileSync(log, "utf8").split("\n").filter((l) => l.includes(`to=${email}`) && l.includes("verify-email"));
    link = lines.at(-1)?.match(/http\S+verify-email\?token=\S+/)?.[0];
    if (!link) await page.waitForTimeout(500);
  }
  expect(link, "verification email").toBeTruthy();
  await page.goto(new URL(link!).pathname + new URL(link!).search);
  await expect(page.getByText("Your email is verified")).toBeVisible();
}

export async function composeRant(
  page: Page,
  opts: { title: string; body: string; anonymous?: boolean; image?: string },
): Promise<void> {
  await page.getByRole("button", { name: /scream it/i }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(opts.title);
  await dialog.getByLabel("Rant", { exact: true }).fill(opts.body);
  await dialog.getByLabel("Tags").fill("e2e");
  await dialog.getByLabel("Tags").press("Enter");
  await dialog.getByRole("radio", { name: /4 · Furious/ }).click();
  if (opts.anonymous) await dialog.getByRole("switch", { name: /post anonymously/i }).click();
  if (opts.image) {
    await dialog.locator('input[type="file"]').setInputFiles(opts.image);
    await expect(dialog.getByRole("button", { name: /scream it/i })).toBeEnabled({ timeout: 30_000 });
  }
  await dialog.getByRole("button", { name: /scream it/i }).click();
  await expect(page).toHaveURL(/\/p\//);
}

/** Build a valid RGB PNG in memory (no fixtures needed). */
export function makePng(width = 320, height = 200): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff]! ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // RGB
  const rows = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * (width * 3 + 1) + 1 + x * 3;
      rows[i] = 88 + (x % 120);
      rows[i + 1] = 101;
      rows[i + 2] = 242 - (y % 100);
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
