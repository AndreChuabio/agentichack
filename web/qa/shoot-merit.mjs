#!/usr/bin/env node
// shoot-merit.mjs -- phone-viewport screenshots of the live Merit for reels.
//
//   node qa/shoot-merit.mjs --out <dir> [--base https://meritai.me]
//     [--email <e> --password <p>] [--pages track,market]
//
// Signs in with the supplied credentials (a demo/QA account, never a real
// customer's), then screenshots each page at several scroll positions at a
// phone viewport. Files land as <out>/<page>-<n>.png for build-reel-frames.
//
// Companion to the mini's untracked shoot-meritai.mjs, recreated from the
// Loop Handoff recipe so the pipeline exists in version control. Auth is
// email+password rather than a saved storageState because the laptop has no
// ~/.claudemeow-qa-auth; the handoff's approach works only where that file
// lives.

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const VIEWPORT = { width: 390, height: 844 }; // iPhone-class
const SCROLLS = [0, 0.45, 0.9]; // fractions of full page height

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    out[argv[i].slice(2)] =
      argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
  }
  return out;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.out) {
    process.stderr.write(
      "usage: node qa/shoot-merit.mjs --out <dir> [--base <url>] " +
        "[--email <e> --password <p>] [--pages track,market]\n",
    );
    return 2;
  }
  const base = (opts.base ?? "https://meritai.me").replace(/\/$/, "");
  const pages = (opts.pages ?? "track,market").split(",").map((p) => p.trim());
  await mkdir(opts.out, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 3, // crisp frames when scaled into 1080x1920
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  });
  const page = await context.newPage();

  try {
    if (opts.email && opts.password) {
      await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
      await page.getByLabel(/email/i).fill(opts.email);
      await page.getByLabel(/password/i).fill(opts.password);
      await page.getByRole("button", { name: /sign in/i }).click();
      // Login lands on an app surface; any (app) URL means the session took.
      await page.waitForURL(/\/(track|productize|market|publish|cfp)/, {
        timeout: 20_000,
      });
    }

    for (const name of pages) {
      await page.goto(`${base}/${name}`, { waitUntil: "networkidle" });
      // Bail rather than shoot a redirect: a login wall screenshot in a reel
      // is worse than a missing one.
      if (/\/login/.test(page.url())) {
        process.stderr.write(`SKIP ${name}: redirected to login\n`);
        continue;
      }
      const height = await page.evaluate(
        () => document.documentElement.scrollHeight - window.innerHeight,
      );
      for (let i = 0; i < SCROLLS.length; i += 1) {
        await page.evaluate((y) => window.scrollTo(0, y), height * SCROLLS[i]);
        await page.waitForTimeout(600); // settle sticky headers and lazy content
        await page.screenshot({ path: join(opts.out, `${name}-${i + 1}.png`) });
      }
      process.stdout.write(`shot ${name} x${SCROLLS.length}\n`);
    }
  } finally {
    await context.close();
    await browser.close();
  }
  return 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    process.stderr.write(`shoot failed: ${err?.stack || err}\n`);
    process.exit(1);
  },
);
