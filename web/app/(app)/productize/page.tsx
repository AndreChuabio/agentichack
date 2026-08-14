"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type {
  Citation,
  DraftDone,
  ExportResult,
  PluginResult,
  ResearchSummary,
  Venue,
} from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { StepHeader } from "./StepHeader";
import { LlmKeyField } from "./LlmKeyField";
import { SummaryEditor } from "./SummaryEditor";
import { VenueCard } from "./VenueCard";
import { DraftStream } from "./DraftStream";

const EMPTY_SUMMARY: ResearchSummary = {
  problem: "",
  contribution: "",
  method: "",
  results: "",
  limitations: "",
  keywords: [],
};

function summaryHasContent(summary: ResearchSummary): boolean {
  return (
    summary.problem.trim().length > 0 ||
    summary.contribution.trim().length > 0 ||
    summary.method.trim().length > 0 ||
    summary.results.trim().length > 0
  );
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Placeholder for a step whose prerequisite is not met yet. Keeps all four
 * steps visible on the page so a new user sees the whole journey up front,
 * instead of sections appearing one by one as they progress.
 */
function LockedStep({
  step,
  title,
  hint,
}: {
  step: string;
  title: string;
  hint: string;
}) {
  return (
    <section className="flex flex-col gap-4 opacity-70">
      <div className="flex items-center gap-2">
        <Badge tone="neutral">{step}</Badge>
        <CardTitle>{title}</CardTitle>
      </div>
      <Card className="border-dashed">
        <CardDescription>{hint}</CardDescription>
      </Card>
    </section>
  );
}

function base64ToBlob(base64: string, type: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type });
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadText(text: string, filename: string, mime: string): void {
  downloadBlob(new Blob([text], { type: mime }), filename);
}

