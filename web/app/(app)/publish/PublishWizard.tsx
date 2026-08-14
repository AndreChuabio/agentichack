"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { BuildSiteResponse, EvidenceItem, RepoOption } from "@/lib/types";

interface EvidenceOption {
  id: string;
  criterion: string;
  title: string;
}

/**
 * Where the built site stands.
 *
 * "draft" is what a fresh build produces: the HTML is stored but the RLS
 * policy on published_site hides it from the anon client, so the URL 404s.
 * "removed" is not the same as "draft": taking the site down deletes the row,
 * so getting back to a URL means building again.
 */
type SiteState = "draft" | "live" | "removed";

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError || err instanceof Error ? err.message : fallback;
}

export function PublishWizard() {
  const [options, setOptions] = useState<EvidenceOption[]>([]);
  const [repos, setRepos] = useState<RepoOption[]>([]);
  const [repoError, setRepoError] = useState("");
  const [chosenRepos, setChosenRepos] = useState<string[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<BuildSiteResponse | null>(null);
  const [siteState, setSiteState] = useState<SiteState>("draft");
  const [liveUrl, setLiveUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [liveBusy, setLiveBusy] = useState(false);

  // Restore the published-site state on mount, so a site published in an
  // earlier session shows as Live (with its take-down control) instead of
  // silently vanishing from the page until the user rebuilds.
  useEffect(() => {
    let live = true;
    api.publish
      .status()
      .then((s) => {
        if (!live) return;
        if (s.live && s.url) {
          setSiteState("live");
          setLiveUrl(s.url);
        }
      })
      .catch(() => {
        // Best-effort restore; building still works without it.
      });
    return () => {
      live = false;
    };
  }, []);

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

  useEffect(() => {
    let live = true;
    api.publish
      .listRepos()
      .then((response) => {
        if (!live) return;
        setRepos(response.repos);
        setChosenRepos(response.selected);
        setRepoError("");
      })
      .catch((err: unknown) => {
        if (!live) return;
        setRepos([]);
        setRepoError(
          message(err, "Could not read your GitHub repositories."),
        );
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

  function toggleRepo(fullName: string): void {
    setChosenRepos((prev) =>
      prev.includes(fullName)
        ? prev.filter((x) => x !== fullName)
        : [...prev, fullName],
    );
  }

  /**
   * Remember the repo choice on the profile so the picker opens on the same
   * selection next time. A failed preference write is not worth losing the
   * build over, so the build carries on and the site is unaffected.
   */
  async function rememberSelection(picked: RepoOption[]): Promise<void> {
    try {
      await api.market.putProfile({
        selected_repos: picked.map((repo) => repo.full_name),
      });
    } catch {
      setRepoError("Your repo selection could not be saved for next time.");
    }
  }

  async function build(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const picked = repos.filter((repo) =>
        chosenRepos.includes(repo.full_name),
      );
      await rememberSelection(picked);
      const built = await api.publish.buildSite(
        picked.map((repo) => repo.html_url),
        chosen,
      );
      setResult(built);
      setSiteState("draft");
      setLiveUrl("");
    } catch (err) {
      setError(message(err, "Build failed"));
    } finally {
      setBusy(false);
    }
  }

  async function goLive(): Promise<void> {
    setLiveBusy(true);
    setError("");
    try {
      const response = await api.publish.goLive();
      setLiveUrl(response.url);
      setSiteState("live");
    } catch (err) {
      setError(message(err, "Could not publish the site"));
    } finally {
      setLiveBusy(false);
    }
  }

  async function takeDown(): Promise<void> {
    setLiveBusy(true);
    setError("");
    try {
      await api.publish.takeDown();
      setLiveUrl("");
      setSiteState("removed");
    } catch (err) {
      setError(message(err, "Could not take the site down"));
    } finally {
      setLiveBusy(false);
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
      {!result && siteState === "live" && liveUrl && (
        <section className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm">
          <p className="font-medium text-green-700">Your site is live</p>
          <p className="text-slate-600">
            <a
              className="font-mono underline"
              href={liveUrl}
              target="_blank"
              rel="noreferrer"
            >
              {liveUrl}
            </a>
          </p>
          <div className="mt-2">
            <button
              type="button"
              onClick={takeDown}
              disabled={liveBusy}
              className="rounded-full border px-5 py-2 disabled:opacity-50"
            >
              {liveBusy ? "Working..." : "Take down"}
            </button>
          </div>
        </section>
      )}

      <section>
        <h2 className="font-semibold">Step 1: Your repositories</h2>
        <p className="text-sm text-slate-600">
          Tick the repos this site should read. Forks are listed last. Up to
          eight are built.
        </p>
        {repoError && <p className="mt-2 text-sm text-amber-700">{repoError}</p>}
        {repos.length === 0 && !repoError && (
          <p className="mt-2 text-sm text-slate-600">
            No repositories to show yet. Add your GitHub URL on the Market
            profile and they will appear here.
          </p>
        )}
        <ul className="mt-2 space-y-2">
          {repos.map((repo) => (
            <li key={repo.full_name} className="flex items-start gap-2">
              <input
                type="checkbox"
                id={`repo-${repo.full_name}`}
                checked={chosenRepos.includes(repo.full_name)}
                onChange={() => toggleRepo(repo.full_name)}
              />
              <label htmlFor={`repo-${repo.full_name}`} className="text-sm">
                <span className="font-medium">{repo.full_name}</span>
                {repo.language && (
                  <span className="text-slate-500"> — {repo.language}</span>
                )}
                <span className="text-slate-500"> — {repo.stars} stars</span>
                {repo.fork && <span className="text-slate-500"> (fork)</span>}
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-semibold">Step 2: What becomes public</h2>
        <p className="text-sm text-slate-600">
          Nothing from Track is published unless you tick it here. Anything you
          tick is world-readable once the site goes live.
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

          <h2 className="mt-6 font-semibold">Step 4: Publish</h2>
          {siteState === "draft" && (
            <div className="mt-2 text-sm">
              <p className="font-medium text-slate-700">
                Draft - not visible to anyone yet
              </p>
              <p className="text-slate-600">
                It will answer on{" "}
                <span className="font-mono">{result.public_url}</span> once you
                publish it.
              </p>
            </div>
          )}
          {siteState === "live" && (
            <div className="mt-2 text-sm">
              <p className="font-medium text-green-700">Live</p>
              <p className="text-slate-600">
                <a
                  className="font-mono underline"
                  href={liveUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {liveUrl}
                </a>
              </p>
            </div>
          )}
          {siteState === "removed" && (
            <p className="mt-2 text-sm text-slate-600">
              Taken down. The stored page was deleted, so generating the site
              again is what brings the URL back.
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-3">
            {siteState !== "live" && (
              <button
                type="button"
                onClick={goLive}
                disabled={liveBusy || siteState === "removed"}
                className="rounded-full bg-indigo-600 px-5 py-2 text-white disabled:opacity-50"
              >
                {liveBusy ? "Working..." : "Publish"}
              </button>
            )}
            {siteState === "live" && (
              <button
                type="button"
                onClick={takeDown}
                disabled={liveBusy}
                className="rounded-full border px-5 py-2 disabled:opacity-50"
              >
                {liveBusy ? "Working..." : "Take down"}
              </button>
            )}
            <button
              type="button"
              onClick={download}
              className="rounded-full border px-5 py-2"
            >
              Download {result.site_name}.zip
            </button>
          </div>
          <p className="mt-2 text-sm text-slate-600">
            The zip is the same site as a folder, if you would rather host it
            yourself.
          </p>
        </section>
      )}
    </div>
  );
}
