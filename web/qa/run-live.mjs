#!/usr/bin/env node
// run-live.mjs -- live-target QA sweep for Merit, contract-compatible with
// claudemeow's qa/run.mjs.
//
//   node qa/run-live.mjs --target <url> --out <dir> [--api <url>] [--notes <text>]
//
// Drives a headless Chromium over a DEPLOYED Merit (preview or production),
// checks the journeys an anonymous visitor can reach, and writes:
//   <out>/findings.json   contract-shaped results
//   <out>/qa.webm         1280x800 screen recording of the walk
//   <out>/break-*.png     one screenshot per recorded break
//
// The output shape and exit codes deliberately match claudemeow's runner, so
// the mini can invoke this with no adapter:
//   0  the run produced findings -- EVEN IF breaks were found. Breaks are data.
//   2  bad invocation (missing/invalid args).
//   1  a real runner failure (browser would not launch, output not writable).
//
// Why this exists alongside the Playwright suite: that suite runs against a
// local dev server and proves the code is right. This proves the DEPLOYMENT is
// right, which is a different question and the one that actually wasted time --
// a frontend shipped against a backend that did not have its routes yet looks
// identical to a bug until someone reads a 404.

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const VIDEO = { width: 1280, height: 800 };

// Public routes any visitor reaches, and a string that proves the right app
// answered. Merit-specific on purpose: a generic "did it 200" check passes
// against any stranger's server, which is exactly how a green result once came
// back from an unrelated app on a shared port.
const PUBLIC_PAGES = [
  { step: "landing", path: "/", expect: /O-1A|Extraordinary ability/i },
  { step: "login", path: "/login", expect: /Welcome back|Sign in/i },
  { step: "signup", path: "/signup", expect: /Create your account|Sign up/i },
  { step: "privacy", path: "/privacy", expect: /privacy/i },
];

// Signed-out visitors must be bounced off these.
const GATED_PAGES = ["/market", "/productize", "/track", "/publish", "/cfp"];

// Routes the API must ANSWER. 401 means present and protected; 404 means the
// backend does not have this build, which is the deploy-skew failure that looks
// like a broken button in the browser.
const API_ROUTES = [
  { method: "POST", path: "/publish/site" },
  { method: "GET", path: "/publish/repos" },
  { method: "POST", path: "/market/profile/autofill" },
  { method: "POST", path: "/market/profile/resume" },
  { method: "POST", path: "/market/outreach/generate" },
];

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
    out[key.slice(2)] = value;
  }
  return out;
}

function usage(reason) {
  process.stderr.write(
    `qa/run-live.mjs: ${reason}\n` +
      "usage: node qa/run-live.mjs --target <url> --out <dir> [--api <url>] [--notes <text>]\n",
  );
}

