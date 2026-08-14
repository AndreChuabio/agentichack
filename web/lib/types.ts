/**
 * Shared types for the Merit frontend.
 * These mirror the FastAPI backend contract at NEXT_PUBLIC_API_BASE_URL.
 */

export interface ResearchSummary {
  problem: string;
  contribution: string;
  method: string;
  results: string;
  limitations: string;
  keywords: string[];
  venue_hints?: string[];
}

export interface IngestResult {
  summary: ResearchSummary;
  repo_url: string;
  files_analyzed?: number;
  notes?: string;
  session_id?: string;
}

export interface Venue {
  name: string;
  type: string;
  score: number;
  deadline?: string | null;
  url?: string | null;
  rationale?: string;
  acceptance_rate?: number | null;
}

/** A call-for-papers entry, as listed on the /cfp landing page. */
export interface Cfp {
  id: string;
  name: string;
  scope: string;
  deadline: string | null;
  format: string;
  url: string;
}

export interface Citation {
  key: string;
  title: string;
  authors?: string;
  year?: number | string;
  venue?: string;
  url?: string;
}

export interface DraftSection {
  name: string;
  text: string;
}

export interface DraftDone {
  sections: Record<string, string>;
  citations?: Citation[];
}

/** Published-site state, restored on the Publish page at mount. */
export interface SiteStatus {
  built: boolean;
  live: boolean;
  url?: string | null;
}

export interface ExportResult {
  tex: string;
  bib: string;
}

export interface PluginResult {
  plugin_name: string;
  manifest: PluginManifest;
  zip_base64: string;
}

export interface PluginManifest {
  name: string;
  version?: string;
  description?: string;
  [key: string]: unknown;
}

/* ----- Track: O-1A evidence ledger ----- */

/**
 * The 8 O-1A criteria keys. Confirm exact keys at runtime via GET /evidence.
 */
export type O1ACriterion =
  | "awards"
  | "membership"
  | "published_material"
  | "judging"
  | "original_contributions"
  | "scholarly_articles"
  | "critical_role"
  | "high_salary";

export interface EvidenceItem {
  id: string;
  criterion: string;
  title: string;
  description?: string;
  url?: string | null;
  strength?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface EvidenceInput {
  criterion: string;
  title: string;
  description?: string;
  url?: string | null;
  strength?: number | null;
}

export interface EvidenceCriterion {
  criterion: string;
  label?: string;
  items: EvidenceItem[];
  satisfied: boolean;
  narrative?: string | null;
}

export interface EvidenceLedger {
  criteria: EvidenceCriterion[];
  satisfied_count: number;
  total: number;
}

/* ----- Market: profile + outreach ----- */

export interface Profile {
  name?: string;
  title?: string;
  bio?: string;
  field?: string;
  links?: string[];
  highlights?: string[];
  [key: string]: unknown;
}

export interface DraftCard {
  id?: string;
  channel?: string;
  recipient?: string;
  subject?: string;
  body: string;
  purpose?: string;
}

export interface OutreachRow {
  id: string;
  purpose: string;
  channel?: string;
  recipient?: string;
  subject?: string;
  body?: string;
  status?: string;
  created_at?: string;
  ts?: string | null;
  posted?: boolean;
  recipient_name?: string;
  recipient_contact?: string;
}

/** A suggested person/lead to reach, from web search. */
export interface PersonLead {
  name: string;
  detail?: string;
  url?: string;
  email?: string;
}

export interface PeopleResponse {
  configured: boolean;
  people: PersonLead[];
  /** Set when configured is false: explains contact discovery is optional. */
  reason?: string;
}

/** Body for recording a draft sent to a recipient. */
export interface SentInput {
  purpose: string;
  channel?: string;
  recipient_name?: string;
  recipient_contact?: string;
  draft_id?: string;
}

/* ----- Auth ----- */

export interface MeResponse {
  id: string;
  email?: string;
  [key: string]: unknown;
}

/* ----- Draft streaming handlers ----- */

export interface DraftHandlers {
  onDelta: (section: string, text: string) => void;
  onSection: (section: string) => void;
  onDone: (done: DraftDone) => void;
  onError: (error: string) => void;
}

/* ----- Assist (Help me) streaming ----- */

/** Which Merit surface the question is asked from. */
export type AssistSurface =
  | "track"
  | "productize"
  | "market"
  | "publish"
  | "cfp";

/** Request body for the streaming /assist endpoint. */
export interface AssistRequest {
  question: string;
  surface: AssistSurface;
  context?: Record<string, unknown>;
}

/** Callbacks the assist stream drives as the coaching answer arrives. */
export interface AssistHandlers {
  onDelta: (text: string) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

/* ----- Publish: portfolio site ----- */

export interface SkippedRepo {
  repo_url: string;
  reason: string;
}

export interface SiteTheme {
  palette: string;
  layout: string;
}

export interface BuildSiteResponse {
  site_name: string;
  theme: SiteTheme;
  html_preview: string;
  zip_base64: string;
  skipped: SkippedRepo[];
  /** The slug the hosted copy is filed under. Stable across rebuilds. */
  slug: string;
  /** Where the hosted copy answers once published. A draft 404s here. */
  public_url: string;
}

/** One repository as the publish picker offers it. */
export interface RepoOption {
  full_name: string;
  html_url: string;
  description: string;
  language: string;
  stars: number;
  pushed_at: string;
  fork: boolean;
}

/** The caller's repositories, plus whichever they picked last time. */
export interface ReposResponse {
  repos: RepoOption[];
  selected: string[];
}

/** Where a published site answers. */
export interface LiveUrlResponse {
  url: string;
}

/* ----- Market: profile autofill and resume upload ----- */

/** Whether one pasted link could be read, and why not when it could not. */
export interface SourceStatus {
  source: string;
  ok: boolean;
  detail: string;
}

/** Proposed profile values the user accepts field by field. */
export interface AutofillResponse {
  proposed: Record<string, string>;
  sources: SourceStatus[];
}

/** Text extracted from an uploaded resume, for the user to review. */
export interface ResumeTextResponse {
  resume_text: string;
}
