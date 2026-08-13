"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { BuildSiteResponse, EvidenceItem } from "@/lib/types";

interface EvidenceOption {
  id: string;
  criterion: string;
  title: string;
}

export function PublishWizard() {
  const [options, setOptions] = useState<EvidenceOption[]>([]);
  const [repoText, setRepoText] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<BuildSiteResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.evidence
      .list()
      .then((ledger) => {
        if (!live) return;
        const flat: EvidenceOption[] = ledger.criteria.flatMap((criterion) =>
          criterion.items.map((item: EvidenceItem) => ({
            id: item.id,
            criterion: item.criterion,
            title: item.title,
          })),
        );
        setOptions(flat);
      })
      .catch(() => {
        if (live) setOptions([]);
      });
    return () => {
      live = false;
    };
  }, []);

  function toggle(id: string): void {
    setChosen((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function build(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const repoUrls = repoText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      setResult(await api.publish.buildSite(repoUrls, chosen));
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "Build failed",
      );
    } finally {
      setBusy(false);
    }
  }

  function download(): void {
    if (!result) return;
    const bytes = Uint8Array.from(atob(result.zip_base64), (c) =>
      c.charCodeAt(0),
    );
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${result.site_name}.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-8">
      <section>
        <h2 className="font-semibold">Step 1: Your repositories</h2>
        <p className="text-sm text-slate-600">
          One GitHub URL per line, up to eight.
        </p>
        <textarea
          aria-label="Repository URLs"
          className="mt-2 h-32 w-full rounded-lg border p-3 font-mono text-sm"
          value={repoText}
          onChange={(e) => setRepoText(e.target.value)}
          placeholder="https://github.com/you/project"
        />
      </section>

      <section>
        <h2 className="font-semibold">Step 2: What becomes public</h2>
        <p className="text-sm text-slate-600">
          Nothing from Track is published unless you tick it here. Anything you
          tick is world-readable and permanent in git history once you push.
        </p>
        <ul className="mt-2 space-y-2">
          {options.map((item) => (
            <li key={item.id} className="flex items-start gap-2">
              <input
                type="checkbox"
                id={`ev-${item.id}`}
                checked={chosen.includes(item.id)}
                onChange={() => toggle(item.id)}
              />
              <label htmlFor={`ev-${item.id}`} className="text-sm">
                <span className="font-medium">{item.title}</span>
                <span className="text-slate-500"> — {item.criterion}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <button
          type="button"
          onClick={build}
          disabled={busy}
          className="rounded-full bg-indigo-600 px-5 py-2 text-white disabled:opacity-50"
        >
          {busy ? "Building..." : "Generate site"}
        </button>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </section>

      {result && (
        <section>
          <h2 className="font-semibold">Step 3: Preview</h2>
          {result.skipped.length > 0 && (
            <ul className="mb-2 text-sm text-amber-700">
              {result.skipped.map((s) => (
                <li key={s.repo_url}>
                  Skipped {s.repo_url}: {s.reason}
                </li>
              ))}
            </ul>
          )}
          <iframe
            title="Site preview"
            sandbox=""
            srcDoc={result.html_preview}
            className="h-[32rem] w-full rounded-lg border"
          />
          <h2 className="mt-6 font-semibold">Step 4: Download and push</h2>
          <button
            type="button"
            onClick={download}
            className="mt-2 rounded-full border px-5 py-2"
          >
            Download {result.site_name}.zip
          </button>
          <p className="mt-2 text-sm text-slate-600">
            Unzip it and follow the README: two git commands puts it live on
            GitHub Pages.
          </p>
        </section>
      )}
    </div>
  );
}
