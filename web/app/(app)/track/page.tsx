"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { api } from "@/lib/api";
import type { EvidenceInput, EvidenceLedger } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { LegalDisclaimer } from "@/components/LegalDisclaimer";
import { CriterionCard } from "./CriterionCard";
import { CRITERIA_GUIDE, RECOMMENDED_FIRST } from "./types";
import type {
  ItemFormValues,
  LiveCriterionGroup,
  LiveEvidenceInput,
  LiveLedger,
} from "./types";

/** O-1A petitions must meet at least three of the eight criteria. */
const REQUIRED_TO_QUALIFY = 3;
const START_HERE_DISMISSED_KEY = "merit.track.startHereDismissed";

/** Subscribe to cross-tab storage changes for useSyncExternalStore. */
function subscribeToStorage(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/**
 * Adapt the form values to the live POST/PATCH body. The shared api client
 * types its parameter as EvidenceInput (lib/types.ts) but the live API reads
 * snake_case fields (evidence_url, evidence_date). We build the real body and
 * cast only at this boundary; lib/* is never modified.
 */
function toEvidenceInput(
  criterion: string,
  values: ItemFormValues,
): EvidenceInput {
  const body: LiveEvidenceInput = {
    criterion,
    title: values.title,
    description: values.description,
    evidence_url: values.evidence_url,
    evidence_date: values.evidence_date ? values.evidence_date : null,
  };
  return body as unknown as EvidenceInput;
}

/** The live ledger is returned by api.evidence.list(); cast the cast-only JSON. */
function asLiveLedger(ledger: EvidenceLedger): LiveLedger {
  return ledger as unknown as LiveLedger;
}

export default function TrackPage() {
  const [ledger, setLedger] = useState<LiveLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [entitled, setEntitled] = useState<boolean | null>(null);
  const [checkingOut, setCheckingOut] = useState(false);
  const [purchaseNote, setPurchaseNote] = useState<string | null>(null);

  // Read the dismissed flag from localStorage in an SSR-safe way: the server
  // snapshot is always "dismissed" so the card never flashes during hydration,
  // and the client reads the real value. A local override handles same-session
  // dismissals without needing to re-subscribe.
  const [dismissOverride, setDismissOverride] = useState(false);
  const storedDismissed = useSyncExternalStore(
    subscribeToStorage,
    () => localStorage.getItem(START_HERE_DISMISSED_KEY) === "1",
    () => true,
  );
  const startHereDismissed = storedDismissed || dismissOverride;

  const dismissStartHere = useCallback(() => {
    setDismissOverride(true);
    localStorage.setItem(START_HERE_DISMISSED_KEY, "1");
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.evidence.list();
      setLedger(asLiveLedger(data));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      try {
        const data = await api.evidence.list();
        if (active) {
          setLedger(asLiveLedger(data));
          setError(null);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleCreate = useCallback(
    async (criterion: string, values: ItemFormValues) => {
      await api.evidence.create(toEvidenceInput(criterion, values));
      await refresh();
    },
    [refresh],
  );

  const handleUpdate = useCallback(
    async (criterion: string, id: string, values: ItemFormValues) => {
      await api.evidence.update(
        id,
        toEvidenceInput(criterion, values) as Partial<EvidenceInput>,
      );
      await refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await api.evidence.remove(id);
      await refresh();
    },
    [refresh],
  );

  const handleNarrative = useCallback(async (criterion: string) => {
    const { narrative } = await api.evidence.narrative(criterion);
    return narrative;
  }, []);

  const handleDossier = useCallback(async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await api.dossier();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "o1a-evidence-dossier.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  }, []);

  const handleUnlock = useCallback(async () => {
    setCheckingOut(true);
    setDownloadError(null);
    try {
      const { url } = await api.billing.checkout();
      window.location.href = url;
    } catch (e) {
      setDownloadError((e as Error).message);
      setCheckingOut(false);
    }
  }, []);

  // Load the dossier entitlement. After a Stripe return (?purchased=dossier) the
  // webhook may lag, so poll a few times before giving up.
  useEffect(() => {
    let cancelled = false;
    const justPurchased =
      new URLSearchParams(window.location.search).get("purchased") === "dossier";

    async function load(attempt: number): Promise<void> {
      try {
        const { entitled: paid } = await api.billing.entitlement("dossier");
        if (cancelled) return;
        setEntitled(paid);
        if (justPurchased && paid) {
          setPurchaseNote("Payment received -- your full dossier is unlocked.");
        } else if (justPurchased && !paid && attempt < 5) {
          setTimeout(() => void load(attempt + 1), 2000);
        }
      } catch {
        if (!cancelled) setEntitled(false);
      }
    }
    void load(0);
    return () => {
      cancelled = true;
    };
  }, []);

  const criteria: LiveCriterionGroup[] = useMemo(
    () => ledger?.criteria ?? [],
    [ledger],
  );

  // How many criteria have at least one declared item, capped at the three
  // needed to qualify. This is what drives the friendly progress row.
  const started = useMemo(
    () => criteria.filter((g) => g.items.length > 0).length,
    [criteria],
  );
  const towardGoal = Math.min(started, REQUIRED_TO_QUALIFY);
  const remaining = Math.max(REQUIRED_TO_QUALIFY - started, 0);
  const hasAnyEvidence = criteria.some((g) => g.items.length > 0);

  // The criterion we point first-timers at: the recommended one if it is still
  // empty, otherwise the first empty criterion we can find.
  const firstActionKey = useMemo(() => {
    const recommended = criteria.find(
      (g) => g.criterion === RECOMMENDED_FIRST && g.items.length === 0,
    );
    if (recommended) return recommended.criterion;
    const firstEmpty = criteria.find((g) => g.items.length === 0);
    return firstEmpty?.criterion ?? null;
  }, [criteria]);

  const firstActionName = firstActionKey
    ? (CRITERIA_GUIDE[firstActionKey]?.name ?? firstActionKey)
    : null;

  const showStartHere = !startHereDismissed && !hasAnyEvidence && !loading;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Badge tone="primary">O-1A Evidence Ledger</Badge>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink">
          Track your extraordinary-ability record
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          The O-1A visa is for people with extraordinary ability. To qualify you
          need to show strong evidence in at least {REQUIRED_TO_QUALIFY} of 8
          areas. Add what you have under each area below, and we will help you
          turn it into a petition-ready dossier.
        </p>
      </header>

      {loading ? (
        <div className="flex items-center gap-3 rounded-2xl border border-black/5 bg-surface px-5 py-8 text-muted shadow-[0_4px_24px_-8px_rgba(31,26,46,0.12)]">
          <Spinner size={20} />
          <span className="text-sm">Loading your evidence ledger.</span>
        </div>
      ) : error ? (
        <div className="flex flex-col items-start gap-3 rounded-2xl border border-danger/20 bg-danger/5 px-5 py-6">
          <p className="text-sm text-danger">{error}</p>
          <Button variant="secondary" size="sm" onClick={() => refresh()}>
            Try again
          </Button>
        </div>
      ) : (
        <>
          <section className="flex flex-col gap-5 rounded-2xl border border-black/5 bg-surface p-6 shadow-[0_4px_24px_-8px_rgba(31,26,46,0.12)]">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm text-muted">Your progress</p>
                <p className="text-sm text-muted">
                  {remaining > 0
                    ? `${remaining} more ${
                        remaining === 1 ? "area" : "areas"
                      } to reach the minimum of ${REQUIRED_TO_QUALIFY}`
                    : `You have evidence in the ${REQUIRED_TO_QUALIFY}+ areas needed to qualify`}
                </p>
              </div>
              <p className="font-display text-2xl font-bold text-ink">
                <span className="text-primary">{started}</span> of 8 areas
                started
              </p>
              <div
                className="h-2.5 w-full overflow-hidden rounded-full bg-black/5"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={REQUIRED_TO_QUALIFY}
                aria-valuenow={towardGoal}
                aria-label={`Progress toward the minimum of ${REQUIRED_TO_QUALIFY} criteria`}
              >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{
                    width: `${(towardGoal / REQUIRED_TO_QUALIFY) * 100}%`,
                  }}
                />
              </div>
              <p className="text-xs text-muted">
                Counting areas where you have added at least one piece of
                evidence. Quality matters too, so add your strongest examples.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {criteria.map((group) => {
                const guide = CRITERIA_GUIDE[group.criterion];
                const hasEvidence = group.items.length > 0;
                return (
                  <span
                    key={group.criterion}
                    title={group.label}
                    className="inline-flex"
                  >
                    <Badge tone={hasEvidence ? "success" : "neutral"}>
                      {guide ? guide.name : group.label}
                    </Badge>
                  </span>
                );
              })}
            </div>
          </section>

          {showStartHere ? (
            <section className="flex flex-col gap-3 rounded-2xl border border-primary/15 bg-primary-50/50 p-6">
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <Badge tone="primary">Start here</Badge>
                  <h2 className="font-display text-lg font-bold text-ink">
                    New here? Add one piece of evidence to begin
                  </h2>
                </div>
                <Button variant="ghost" size="sm" onClick={dismissStartHere}>
                  Dismiss
                </Button>
              </div>
              <p className="max-w-2xl text-sm leading-relaxed text-muted">
                You do not need to fill in everything. Aim for at least{" "}
                {REQUIRED_TO_QUALIFY} of the 8 areas below. Each area expands
                with plain-language examples of what counts.{" "}
                {firstActionName
                  ? `A simple place to begin is ${firstActionName}.`
                  : ""}
              </p>
              {firstActionName ? (
                <div>
                  <Button variant="primary" size="sm" onClick={dismissStartHere}>
                    Start with {firstActionName}
                  </Button>
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="flex flex-col gap-4">
            {criteria.map((group) => (
              <CriterionCard
                key={group.criterion}
                group={group}
                defaultOpen={showStartHere && group.criterion === firstActionKey}
                onCreate={(values) => handleCreate(group.criterion, values)}
                onUpdate={(id, values) =>
                  handleUpdate(group.criterion, id, values)
                }
                onDelete={handleDelete}
                onNarrative={() => handleNarrative(group.criterion)}
              />
            ))}
          </section>

          <section className="flex flex-col gap-3 rounded-2xl border border-black/5 bg-surface p-6 shadow-[0_4px_24px_-8px_rgba(31,26,46,0.12)]">
            <div className="flex flex-col gap-1">
              <h2 className="font-display text-base font-semibold text-ink">
                Export your dossier
              </h2>
              <p className="max-w-2xl text-sm leading-relaxed text-muted">
                When you have evidence in place, download a single PDF that
                organizes everything by criterion, ready to share with a lawyer
                or attach to your petition.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {entitled === false ? (
                <Button
                  variant="primary"
                  onClick={handleUnlock}
                  disabled={checkingOut || !hasAnyEvidence}
                >
                  {checkingOut ? (
                    <>
                      <Spinner size={16} /> Redirecting to checkout
                    </>
                  ) : (
                    "Unlock full dossier ($99)"
                  )}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={handleDossier}
                  disabled={downloading || !hasAnyEvidence || entitled === null}
                >
                  {downloading ? (
                    <>
                      <Spinner size={16} /> Preparing dossier
                    </>
                  ) : (
                    "Download dossier (PDF)"
                  )}
                </Button>
              )}
              {!hasAnyEvidence ? (
                <span className="text-xs text-muted">
                  Add at least one piece of evidence to enable the export.
                </span>
              ) : entitled === false ? (
                <span className="text-xs text-muted">
                  One-time unlock. Your evidence and per-criterion narratives stay
                  free.
                </span>
              ) : null}
            </div>
            {purchaseNote ? (
              <p className="rounded-2xl bg-success/10 px-4 py-2.5 text-sm text-success">
                {purchaseNote}
              </p>
            ) : null}
            {downloadError ? (
              <p className="rounded-2xl bg-danger/10 px-4 py-2.5 text-sm text-danger">
                {downloadError}
              </p>
            ) : null}
            <LegalDisclaimer />
          </section>
        </>
      )}
    </div>
  );
}
