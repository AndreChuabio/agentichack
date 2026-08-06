import fs from "node:fs";
import path from "node:path";
import { type Page, expect } from "@playwright/test";

/**
 * Wall-detector + action-logger shared by every persona.
 *
 * A "wall" is any point an anonymous visitor cannot pass: an auth gate, a
 * payment gate, an error state, or a click that goes nowhere. The safety rail
 * for this run is that reaching a wall IS the deliverable -- we film it and
 * record it, we never cross it (no signup submit, no payment).
 */

export type WallType =
  | "auth-gate" // signup / login form or redirect-to-login
  | "payment-gate" // Stripe / paywall
  | "recovery-gate" // password-reset request form
  | "http-error" // response status >= 400
  | "console-error" // uncaught page error or console.error
  | "error-banner" // inline bg-danger error state rendered
  | "noop-click" // click produced no navigation and no DOM change
  | "none"; // completeness checkpoint, no wall

export interface ActionLogEntry {
  persona: string;
  step: string;
  url: string;
  wall_type: WallType;
  screenshot: string | null;
  http_errors: string[];
  console_errors: string[];
  note: string;
  ts: string;
}

const RESULTS_DIR = path.resolve(process.cwd(), "results");
const SHOTS_DIR = path.join(RESULTS_DIR, "money-shots");
const LOG_FILE = path.join(RESULTS_DIR, "action-log.jsonl");

for (const d of [RESULTS_DIR, SHOTS_DIR]) {
  fs.mkdirSync(d, { recursive: true });
}

/** Per-page collectors for the error-channel half of the detector. */
export class ErrorChannel {
  readonly httpErrors: string[] = [];
  readonly consoleErrors: string[] = [];

  constructor(page: Page) {
    page.on("pageerror", (err) => {
      this.consoleErrors.push(`pageerror: ${err.message}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        this.consoleErrors.push(`console.error: ${msg.text()}`);
      }
    });
    page.on("response", (res) => {
      const status = res.status();
      // Ignore benign analytics/telemetry noise; record everything >= 400.
      if (status >= 400) {
        this.httpErrors.push(`${status} ${res.request().method()} ${res.url()}`);
      }
    });
  }
}

/** True if the repo's canonical inline error banner (bg-danger/10) is showing. */
export async function errorBannerVisible(page: Page): Promise<boolean> {
  const banner = page.locator('[class*="bg-danger"]');
  return (await banner.count()) > 0 && (await banner.first().isVisible());
}

/** Slugify for filenames. */
function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/**
 * Capture a full-page money shot, append a structured action-log line, and
 * return the entry. Call this at each persona checkpoint -- especially the
 * wall step.
 */
export async function recordCheckpoint(
  page: Page,
  errs: ErrorChannel,
  opts: {
    persona: string;
    step: string;
    wall_type: WallType;
    note?: string;
    shot?: boolean;
  },
): Promise<ActionLogEntry> {
  const shotName = opts.shot === false
    ? null
    : `${slug(opts.persona)}__${slug(opts.step)}.png`;
  if (shotName) {
    await page.screenshot({
      path: path.join(SHOTS_DIR, shotName),
      fullPage: true,
    });
  }
  const entry: ActionLogEntry = {
    persona: opts.persona,
    step: opts.step,
    url: page.url(),
    wall_type: opts.wall_type,
    screenshot: shotName,
    http_errors: [...errs.httpErrors],
    console_errors: [...errs.consoleErrors],
    note: opts.note ?? "",
    ts: new Date().toISOString(),
  };
  fs.appendFileSync(LOG_FILE, `${JSON.stringify(entry)}\n`);
  return entry;
}

/**
 * No-op / stuck detector. Runs `action`, waits for the network to settle, and
 * returns whether the URL changed. Callers assert on the result to decide
 * whether a CTA actually did something.
 */
export async function didNavigate(
  page: Page,
  action: () => Promise<void>,
): Promise<{ changed: boolean; from: string; to: string }> {
  const from = page.url();
  await action();
  // Client-side (Next.js Link) navigation commits asynchronously and may leave
  // the network idle before the URL updates. Wait explicitly for a URL change
  // (bounded), then let the network settle, before sampling the final URL.
  await page
    .waitForURL((url) => url.toString() !== from, { timeout: 10_000 })
    .catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});
  const to = page.url();
  return { changed: from !== to, from, to };
}

export { expect };
