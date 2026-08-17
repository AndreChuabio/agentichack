"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ContactResult, PersonLead } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CardDescription,
  CardTitle,
  Input,
  Spinner,
  Textarea,
} from "@/components/ui";
import { LegalDisclaimer } from "@/components/LegalDisclaimer";

/**
 * Outreach purposes accepted by the backend (OutreachGenerateRequest.purpose).
 */
const PURPOSES = [
  {
    id: "VISA",
    label: "Visa",
    blurb:
      "Ask someone for a reference letter or evidence toward an O-1A or EB-1 case.",
  },
  {
    id: "CAREER",
    label: "Career",
    blurb: "Reach out about a job, a role, or a referral.",
  },
  {
    id: "NETWORK",
    label: "Network",
    blurb: "Introduce yourself, ask for advice, or request a warm intro.",
  },
  {
    id: "BRAND",
    label: "Brand",
    blurb: "Pitch a talk, podcast, or collaboration to grow your visibility.",
  },
  {
    id: "SERVICE",
    label: "Service",
    blurb: "Offer your consulting or services to a potential client.",
  },
] as const;

type Purpose = (typeof PURPOSES)[number]["id"];

interface DraftCardView {
  channel: string;
  markdown: string;
  contentTypeId: string;
  draftId: string;
  error: string | null;
}

interface OutreachLogView {
  id: number | string;
  ts: string | null;
  purpose: string;
  channel: string;
  recipientName: string;
  recipientContact: string;
  posted: boolean;
}

function str(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function toCardView(raw: unknown): DraftCardView {
  const r = (raw ?? {}) as Record<string, unknown>;
  const errorValue = r["error"];
  return {
    channel: str(r, "channel"),
    markdown: str(r, "markdown") || str(r, "body"),
    contentTypeId: str(r, "content_type_id"),
    draftId: str(r, "draft_id"),
    error: typeof errorValue === "string" ? errorValue : null,
  };
}

function toLogView(raw: unknown): OutreachLogView {
  const r = (raw ?? {}) as Record<string, unknown>;
  const id = r["id"];
  return {
    id: typeof id === "number" || typeof id === "string" ? id : "",
    ts: str(r, "ts") || str(r, "created_at") || null,
    purpose: str(r, "purpose"),
    channel: str(r, "channel"),
    recipientName: str(r, "recipient_name"),
    recipientContact: str(r, "recipient_contact"),
    posted: r["posted"] === true,
  };
}

function formatTs(ts: string | null): string {
  if (!ts) return "";
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleString();
}

function purposeLabel(id: string): string {
  return PURPOSES.find((p) => p.id === id)?.label ?? id;
}

/** Lightweight email shape check for the recipient field. */
function isValidEmail(value: string): boolean {
  const trimmed = value.trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);
}

