"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import type { AssistSurface } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";

/** Map the current pathname to a known Merit surface. Defaults to track. */
function surfaceForPath(pathname: string): AssistSurface {
  if (pathname.startsWith("/productize")) return "productize";
  if (pathname.startsWith("/market")) return "market";
  if (pathname.startsWith("/publish")) return "publish";
  if (pathname.startsWith("/cfp")) return "cfp";
  return "track";
}

interface SurfaceCopy {
  label: string;
  intro: string;
  prompts: string[];
}

/** Per-surface starter copy so a non-expert always has a way in. */
const SURFACE_COPY: Record<AssistSurface, SurfaceCopy> = {
  track: {
    label: "Track",
    intro:
      "Track is your evidence ledger for the O-1A visa. You only need to satisfy three of the eight criteria. Ask me which ones fit you.",
    prompts: [
      "What are the eight O-1A criteria in plain English?",
      "Which criteria should someone like me focus on first?",
      "What counts as evidence for original contributions?",
    ],
  },
  productize: {
    label: "Productize",
    intro:
      "Productize turns your repo into a paper and a Claude plugin. Both become real evidence you can Track. Ask me how they map to the criteria.",
    prompts: [
      "How does a published paper help my O-1A case?",
      "What does the Claude plugin count as?",
      "What should I do after I generate a paper?",
    ],
  },
  market: {
    label: "Market",
    intro:
      "Market is your profile plus outreach drafts to reach people who can support your case. Ask me who to contact and why.",
    prompts: [
      "Who should I reach out to for my O-1A case?",
      "How do recommendation letters fit the criteria?",
      "What makes outreach for judging or media effective?",
    ],
  },
  publish: {
    label: "Publish",
    intro:
      "Publish turns your repos and profile into a hosted portfolio site with a public link. Ask me how a portfolio strengthens your case.",
    prompts: [
      "How does a portfolio site help my O-1A case?",
      "What should my portfolio lead with?",
      "Who should I share my published site with?",
    ],
  },
  cfp: {
    label: "Call for Papers",
    intro:
      "These are venues and deadlines where you can submit your paper. A published paper becomes evidence you can Track. Ask me where to submit.",
    prompts: [
      "Which venue should I submit my work to first?",
      "How does presenting at a conference help my case?",
      "What is the difference between a workshop and a full paper?",
    ],
  },
};

/**
 * Global "Help me" AI assistant: a floating button that opens a slide-over
 * panel. Streams a coaching answer from POST /assist, passing the current
 * surface and pathname as context so replies stay relevant. Mounted once in
 * AppShell so it is available on every authenticated surface.
 */
export function HelpAssistant() {
  const pathname = usePathname();
  const surface = useMemo(() => surfaceForPath(pathname), [pathname]);
  const copy = SURFACE_COPY[surface];

  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const answerRef = useRef<HTMLDivElement | null>(null);

  // Cancel any in-flight stream when the panel unmounts.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Close on Escape; focus the input when the panel opens.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    inputRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Keep the latest streamed text in view.
  useEffect(() => {
    if (answerRef.current) {
      answerRef.current.scrollTop = answerRef.current.scrollHeight;
    }
  }, [answer]);

  const ask = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed || streaming) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStreaming(true);
      setError(null);
      setAnswer("");

      await api.assist(
        trimmed,
        surface,
        {
          onDelta: (text) => setAnswer((prev) => prev + text),
          onDone: () => setStreaming(false),
          onError: (message) => {
            setError(message);
            setStreaming(false);
          },
        },
        { path: pathname, surface },
        controller.signal,
      );
    },
    [pathname, surface, streaming],
  );

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      void ask(question);
    },
    [ask, question],
  );

  return (
    <>
      <button
        type="button"
        aria-label="Open the Help me assistant"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 rounded-2xl bg-primary px-5 py-3 font-display text-sm font-semibold text-white shadow-[0_10px_30px_-12px_rgba(109,74,255,0.6)] transition-transform duration-150 ease-out hover:scale-[1.03] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-cream"
      >
        <span
          aria-hidden="true"
          className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/25 font-display text-xs font-bold"
        >
          ?
        </span>
        Help me
      </button>

      {open ? (
        <div className="fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-ink/30 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Merit help assistant"
            className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-black/5 bg-cream shadow-[0_0_60px_-12px_rgba(31,26,46,0.4)]"
          >
            <header className="flex items-start justify-between gap-4 border-b border-black/5 px-5 py-4">
              <div>
                <h2 className="font-display text-lg font-semibold text-ink">
                  Help me
                </h2>
                <p className="mt-0.5 text-xs font-medium uppercase tracking-wide text-primary">
                  {copy.label}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Close the assistant"
                onClick={() => setOpen(false)}
              >
                Close
              </Button>
            </header>

            <div
              ref={answerRef}
              className="flex-1 overflow-y-auto px-5 py-4"
            >
              <p className="text-sm leading-relaxed text-muted">
                {copy.intro}
              </p>

              {!answer && !streaming && !error ? (
                <div className="mt-5">
                  <p className="font-display text-sm font-medium text-ink">
                    Try asking
                  </p>
                  <ul className="mt-2 flex flex-col gap-2">
                    {copy.prompts.map((prompt) => (
                      <li key={prompt}>
                        <button
                          type="button"
                          onClick={() => {
                            setQuestion(prompt);
                            void ask(prompt);
                          }}
                          className="w-full rounded-2xl border border-black/5 bg-surface px-4 py-3 text-left text-sm text-ink shadow-sm transition-colors hover:bg-primary-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                        >
                          {prompt}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {answer || streaming ? (
                <div className="mt-5 rounded-2xl border border-black/5 bg-surface px-4 py-3 shadow-sm">
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
                    {answer}
                    {streaming ? (
                      <span className="ml-1 inline-flex align-middle">
                        <Spinner size={14} label="Thinking" />
                      </span>
                    ) : null}
                  </p>
                </div>
              ) : null}

              {error ? (
                <div className="mt-5 rounded-2xl border border-danger/30 bg-danger/5 px-4 py-3">
                  <p className="text-sm text-danger">{error}</p>
                </div>
              ) : null}
            </div>

            <form
              onSubmit={onSubmit}
              className="border-t border-black/5 px-5 py-4"
            >
              <textarea
                ref={inputRef}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void ask(question);
                  }
                }}
                placeholder="Ask about your O-1A case in plain English"
                rows={2}
                className="w-full resize-none rounded-2xl border border-black/10 bg-surface px-4 py-3 text-sm leading-relaxed text-ink placeholder:text-muted/70 shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
              />
              <div className="mt-3 flex items-center justify-between gap-3">
                <p className="text-xs text-muted">
                  General guidance, not legal advice.
                </p>
                <Button
                  type="submit"
                  size="sm"
                  disabled={streaming || !question.trim()}
                >
                  {streaming ? "Answering" : "Ask"}
                </Button>
              </div>
            </form>
          </aside>
        </div>
      ) : null}
    </>
  );
}

export default HelpAssistant;