export default function ProductizePage() {
  const [repoUrl, setRepoUrl] = useState("");
  const [summary, setSummary] = useState<ResearchSummary>(EMPTY_SUMMARY);
  const [summaryReady, setSummaryReady] = useState(false);
  const [ingestNotice, setIngestNotice] = useState<string | null>(null);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // The repo URL that sessionId was ingested from. Plugin extraction only
  // reuses sessionId's cached bundle when this still matches the current
  // repoUrl -- otherwise a leftover session from a previously ingested repo
  // could get passed to a plugin extraction for a different repo.
  const [ingestedRepoUrl, setIngestedRepoUrl] = useState<string | null>(null);
  // Set when ingest is refused with a 413 (bundle too large to run
  // unconfirmed). Holds the backend's detail message; cleared once the user
  // either confirms ("Run anyway") or changes the repo URL.
  const [largeBundleNotice, setLargeBundleNotice] = useState<string | null>(
    null,
  );

  const [venues, setVenues] = useState<Venue[]>([]);
  const [selectedVenue, setSelectedVenue] = useState<Venue | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);

  const [draftSections, setDraftSections] = useState<Record<string, string>>(
    {},
  );
  const [draftOrder, setDraftOrder] = useState<string[]>([]);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [draftStreaming, setDraftStreaming] = useState(false);
  const [draftStarted, setDraftStarted] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const draftAbort = useRef<AbortController | null>(null);

  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [plugin, setPlugin] = useState<PluginResult | null>(null);
  const [pluginLoading, setPluginLoading] = useState(false);
  const [pluginError, setPluginError] = useState<string | null>(null);

  const draftComplete = useMemo(
    () => draftStarted && !draftStreaming && draftOrder.length > 0,
    [draftStarted, draftStreaming, draftOrder.length],
  );

  const currentStep = useMemo(() => {
    if (draftStarted) return draftComplete ? 4 : 3;
    if (selectedVenue) return 3;
    if (summaryReady) return 2;
    return 1;
  }, [draftStarted, draftComplete, selectedVenue, summaryReady]);

  const recordSection = useCallback((name: string) => {
    if (!name) return;
    setDraftOrder((prev) => (prev.includes(name) ? prev : [...prev, name]));
  }, []);

  const handleIngest = useCallback(
    async (confirmLarge = false) => {
      const url = repoUrl.trim();
      if (!url) return;
      setIngestLoading(true);
      setIngestNotice(null);
      setLargeBundleNotice(null);
      try {
        const result = await api.ingest(url, confirmLarge);
        setSummary({ ...EMPTY_SUMMARY, ...result.summary });
        setSummaryReady(true);
        setSessionId(result.session_id ?? null);
        setIngestedRepoUrl(result.session_id ? url : null);
        if (result.notes) setIngestNotice(result.notes);
      } catch (err) {
        if (err instanceof ApiError && err.status === 413) {
          // Oversized bundle on the user's own key: surface the cost and let
          // them decide, rather than silently spending it or silently
          // falling back to manual entry.
          setLargeBundleNotice(err.message);
          return;
        }
        // Ingest can fail when the server GitHub token is unconfigured. Surface a
        // friendly note (no raw error) and let the user write the summary by hand.
        setIngestNotice(
          "We could not read that repo automatically right now. No problem, you can write the summary below and continue.",
        );
        setSummary((prev) => (summaryHasContent(prev) ? prev : EMPTY_SUMMARY));
        setSummaryReady(true);
      } finally {
        setIngestLoading(false);
      }
    },
    [repoUrl],
  );

  const handleManualStart = useCallback(() => {
    setSummaryReady(true);
    setIngestNotice(null);
  }, []);

  const handleMatch = useCallback(async () => {
    setMatchLoading(true);
    setMatchError(null);
    setSelectedVenue(null);
    try {
      const result = await api.match(summary, 6);
      setVenues(result);
      if (result.length === 0) {
        setMatchError("No venues came back. Try adding more detail above.");
      }
    } catch (err) {
      setMatchError(errorMessage(err));
    } finally {
      setMatchLoading(false);
    }
  }, [summary]);

  const handleDraft = useCallback(async () => {
    if (!selectedVenue) return;
    // Reset any previous run.
    draftAbort.current?.abort();
    const controller = new AbortController();
    draftAbort.current = controller;

    setDraftSections({});
    setDraftOrder([]);
    setActiveSection(null);
    setCitations([]);
    setDraftError(null);
    setExportResult(null);
    setDraftStarted(true);
    setDraftStreaming(true);

    await api.draft(
      summary,
      selectedVenue,
      {
        onDelta: (section, text) => {
          const name = section || "draft";
          recordSection(name);
          setActiveSection(name);
          setDraftSections((prev) => ({
            ...prev,
            [name]: (prev[name] ?? "") + text,
          }));
        },
        onSection: (section) => {
          recordSection(section);
          setActiveSection(section);
        },
        onDone: (done: DraftDone) => {
          if (done.sections) {
            setDraftSections((prev) => ({ ...prev, ...done.sections }));
            setDraftOrder((prev) => {
              const merged = [...prev];
              for (const key of Object.keys(done.sections)) {
                if (!merged.includes(key)) merged.push(key);
              }
              return merged;
            });
          }
          if (done.citations) setCitations(done.citations);
          setActiveSection(null);
          setDraftStreaming(false);
        },
        onError: (message) => {
          setDraftError(message);
          setActiveSection(null);
          setDraftStreaming(false);
        },
      },
      controller.signal,
    );

    // Guard: if the stream ended without a done event.
    setDraftStreaming(false);
    setActiveSection(null);
  }, [selectedVenue, summary, recordSection]);

  const handleExport = useCallback(async () => {
    if (!selectedVenue) return;
    setExportLoading(true);
    setExportError(null);
    try {
      const result = await api.exportPaper(
        summary,
        selectedVenue,
        draftSections,
        citations.length > 0 ? citations : undefined,
      );
      setExportResult(result);
    } catch (err) {
      setExportError(errorMessage(err));
    } finally {
      setExportLoading(false);
    }
  }, [selectedVenue, summary, draftSections, citations]);

  const handleExtractPlugin = useCallback(async () => {
    const url = repoUrl.trim();
    if (!url) {
      setPluginError("Add a repo URL at the top to extract a plugin.");
      return;
    }
    setPluginLoading(true);
    setPluginError(null);
    try {
      const reusableSessionId = ingestedRepoUrl === url ? sessionId : null;
      const result = await api.extractPlugin(url, reusableSessionId);
      setPlugin(result);
    } catch (err) {
      setPluginError(errorMessage(err));
    } finally {
      setPluginLoading(false);
    }
  }, [repoUrl, sessionId, ingestedRepoUrl]);

  const downloadPlugin = useCallback(() => {
    if (!plugin) return;
    const blob = base64ToBlob(plugin.zip_base64, "application/zip");
    downloadBlob(blob, `${plugin.plugin_name || "plugin"}.zip`);
  }, [plugin]);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <Badge tone="pink">Productize</Badge>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink sm:text-4xl">
          Turn a repo into a paper
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          Point us at a GitHub repo. We distill the research story, match it to
          venues, draft the paper live, then hand you the LaTeX and a packaged
          plugin.
        </p>
        <StepHeader current={currentStep} />
        <LlmKeyField />

        <Card className="flex flex-col gap-3 bg-primary-50/60">
          <CardTitle>Why this helps your O-1A case</CardTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <Badge tone="primary">Published articles</Badge>
              <p className="text-sm leading-relaxed text-muted">
                Turning your repo into a paper builds toward the O-1A criterion
                for authorship of scholarly articles in your field.
              </p>
            </div>
            <div className="flex flex-col gap-1">
              <Badge tone="lime">Original contributions</Badge>
              <p className="text-sm leading-relaxed text-muted">
                Packaging it as a shippable Claude plugin builds toward the
                criterion for original contributions of major significance.
              </p>
            </div>
          </div>
          <p className="text-xs text-muted">
            New to the O-1A criteria? You do not need to know them. Follow the
            steps below and Merit maps the output to your case.
          </p>
        </Card>
      </header>

      {/* Step 1: Ingest */}
      <section className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Badge tone="primary">1</Badge>
          <CardTitle>Ingest a repo</CardTitle>
        </div>
        <Card className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Input
                label="GitHub repository URL"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !ingestLoading) handleIngest();
                }}
              />
            </div>
            <Button
              onClick={() => handleIngest()}
              disabled={ingestLoading || repoUrl.trim().length === 0}
            >
              {ingestLoading ? <Spinner size={16} /> : null}
              {ingestLoading ? "Ingesting" : "Ingest repo"}
            </Button>
            {!summaryReady ? (
              <Button variant="ghost" onClick={handleManualStart}>
                Skip, write it myself
              </Button>
            ) : null}
          </div>
          {largeBundleNotice ? (
            <div className="flex flex-col gap-3 rounded-2xl bg-warning/10 px-4 py-3">
              <p className="text-sm text-ink">{largeBundleNotice}</p>
              <div>
                <Button
                  variant="secondary"
                  onClick={() => handleIngest(true)}
                  disabled={ingestLoading}
                >
                  {ingestLoading ? <Spinner size={16} /> : null}
                  {ingestLoading ? "Ingesting" : "Run anyway"}
                </Button>
              </div>
            </div>
          ) : null}
          {ingestNotice ? (
            <p className="rounded-2xl bg-warning/10 px-4 py-3 text-sm text-ink">
              {ingestNotice}
            </p>
          ) : null}
        </Card>
      </section>

      {/* Step 1b: Editable summary, folded into step 1. */}
      {summaryReady ? (
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Badge tone="primary">1</Badge>
            <CardTitle>Research summary</CardTitle>
            <span className="text-sm text-muted">
              edit anything before matching
            </span>
          </div>
          <SummaryEditor
            summary={summary}
            onChange={setSummary}
            disabled={ingestLoading}
          />
          <div>
            <Button
              onClick={handleMatch}
              disabled={matchLoading || !summaryHasContent(summary)}
            >
              {matchLoading ? <Spinner size={16} /> : null}
              {matchLoading ? "Matching venues" : "Match venues"}
            </Button>
            {!summaryHasContent(summary) ? (
              <p className="mt-2 text-xs text-muted">
                Fill in at least the problem or contribution to match venues.
              </p>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* Step 2: Venues */}
      {(venues.length > 0 || matchError) && summaryReady ? (
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Badge tone="primary">2</Badge>
            <CardTitle>Pick a venue</CardTitle>
          </div>
          <CardDescription>
            A venue is a journal, conference, or workshop where your paper could
            be published. The fit score is how closely each one matches your
            work. Pick the one you want to write toward.
          </CardDescription>
          {matchError ? (
            <Card className="bg-danger/5">
              <CardDescription className="text-danger">
                {matchError}
              </CardDescription>
            </Card>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            {venues.map((venue) => (
              <VenueCard
                key={`${venue.name}-${venue.type}`}
                venue={venue}
                selected={selectedVenue?.name === venue.name}
                onSelect={() => setSelectedVenue(venue)}
              />
            ))}
          </div>
          {selectedVenue ? (
            <div>
              <Button onClick={handleDraft} disabled={draftStreaming}>
                {draftStreaming ? <Spinner size={16} /> : null}
                {draftStreaming
                  ? "Drafting"
                  : draftStarted
                    ? `Redraft for ${selectedVenue.name}`
                    : `Draft for ${selectedVenue.name}`}
              </Button>
            </div>
          ) : null}
        </section>
      ) : (
        <LockedStep
          step="2"
          title="Pick a venue"
          hint="Once your research summary is in, Merit ranks the journals, conferences, and workshops that fit it. The ranked venues appear here with a fit score, and you pick the one to write toward."
        />
      )}

      {/* Step 3: Draft stream */}
      {draftStarted ? (
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Badge tone="primary">3</Badge>
            <CardTitle>Live draft</CardTitle>
            {draftStreaming ? (
              <Badge tone="pink">streaming</Badge>
            ) : draftError ? (
              <Badge tone="danger">stopped</Badge>
            ) : (
              <Badge tone="success">complete</Badge>
            )}
          </div>
          {draftError ? (
            <Card className="bg-danger/5">
              <CardDescription className="text-danger">
                {draftError}
              </CardDescription>
            </Card>
          ) : null}
          <DraftStream
            order={draftOrder}
            sections={draftSections}
            activeSection={activeSection}
            streaming={draftStreaming}
          />
        </section>
      ) : (
        <LockedStep
          step="3"
          title="Live draft"
          hint="Pick a venue in step 2 and Merit drafts the paper section by section, streaming live into this space so you can watch it come together."
        />
      )}

      {/* Step 4: Export + plugin */}
      {draftComplete ? (
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Badge tone="primary">4</Badge>
            <CardTitle>Export</CardTitle>
          </div>
          <Card className="flex flex-col gap-3">
            <CardTitle>LaTeX paper</CardTitle>
            <CardDescription>
              Generate the files for a finished manuscript: a .tex file (the
              paper, written in LaTeX, the typesetting format journals expect)
              and a matching .bib file (its list of references). Both drop
              straight into Overleaf, a free in-browser LaTeX editor, so you can
              format and submit without installing anything.
            </CardDescription>
            <div className="mt-auto flex flex-wrap gap-2 pt-2">
              <Button onClick={handleExport} disabled={exportLoading}>
                {exportLoading ? <Spinner size={16} /> : null}
                {exportLoading
                  ? "Building"
                  : exportResult
                    ? "Rebuild"
                    : "Build LaTeX"}
              </Button>
              {exportResult ? (
                <>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      downloadText(
                        exportResult.tex,
                        "paper.tex",
                        "application/x-tex",
                      )
                    }
                  >
                    Download .tex
                  </Button>
                  <Button
                    variant="lime"
                    onClick={() =>
                      downloadText(
                        exportResult.bib,
                        "paper.bib",
                        "application/x-bibtex",
                      )
                    }
                  >
                    Download .bib
                  </Button>
                </>
              ) : null}
            </div>
            {exportError ? (
              <p className="text-sm text-danger">{exportError}</p>
            ) : null}
            {exportResult ? (
              <p className="text-sm text-muted">
                Done. Log this as evidence in your{" "}
                <Link
                  href="/track"
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  Track ledger
                </Link>{" "}
                so it counts toward your O-1A case.
              </p>
            ) : null}
          </Card>
        </section>
      ) : (
        <LockedStep
          step="4"
          title="Export"
          hint="When the draft finishes, build the LaTeX files here: a .tex manuscript and its .bib references, ready to drop into Overleaf and submit."
        />
      )}

      {/* Optional: package the repo as a Claude plugin. Available once a
          summary exists, folded after the paper flow as a side output. */}
      {summaryReady ? (
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Badge tone="lime">Optional</Badge>
            <CardTitle>Package this repo as a Claude plugin</CardTitle>
          </div>
          <Card className="flex flex-col gap-3">
            <CardDescription>
              Bundle the same repo into a ready-to-install Claude Code plugin:
              skills (reusable instructions Claude can load), slash commands
              (shortcuts you type to run a task), subagents (helpers that run on
              their own), hooks (actions that fire automatically on events), and
              MCP build prompts (setup for connecting Claude to external tools).
              It all ships as one plugin.json file. A tool other people can
              install counts as an original contribution.
            </CardDescription>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                variant="lime"
                onClick={handleExtractPlugin}
                disabled={pluginLoading || repoUrl.trim().length === 0}
              >
                {pluginLoading ? <Spinner size={16} /> : null}
                {pluginLoading
                  ? "Extracting"
                  : plugin
                    ? "Re-extract plugin"
                    : "Create Claude plugin"}
              </Button>
              {plugin ? (
                <Button variant="secondary" onClick={downloadPlugin}>
                  Download {plugin.plugin_name || "plugin"}.zip
                </Button>
              ) : null}
            </div>
            {repoUrl.trim().length === 0 ? (
              <p className="text-xs text-muted">
                Add a repo URL in step 1 to package a plugin.
              </p>
            ) : null}
            {plugin ? (
              <p className="text-xs text-muted">
                {plugin.manifest?.description ??
                  `Manifest: ${plugin.manifest?.name ?? plugin.plugin_name}`}
              </p>
            ) : null}
            {pluginError ? (
              <p className="text-sm text-danger">{pluginError}</p>
            ) : null}
          </Card>
        </section>
      ) : null}
    </div>
  );
}