/** Pull a subject line out of a draft body, or fall back to a sensible default. */
function deriveSubject(body: string, purpose: string): string {
  for (const line of body.split("\n").slice(0, 6)) {
    const match = line.match(/subject[:\-]\s*(.+)/i);
    if (match) {
      return match[1].replace(/[*#]/g, "").trim();
    }
  }
  return `${purposeLabel(purpose)} outreach`;
}

interface OutreachStudioProps {
  /** Reports the current outreach step (2 generate, 3 recipient, 4 send). */
  onStepChange?: (step: number) => void;
}

export function OutreachStudio({ onStepChange }: OutreachStudioProps) {
  const [purpose, setPurpose] = useState<Purpose>("VISA");
  const [context, setContext] = useState("");
  const [cards, setCards] = useState<DraftCardView[]>([]);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [hasGenerated, setHasGenerated] = useState(false);

  // Shared recipient for the generated drafts.
  const [toName, setToName] = useState("");
  const [toEmail, setToEmail] = useState("");

  // People discovery.
  const [people, setPeople] = useState<PersonLead[]>([]);
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [peopleConfigured, setPeopleConfigured] = useState(true);
  const [peopleReason, setPeopleReason] = useState("");
  const [searchedPeople, setSearchedPeople] = useState(false);

  const [log, setLog] = useState<OutreachLogView[]>([]);
  const [logLoading, setLogLoading] = useState(true);
  const [logError, setLogError] = useState<string | null>(null);

  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const rows = await api.market.outreachLog();
      setLog((rows as unknown[]).map(toLogView));
      setLogError(null);
    } catch (err: unknown) {
      setLogError(
        err instanceof Error ? err.message : "Could not load outreach history.",
      );
    } finally {
      setLogLoading(false);
    }
  }, []);

  useEffect(() => {
    Promise.resolve().then(loadLog);
  }, [loadLog]);

  async function handleGenerate(event: React.FormEvent) {
    event.preventDefault();
    setGenerating(true);
    setGenError(null);
    try {
      const result = await api.market.generateOutreach(purpose, context);
      const views = (result as unknown[]).map(toCardView);
      setCards(views);
      setEdited({});
      setHasGenerated(true);
      void loadLog();
    } catch (err: unknown) {
      setGenError(
        err instanceof Error
          ? err.message
          : "Outreach generation is unavailable right now.",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function handleFindPeople() {
    setPeopleLoading(true);
    setPeopleError(null);
    setSearchedPeople(true);
    try {
      const res = await api.market.suggestPeople(purpose, context);
      setPeopleConfigured(res.configured);
      setPeopleReason(res.reason ?? "");
      setPeople(res.people ?? []);
    } catch (err: unknown) {
      setPeopleError(
        err instanceof Error ? err.message : "Could not find people right now.",
      );
    } finally {
      setPeopleLoading(false);
    }
  }

  // Key of the lead currently chosen as recipient, so we can mark it.
  const [selectedLeadKey, setSelectedLeadKey] = useState<string | null>(null);
  // Key of the lead whose page we are currently reading for a contact.
  const [resolvingKey, setResolvingKey] = useState<string | null>(null);
  // Per-lead outcome of opening the page, keyed the same as the rows.
  const [contacts, setContacts] = useState<Record<string, ContactResult>>({});

  /**
   * Select a lead and go find a real address on its page.
   *
   * A search hit is a page, not a person: its title is a headline and its
   * snippet almost never contains an email. So we never copy the title into
   * the recipient name, and we open the page to look for the contact instead
   * of leaving the caller with an empty email field.
   */
  async function selectLead(lead: PersonLead, key: string) {
    setSelectedLeadKey(key);
    if (lead.name) setToName(lead.name);
    if (lead.email) setToEmail(lead.email);
    if (!lead.url) return;
    setResolvingKey(key);
    try {
      const found = await api.market.resolveContact(lead.url);
      setContacts((prev) => ({ ...prev, [key]: found }));
      if (found.email) setToEmail(found.email);
      if (found.name) setToName(found.name);
    } catch (err: unknown) {
      setContacts((prev) => ({
        ...prev,
        [key]: {
          found: false,
          email: "",
          emails: [],
          name: "",
          reason:
            err instanceof Error
              ? err.message
              : "Could not read that page. Open it and copy the address in.",
        },
      }));
    } finally {
      setResolvingKey((current) => (current === key ? null : current));
    }
  }

  function bodyFor(card: DraftCardView, key: string): string {
    return edited[key] ?? card.markdown;
  }

  async function handleSend(card: DraftCardView, key: string) {
    const body = bodyFor(card, key);
    const subject = deriveSubject(body, purpose);
    const mailto = `mailto:${toEmail}?subject=${encodeURIComponent(
      subject,
    )}&body=${encodeURIComponent(body)}`;
    // Open the user's mail client with the draft pre-filled.
    window.location.assign(mailto);
    setOpenedOnce(true);
    try {
      await api.market.logSent({
        purpose,
        channel: card.channel,
        recipient_name: toName,
        recipient_contact: toEmail,
        draft_id: card.draftId,
      });
      void loadLog();
    } catch {
      // Logging is best-effort; the email still opened.
    }
  }

  const [copiedId, setCopiedId] = useState<string | null>(null);
  // True once the user has opened at least one draft in their mail app.
  const [openedOnce, setOpenedOnce] = useState(false);

  async function copyCard(key: string, body: string) {
    try {
      await navigator.clipboard.writeText(body);
      setCopiedId(key);
      window.setTimeout(() => {
        setCopiedId((current) => (current === key ? null : current));
      }, 1600);
    } catch {
      // Clipboard may be blocked; ignore silently.
    }
  }

  const hasDrafts = cards.some((c) => !c.error && c.markdown);
  const emailReady = isValidEmail(toEmail);

  // Report flow progress to the page step indicator:
  // 2 = generating drafts, 3 = drafts ready / picking a recipient,
  // 4 = a recipient is set, or a draft has been opened to send.
  useEffect(() => {
    let step = 2;
    if (hasDrafts) step = 3;
    if (hasDrafts && (emailReady || openedOnce)) step = 4;
    onStepChange?.(step);
  }, [hasDrafts, emailReady, openedOnce, onStepChange]);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardTitle>Step 2: Generate a draft</CardTitle>
        <CardDescription>
          Pick why you are reaching out, add a sentence of context, and we
          write a first draft using your profile. You can edit it before
          anything is sent.
        </CardDescription>

        <form onSubmit={handleGenerate} className="mt-5 flex flex-col gap-5">
          <fieldset className="flex flex-col gap-2">
            <legend className="font-display text-sm font-medium text-ink">
              Purpose
            </legend>
            <div className="flex flex-wrap gap-2.5">
              {PURPOSES.map((option) => {
                const active = option.id === purpose;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setPurpose(option.id)}
                    aria-pressed={active}
                    title={option.blurb}
                    className={`rounded-2xl border px-4 py-2 text-sm font-display font-semibold transition-transform duration-150 ease-out hover:scale-[1.03] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-cream ${
                      active
                        ? "border-primary bg-primary text-white shadow-[0_10px_30px_-12px_rgba(109,74,255,0.5)]"
                        : "border-black/10 bg-surface text-ink hover:bg-primary-50"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-muted">
              {PURPOSES.find((p) => p.id === purpose)?.blurb}
            </p>
          </fieldset>

          <div className="flex flex-col gap-2">
            <Textarea
              name="context"
              label="Context (optional)"
              placeholder="Who are you reaching, and what is the ask? Add specifics for a sharper draft."
              className="min-h-32"
              value={context}
              onChange={(e) => setContext(e.target.value)}
            />
            <p className="text-xs text-muted">
              Example: &ldquo;Reaching Dr. Chen, who reviewed my paper at
              NeurIPS, to ask for a recommendation letter about my work on
              graph models.&rdquo;
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <Button type="submit" disabled={generating}>
              {generating ? (
                <>
                  <Spinner
                    size={16}
                    className="border-white/40 border-t-white"
                  />
                  Generating
                </>
              ) : (
                "Generate drafts"
              )}
            </Button>
          </div>
        </form>

        {genError ? (
          <div className="mt-5 rounded-2xl bg-danger/10 px-4 py-3 text-sm text-ink">
            <span className="font-medium text-danger">
              Outreach is unavailable.
            </span>{" "}
            {genError}
            <p className="mt-1 text-xs text-muted">
              The drafting service may not be set up yet. Your profile still
              saves normally.
            </p>
          </div>
        ) : null}
      </Card>

      <Card className={hasDrafts ? undefined : "opacity-60"}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Step 3: Who are you reaching?</CardTitle>
            <CardDescription>
              {hasDrafts
                ? "Find people from the web, or type in a recipient. Nothing sends automatically; you review every draft in your own email first."
                : "Generate a draft first, then add who it goes to here."}
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void handleFindPeople()}
            disabled={!hasDrafts || peopleLoading}
          >
            {peopleLoading ? (
              <>
                <Spinner size={16} />
                Searching
              </>
            ) : (
              "Find people to reach"
            )}
          </Button>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Input
            name="to_name"
            label="Recipient name"
            placeholder="Dr. Ada Lovelace"
            value={toName}
            disabled={!hasDrafts}
            onChange={(e) => setToName(e.target.value)}
          />
          <Input
            name="to_email"
            label="Recipient email"
            type="text"
            inputMode="email"
            placeholder="ada@example.com"
            value={toEmail}
            disabled={!hasDrafts}
            error={
              toEmail.trim() && !emailReady
                ? "Enter a valid email address."
                : undefined
            }
            onChange={(e) => setToEmail(e.target.value)}
          />
        </div>

        {hasDrafts && searchedPeople ? (
          <div className="mt-4">
            {peopleError ? (
              <p className="text-sm text-danger">{peopleError}</p>
            ) : !peopleConfigured ? (
              <div className="rounded-2xl bg-primary-50 px-4 py-3 text-sm text-ink">
                <span className="font-medium">Contact discovery is optional.</span>{" "}
                {peopleReason ||
                  "Enter the recipient's name and contact yourself above -- drafting works without it."}
              </div>
            ) : peopleLoading ? null : people.length === 0 ? (
              <p className="text-sm text-muted">
                No leads found. Try broader context, or enter a recipient
                manually.
              </p>
            ) : (
              <>
                <p className="mb-2 text-xs text-muted">
                  Pages from the web, not vetted contacts. Select one and we
                  read it for an address. Check the page before reaching out.
                </p>
                <ul className="flex flex-col divide-y divide-black/5">
                  {people.map((lead, i) => {
                    const leadKey = `${lead.url}-${i}`;
                    const selected = selectedLeadKey === leadKey;
                    const resolving = resolvingKey === leadKey;
                    const contact = contacts[leadKey];
                    // The snippet email is a lucky pre-fill; the resolved one
                    // came from the page body and wins when both exist.
                    const shownEmail = contact?.email || lead.email || "";
                    return (
                      <li
                        key={leadKey}
                        className="flex flex-wrap items-start justify-between gap-3 py-3 first:pt-0"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">
                            {lead.title || lead.name || lead.url}
                          </p>
                          {lead.detail ? (
                            <p className="line-clamp-2 text-xs text-muted">
                              {lead.detail}
                            </p>
                          ) : null}
                          <div className="mt-1 flex flex-wrap items-center gap-2">
                            {resolving ? (
                              <Badge tone="neutral">reading page...</Badge>
                            ) : shownEmail ? (
                              <Badge tone="success">{shownEmail}</Badge>
                            ) : contact ? (
                              <Badge tone="neutral">no email on page</Badge>
                            ) : (
                              <Badge tone="neutral">email not checked yet</Badge>
                            )}
                            {lead.url ? (
                              <a
                                href={lead.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs font-medium text-primary underline-offset-2 hover:underline"
                              >
                                Open
                              </a>
                            ) : null}
                          </div>
                          {contact && !contact.found && contact.reason ? (
                            <p className="mt-1 text-xs text-muted">
                              {contact.reason}
                            </p>
                          ) : null}
                          {contact && contact.emails.length > 1 ? (
                            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                              <span className="text-xs text-muted">
                                Also on the page:
                              </span>
                              {contact.emails.slice(1).map((addr) => (
                                <button
                                  key={addr}
                                  type="button"
                                  onClick={() => setToEmail(addr)}
                                  className="rounded-full bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary hover:text-white"
                                >
                                  {addr}
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                        {selected ? (
                          <Badge tone="primary">
                            {resolving ? "Checking" : "Selected"}
                          </Badge>
                        ) : (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={resolvingKey !== null}
                            onClick={() => void selectLead(lead, leadKey)}
                          >
                            Select
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </div>
        ) : null}
      </Card>

      {cards.length > 0 ? (
        <div className="flex flex-col gap-4">
          <LegalDisclaimer />
          <div className="grid gap-5 lg:grid-cols-2">
            {cards.map((card, index) => {
              const key = card.draftId || `${card.channel}-${index}`;
              const body = bodyFor(card, key);
              return (
                <Card key={key} interactive>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="primary">{card.channel || "Draft"}</Badge>
                      {card.contentTypeId ? (
                        <Badge tone="neutral">{card.contentTypeId}</Badge>
                      ) : null}
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => void copyCard(key, body)}
                      disabled={!body}
                    >
                      {copiedId === key ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  {card.error ? (
                    <p className="text-sm text-danger">{card.error}</p>
                  ) : (
                    <>
                      <Textarea
                        name={`draft-${key}`}
                        label="Edit before sending"
                        className="min-h-56 font-sans text-sm leading-relaxed"
                        value={body}
                        onChange={(e) =>
                          setEdited((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                      />
                      <div className="mt-3 flex flex-wrap items-center gap-3">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void handleSend(card, key)}
                          disabled={!emailReady || !body.trim()}
                        >
                          Open in email
                        </Button>
                        {!toEmail.trim() ? (
                          <span className="text-xs text-muted">
                            Add a recipient email above to send.
                          </span>
                        ) : !emailReady ? (
                          <span className="text-xs text-muted">
                            That email does not look valid yet.
                          </span>
                        ) : (
                          <span className="text-xs text-muted">
                            Opens your mail app to {toEmail}. You review and
                            send it yourself.
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      ) : hasGenerated && !genError ? (
        <Card>
          <p className="text-sm text-muted">
            No drafts came back for that purpose. Try adding more context.
          </p>
        </Card>
      ) : null}

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Recent outreach</CardTitle>
            <CardDescription>
              Drafts you opened in your email app, and when. We track that you
              opened them, not whether you actually hit send.
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void loadLog()}
            disabled={logLoading}
          >
            Refresh
          </Button>
        </div>

        {logLoading ? (
          <div className="flex items-center gap-3 text-muted">
            <Spinner size={18} />
            <span className="text-sm">Loading history</span>
          </div>
        ) : logError ? (
          <p className="text-sm text-danger">{logError}</p>
        ) : log.length === 0 ? (
          <p className="text-sm text-muted">
            No outreach yet. Generate your first batch above.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-black/5">
            {log.map((row) => (
              <li
                key={String(row.id)}
                className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge tone="pink">{purposeLabel(row.purpose)}</Badge>
                  {row.channel ? (
                    <Badge tone="neutral">{row.channel}</Badge>
                  ) : null}
                  {row.posted ? (
                    <Badge tone="success">Opened in email</Badge>
                  ) : (
                    <Badge tone="neutral">Drafted</Badge>
                  )}
                  {row.recipientName || row.recipientContact ? (
                    <span className="truncate text-sm text-ink">
                      to{" "}
                      <span className="font-medium">
                        {row.recipientName || row.recipientContact}
                      </span>
                      {row.recipientName && row.recipientContact ? (
                        <span className="text-muted">
                          {" "}
                          ({row.recipientContact})
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <span className="text-xs text-muted">{formatTs(row.ts)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