/** Trim a URL to its origin, so a pasted deep link still works as a target. */
function origin(value) {
  return new URL(value).origin;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.target || !opts.out) {
    usage("both --target and --out are required");
    return 2;
  }

  let base;
  try {
    base = origin(opts.target);
  } catch {
    usage(`--target ${opts.target} is not a URL`);
    return 2;
  }
  const api = opts.api ? origin(opts.api) : "";
  const outDir = opts.out;

  await mkdir(outDir, { recursive: true });

  const flows = [];
  const breaks = [];
  const suggestions = [];
  let shotIndex = 0;

  const addBreak = async (page, where, kind, detail) => {
    shotIndex += 1;
    const shot = join(outDir, `break-${String(shotIndex).padStart(2, "0")}.png`);
    try {
      if (page) await page.screenshot({ path: shot, fullPage: false });
    } catch {
      // A screenshot failing must never lose the break it was documenting.
    }
    breaks.push({ where, kind, detail: String(detail).slice(0, 500), shot });
  };

  let browser;
  try {
    browser = await chromium.launch();
  } catch (err) {
    process.stderr.write(`browser would not launch: ${err}\n`);
    return 1;
  }

  const context = await browser.newContext({
    viewport: VIDEO,
    recordVideo: { dir: outDir, size: VIDEO },
  });
  const page = await context.newPage();

  // Console errors are collected per-navigation rather than thrown, because one
  // noisy 404 for a favicon should not end a walk that still has journeys left.
  let consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    // --- identity ------------------------------------------------------
    // Everything after this is only meaningful if the right app answered.
    let identified = false;
    try {
      const res = await page.goto(base, { waitUntil: "domcontentloaded", timeout: 30_000 });
      const html = await page.content();
      identified = /O-1A|Extraordinary ability|Merit/i.test(html);
      flows.push({ step: "identity", url: base, ok: Boolean(res?.ok()) && identified });
      if (!identified) {
        await addBreak(
          page,
          base,
          "error-banner",
          `served "${await page.title()}", which is not Merit -- every other ` +
            "result in this run should be discarded",
        );
      }
    } catch (err) {
      flows.push({ step: "identity", url: base, ok: false });
      await addBreak(page, base, "stuck", `could not reach the target: ${err}`);
    }

    if (identified) {
      // --- public pages ------------------------------------------------
      for (const { step, path, expect } of PUBLIC_PAGES) {
        const url = `${base}${path}`;
        consoleErrors = [];
        let ok = false;
        try {
          const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
          const status = res?.status() ?? 0;
          if (status >= 500) {
            await addBreak(page, url, "http-5xx", `status ${status}`);
          } else if (status >= 400) {
            await addBreak(page, url, "http-4xx", `status ${status}`);
          } else {
            // Wait for the text rather than regexing the initial HTML: these
            // pages hydrate client-side, so the copy is absent from the first
            // response and a raw match reports a healthy page as broken.
            try {
              await page.getByText(expect).first().waitFor({ state: "visible", timeout: 15_000 });
              ok = true;
            } catch {
              await addBreak(page, url, "error-banner", `expected copy ${expect} never appeared`);
            }
          }
          for (const text of consoleErrors.slice(0, 3)) {
            await addBreak(page, url, "console-error", text);
          }
        } catch (err) {
          await addBreak(page, url, "stuck", String(err));
        }
        flows.push({ step, url, ok });
      }

      // --- gated pages bounce anonymous visitors -----------------------
      for (const path of GATED_PAGES) {
        const url = `${base}${path}`;
        let ok = false;
        try {
          await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
          ok = /\/login/.test(page.url());
          if (!ok) {
            await addBreak(
              page,
              url,
              "error-banner",
              `an anonymous visitor was left on ${page.url()} instead of /login`,
            );
          }
        } catch (err) {
          await addBreak(page, url, "stuck", String(err));
        }
        flows.push({ step: `gated${path}`, url, ok });
      }

      // --- a portfolio slug nobody owns must 404 -----------------------
      // The published-site route is served by RLS: an unpublished draft returns
      // no row and 404s. A 200 here would mean drafts are reachable.
      const ghostUrl = `${base}/u/qa-slug-that-should-not-exist`;
      let ghostOk = false;
      try {
        const res = await page.goto(ghostUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
        ghostOk = res?.status() === 404;
        if (!ghostOk) {
          await addBreak(page, ghostUrl, "error-banner", `expected 404, got ${res?.status()}`);
        }
      } catch (err) {
        await addBreak(page, ghostUrl, "stuck", String(err));
      }
      flows.push({ step: "unknown-portfolio-slug-404s", url: ghostUrl, ok: ghostOk });
    }

    // --- the API behind it ---------------------------------------------
    if (api) {
      let health = null;
      try {
        const res = await page.request.get(`${api}/health`, { timeout: 30_000 });
        health = res.ok() ? await res.json() : null;
        flows.push({ step: "api-health", url: `${api}/health`, ok: Boolean(health?.database) });
        if (!health) {
          await addBreak(null, `${api}/health`, "http-5xx", `status ${res.status()}`);
        } else if (!health.database) {
          await addBreak(null, `${api}/health`, "error-banner", "API cannot reach its database");
        }
        if (health && !health.build) {
          suggestions.push(
            "API /health reports no build marker, so there is no way to tell " +
              "which build is serving. Deploys can only be confirmed by guesswork.",
          );
        }
      } catch (err) {
        flows.push({ step: "api-health", url: `${api}/health`, ok: false });
        await addBreak(null, `${api}/health`, "stuck", String(err));
      }

      for (const { method, path } of API_ROUTES) {
        const url = `${api}${path}`;
        let ok = false;
        try {
          const res =
            method === "GET"
              ? await page.request.get(url, { timeout: 30_000, failOnStatusCode: false })
              : await page.request.post(url, {
                  data: {},
                  timeout: 30_000,
                  failOnStatusCode: false,
                });
          const status = res.status();
          // 401 is the healthy answer: the route exists and refused an
          // anonymous caller. 404 means this build of the API does not have it,
          // which in the browser looks exactly like a broken feature.
          ok = status === 401;
          if (status === 404) {
            await addBreak(
              null,
              url,
              "http-4xx",
              "route missing from the deployed API -- the frontend calls it, so " +
                "this feature is dead until the backend is redeployed",
            );
          } else if (!ok && status >= 500) {
            await addBreak(null, url, "http-5xx", `status ${status}`);
          } else if (!ok) {
            suggestions.push(`${method} ${path} answered ${status}, expected 401 when anonymous.`);
          }
        } catch (err) {
          await addBreak(null, url, "stuck", String(err));
        }
        flows.push({ step: `api ${method} ${path}`, url, ok });
      }
    } else {
      suggestions.push(
        "No --api given, so nothing checked whether the backend actually has " +
          "the routes this frontend calls. That skew is invisible from the UI.",
      );
    }
  } finally {
    await context.close();
    await browser.close();
  }

  // Playwright names the video on close; find it rather than assuming.
  let video = "";
  try {
    const { readdir } = await import("node:fs/promises");
    const found = (await readdir(outDir)).find((f) => f.endsWith(".webm"));
    if (found) video = join(outDir, found);
  } catch {
    // No video is a degraded run, not a failed one.
  }

  const findings = {
    target: base,
    api,
    flows,
    breaks,
    suggestions,
    video,
    logged_in: false,
    carried_corrections: Boolean(opts.notes),
    notes: opts.notes ?? "",
  };

  await writeFile(join(outDir, "findings.json"), `${JSON.stringify(findings, null, 2)}\n`);

  const failed = flows.filter((f) => !f.ok).length;
  process.stdout.write(
    `${flows.length - failed}/${flows.length} flows ok, ${breaks.length} break(s), ` +
      `${suggestions.length} suggestion(s)\n${join(outDir, "findings.json")}\n`,
  );
  for (const b of breaks) process.stdout.write(`  BREAK ${b.kind} ${b.where}: ${b.detail}\n`);

  // 0 even with breaks: breaks are the product of the run, not a runner error.
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    process.stderr.write(`runner failure: ${err?.stack || err}\n`);
    process.exit(1);
  });
