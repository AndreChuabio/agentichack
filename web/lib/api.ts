import { createClient } from "@/lib/supabase/client";
import { getLlmKey } from "@/lib/llmKey";
import type {
  AssistHandlers,
  AssistSurface,
  AutofillResponse,
  BuildSiteResponse,
  Cfp,
  Citation,
  DraftCard,
  DraftHandlers,
  EvidenceInput,
  EvidenceItem,
  EvidenceLedger,
  ExportResult,
  IngestResult,
  LiveUrlResponse,
  MeResponse,
  OutreachRow,
  ContactResult,
  PeopleResponse,
  PluginResult,
  Profile,
  ReposResponse,
  ResearchSummary,
  ResumeTextResponse,
  SentInput,
  SiteStatus,
  Venue,
} from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "https://paperpilot-api-production.up.railway.app";

/**
 * Reads the current Supabase access token from the browser client.
 * Throws if there is no active session so callers can surface a login prompt.
 */
async function getAccessToken(): Promise<string> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) {
    throw new Error("Not authenticated");
  }
  return token;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

/**
 * Thrown by requestJson on a non-OK response. Carries the HTTP status so
 * callers can branch on specific codes (e.g. 413 "bundle too large, needs
 * confirm_large") without parsing the message string.
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function authedFetch(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  // Sent only when the user has actually set one. The repo-reading surfaces
  // refuse a request without it; every other surface falls back to Merit's key
  // and caps the caller instead, so omitting it is a supported state rather
  // than an error.
  const llmKey = getLlmKey();
  if (llmKey) {
    headers["X-LLM-Key"] = llmKey;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  return response;
}

async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await authedFetch(path, options);
  if (!response.ok) {
    const detail = await safeErrorDetail(response);
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

async function safeErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (data.detail) return JSON.stringify(data.detail);
  } catch {
    // fall through
  }
  return `Request failed (${response.status})`;
}

export const api = {
  async getMe(): Promise<MeResponse> {
    return requestJson<MeResponse>("/me");
  },

  async ingest(repoUrl: string, confirmLarge?: boolean): Promise<IngestResult> {
    return requestJson<IngestResult>("/ingest", {
      method: "POST",
      body: {
        repo_url: repoUrl,
        ...(confirmLarge ? { confirm_large: true } : {}),
      },
    });
  },

  async match(
    summary: ResearchSummary,
    limit?: number,
    horizonDays?: number,
  ): Promise<Venue[]> {
    const venues = await requestJson<(Venue & { fit_score?: number })[]>(
      "/match",
      {
        method: "POST",
        body: {
          summary,
          ...(limit !== undefined ? { limit } : {}),
          ...(horizonDays !== undefined ? { horizon_days: horizonDays } : {}),
        },
      },
    );
    // The live API names the field fit_score; the UI type uses score.
    // Accept either so a rename on one side can never render NaN.
    return venues.map((v) => ({ ...v, score: v.score ?? v.fit_score ?? 0 }));
  },

  /** Chronological listing of the shared CFP corpus, with optional filters. */
  async listCfps(filters?: {
    q?: string;
    format?: string;
    upcoming?: boolean;
  }): Promise<Cfp[]> {
    const params = new URLSearchParams();
    if (filters?.q) params.set("q", filters.q);
    if (filters?.format) params.set("format", filters.format);
    if (filters?.upcoming) params.set("upcoming", "true");
    const qs = params.toString();
    return requestJson<Cfp[]>(`/cfp${qs ? `?${qs}` : ""}`);
  },

  /**
   * Streams a paper draft via Server-Sent Events.
   * The backend emits events: delta, section, done, error.
   */
  async draft(
    summary: ResearchSummary,
    venue: Venue,
    handlers: DraftHandlers,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = await getAccessToken();
    // This path builds its own request rather than going through authedFetch,
    // so the key header has to be repeated here or a BYOK caller would be
    // metered against Merit's cap while paying for their own inference.
    const draftKey = getLlmKey();
    const response = await fetch(`${API_BASE_URL}/draft`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(draftKey ? { "X-LLM-Key": draftKey } : {}),
      },
      body: JSON.stringify({ summary, venue }),
      signal,
    });

    if (!response.ok || !response.body) {
      const detail = response.body
        ? await safeErrorDetail(response)
        : `Draft stream failed (${response.status})`;
      handlers.onError(detail);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const dispatch = (rawEvent: string) => {
      // Each SSE message is a block of "event:" / "data:" lines.
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
      const dataStr = dataLines.join("\n");
      if (!dataStr && eventName === "message") return;

      let payload: unknown = dataStr;
      if (dataStr) {
        try {
          payload = JSON.parse(dataStr);
        } catch {
          payload = dataStr;
        }
      }

      switch (eventName) {
        case "delta": {
          const p = payload as { section?: string; text?: string };
          handlers.onDelta(p.section ?? "", p.text ?? "");
          break;
        }
        case "section": {
          const p = payload as { section?: string } | string;
          handlers.onSection(
            typeof p === "string" ? p : (p.section ?? ""),
          );
          break;
        }
        case "done": {
          // The backend done event ships sections as name -> payload object
          // ({section, text, citations, stripped_ids}); the UI state is
          // name -> string. Normalize here so a payload object can never
          // reach React as a child (it white-screened the app at the exact
          // moment a draft finished).
          const raw = payload as {
            sections?: Record<string, unknown>;
            citations?: Citation[];
          };
          const sections: Record<string, string> = {};
          const collected: Citation[] = [...(raw.citations ?? [])];
          for (const [name, value] of Object.entries(raw.sections ?? {})) {
            if (typeof value === "string") {
              sections[name] = value;
            } else if (value && typeof value === "object") {
              const sp = value as { text?: string; citations?: Citation[] };
              sections[name] = sp.text ?? "";
              collected.push(...(sp.citations ?? []));
            }
          }
          const seen = new Set<string>();
          const citations: Citation[] = [];
          for (const c of collected) {
            if (!seen.has(c.key)) {
              seen.add(c.key);
              citations.push(c);
            }
          }
          handlers.onDone({ sections, citations });
          break;
        }
        case "error": {
          const p = payload as { error?: string; detail?: string } | string;
          const message =
            typeof p === "string"
              ? p
              : (p.error ?? p.detail ?? "Draft stream error");
          handlers.onError(message);
          break;
        }
        default:
          break;
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE messages are separated by a blank line. The backend emits
        // CRLF-delimited frames, so accept both \n\n and \r\n\r\n and strip
        // stray carriage returns before parsing lines.
        let sep: RegExpExecArray | null;
        while ((sep = /\r?\n\r?\n/.exec(buffer)) !== null) {
          const rawEvent = buffer.slice(0, sep.index);
          buffer = buffer.slice(sep.index + sep[0].length);
          if (rawEvent.trim()) dispatch(rawEvent.replace(/\r/g, ""));
        }
      }
      const tail = buffer.trim();
      if (tail) dispatch(tail.replace(/\r/g, ""));
    } catch (err) {
      if ((err as Error)?.name !== "AbortError") {
        handlers.onError((err as Error)?.message ?? "Draft stream aborted");
      }
    }
  },

  /**
   * Streams a coaching answer from the "Help me" assistant via SSE.
   * The backend emits events: delta, done, error.
   *
   * `context` is the current page/surface state so the answer is relevant;
   * pass the pathname and any lightweight counts the surface knows about.
   */
  async assist(
    question: string,
    surface: AssistSurface,
    handlers: AssistHandlers,
    context?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = await getAccessToken();
    const response = await fetch(`${API_BASE_URL}/assist`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        question,
        surface,
        ...(context ? { context } : {}),
      }),
      signal,
    });

    if (!response.ok || !response.body) {
      const detail = response.body
        ? await safeErrorDetail(response)
        : `Assist stream failed (${response.status})`;
      handlers.onError(detail);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const dispatch = (rawEvent: string) => {
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
      const dataStr = dataLines.join("\n");
      if (!dataStr && eventName === "message") return;

      let payload: unknown = dataStr;
      if (dataStr) {
        try {
          payload = JSON.parse(dataStr);
        } catch {
          payload = dataStr;
        }
      }

      switch (eventName) {
        case "delta": {
          const p = payload as { text?: string };
          handlers.onDelta(p.text ?? "");
          break;
        }
        case "done": {
          handlers.onDone();
          break;
        }
        case "error": {
          const p = payload as { message?: string } | string;
          const message =
            typeof p === "string"
              ? p
              : (p.message ?? "Assist stream error");
          handlers.onError(message);
          break;
        }
        default:
          break;
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Same CRLF-tolerant framing as the draft stream above.
        let sep: RegExpExecArray | null;
        while ((sep = /\r?\n\r?\n/.exec(buffer)) !== null) {
          const rawEvent = buffer.slice(0, sep.index);
          buffer = buffer.slice(sep.index + sep[0].length);
          if (rawEvent.trim()) dispatch(rawEvent.replace(/\r/g, ""));
        }
      }
      const tail = buffer.trim();
      if (tail) dispatch(tail.replace(/\r/g, ""));
    } catch (err) {
      if ((err as Error)?.name !== "AbortError") {
        handlers.onError((err as Error)?.message ?? "Assist stream aborted");
      }
    }
  },

  async exportPaper(
    summary: ResearchSummary,
    venue: Venue,
    sections: Record<string, string>,
    citations?: Citation[],
  ): Promise<ExportResult> {
    return requestJson<ExportResult>("/export", {
      method: "POST",
      body: {
        summary,
        venue,
        sections,
        ...(citations ? { citations } : {}),
      },
    });
  },

  async extractPlugin(
    repoUrl: string,
    sessionId?: string | null,
  ): Promise<PluginResult> {
    return requestJson<PluginResult>("/extract-plugin", {
      method: "POST",
      body: {
        repo_url: repoUrl,
        ...(sessionId ? { session_id: sessionId } : {}),
      },
    });
  },

  evidence: {
    async list(): Promise<EvidenceLedger> {
      return requestJson<EvidenceLedger>("/evidence");
    },

    async create(item: EvidenceInput): Promise<EvidenceItem> {
      return requestJson<EvidenceItem>("/evidence", {
        method: "POST",
        body: item,
      });
    },

    async update(
      id: string,
      patch: Partial<EvidenceInput>,
    ): Promise<EvidenceItem> {
      return requestJson<EvidenceItem>(
        `/evidence/${encodeURIComponent(id)}`,
        {
          method: "PATCH",
          body: patch,
        },
      );
    },

    async remove(id: string): Promise<void> {
      const response = await authedFetch(
        `/evidence/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(await safeErrorDetail(response));
      }
    },

    async narrative(criterion: string): Promise<{ narrative: string }> {
      return requestJson<{ narrative: string }>(
        `/evidence/${encodeURIComponent(criterion)}/narrative`,
        { method: "POST" },
      );
    },
  },

  publish: {
    /** Build a portfolio site from the caller's profile, repos, and chosen evidence. */
    async buildSite(
      repoUrls: string[],
      evidenceIds: string[],
    ): Promise<BuildSiteResponse> {
      return requestJson<BuildSiteResponse>("/publish/site", {
        method: "POST",
        body: { repo_urls: repoUrls, evidence_ids: evidenceIds },
      });
    },

    /**
     * The caller's GitHub repos for the picker, plus their last selection.
     * Pass githubUrl to list repos for a URL typed but not yet saved on the
     * profile; omitted, the server reads the saved profile URL.
     */
    async listRepos(githubUrl?: string): Promise<ReposResponse> {
      const qs = githubUrl
        ? `?github_url=${encodeURIComponent(githubUrl)}`
        : "";
      return requestJson<ReposResponse>(`/publish/repos${qs}`);
    },

    /** Whether the caller has a built site and whether it is live. */
    async status(): Promise<SiteStatus> {
      return requestJson<SiteStatus>("/publish/site/live");
    },

    /** Make the built site public. Returns the URL it now answers on. */
    async goLive(): Promise<LiveUrlResponse> {
      return requestJson<LiveUrlResponse>("/publish/site/live", {
        method: "POST",
      });
    },

    /** Take the site down and delete the stored HTML. */
    async takeDown(): Promise<void> {
      const response = await authedFetch("/publish/site/live", {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new ApiError(response.status, await safeErrorDetail(response));
      }
    },
  },

  async dossier(): Promise<Blob> {
    const response = await authedFetch("/dossier", {
      method: "POST",
      body: {},
    });
    if (!response.ok) {
      throw new Error(await safeErrorDetail(response));
    }
    return response.blob();
  },

  billing: {
    /** Whether the caller has paid for `product` (default the dossier). */
    async entitlement(
      product = "dossier",
    ): Promise<{ product: string; entitled: boolean }> {
      return requestJson<{ product: string; entitled: boolean }>(
        `/billing/entitlement?product=${encodeURIComponent(product)}`,
      );
    },
    /** Start a Stripe Checkout session; returns the URL to redirect the user to. */
    async checkout(): Promise<{ url: string }> {
      return requestJson<{ url: string }>("/billing/checkout", {
        method: "POST",
      });
    },
  },

  account: {
    /** Everything Merit stores about the caller, grouped by table. */
    async export(): Promise<Record<string, unknown>> {
      return requestJson<Record<string, unknown>>("/account/export");
    },
    /** Delete the caller's account; every per-user row cascades away. */
    async remove(): Promise<void> {
      const response = await authedFetch("/account", { method: "DELETE" });
      if (!response.ok) {
        throw new ApiError(response.status, await safeErrorDetail(response));
      }
    },
  },

  market: {
    async getProfile(): Promise<Profile> {
      return requestJson<Profile>("/market/profile");
    },

    async putProfile(p: Profile): Promise<Profile> {
      return requestJson<Profile>("/market/profile", {
        method: "PUT",
        body: p,
      });
    },

    async generateOutreach(
      purpose: string,
      context: string,
    ): Promise<DraftCard[]> {
      return requestJson<DraftCard[]>("/market/outreach/generate", {
        method: "POST",
        body: { purpose, context },
      });
    },

    async outreachLog(): Promise<OutreachRow[]> {
      return requestJson<OutreachRow[]>("/market/outreach/log");
    },

    async suggestPeople(
      purpose: string,
      context: string,
    ): Promise<PeopleResponse> {
      return requestJson<PeopleResponse>("/market/outreach/people", {
        method: "POST",
        body: { purpose, context },
      });
    },

    /**
     * Open one lead page and pull the best contact address off it. Search
     * snippets never carry an email, so this is the only path that finds one.
     */
    async resolveContact(url: string): Promise<ContactResult> {
      return requestJson<ContactResult>("/market/outreach/contact", {
        method: "POST",
        body: { url },
      });
    },

    /**
     * Propose profile fields from the caller's pasted links.
     * Never writes the profile: the user accepts fields one at a time.
     */
    async autofillProfile(urls: {
      github_url: string;
      linkedin_url: string;
      scholar_url: string;
      site_url: string;
    }): Promise<AutofillResponse> {
      return requestJson<AutofillResponse>("/market/profile/autofill", {
        method: "POST",
        body: urls,
      });
    },

    /** Multipart, so this bypasses requestJson but still uses the shared token. */
    async uploadResume(file: File): Promise<ResumeTextResponse> {
      const token = await getAccessToken();
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${API_BASE_URL}/market/profile/resume`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!response.ok) {
        throw new ApiError(response.status, await safeErrorDetail(response));
      }
      return (await response.json()) as ResumeTextResponse;
    },

    async logSent(input: SentInput): Promise<void> {
      const response = await authedFetch("/market/outreach/sent", {
        method: "POST",
        body: input,
      });
      if (!response.ok) {
        throw new Error(await safeErrorDetail(response));
      }
    },
  },
};
