"use client";

import { useEffect, useState } from "react";
import type { Profile, RepoOption, SourceStatus } from "@/lib/types";
import { api } from "@/lib/api";
import {
  Button,
  Card,
  CardDescription,
  CardTitle,
  Input,
  Spinner,
  Textarea,
} from "@/components/ui";

/**
 * Profile fields as defined by the live backend (ProfileOut / ProfileUpdate).
 * The shared Profile type is loose ([key: string]: unknown), so we narrow to
 * the exact string fields the market profile form edits.
 */
interface MarketProfile {
  name: string;
  title: string;
  about: string;
  voice_tone: string;
  github_url: string;
  linkedin_url: string;
  scholar_url: string;
  site_url: string;
  resume_text: string;
  /** Repos the user ticked. A GitHub URL alone says who they are, not what to read. */
  selected_repos: string[];
}

const EMPTY_PROFILE: MarketProfile = {
  name: "",
  title: "",
  about: "",
  voice_tone: "",
  github_url: "",
  linkedin_url: "",
  scholar_url: "",
  site_url: "",
  resume_text: "",
  selected_repos: [],
};

type ReposState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; repos: RepoOption[] }
  | { kind: "error"; message: string };

type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

/**
 * The fields autofill is allowed to propose. The backend is asked for exactly
 * these keys, and anything else it returns is ignored rather than written into
 * form state, so a widened prompt can never reach a field the user did not
 * expect to see change.
 */
const AUTOFILL_FIELDS = ["name", "title", "about", "voice_tone"] as const;

type AutofillField = (typeof AUTOFILL_FIELDS)[number];

const FIELD_LABELS: Record<AutofillField, string> = {
  name: "Name",
  title: "Title",
  about: "About",
  voice_tone: "Voice and tone",
};

type AutofillState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; proposed: Record<string, string>; sources: SourceStatus[] }
  | { kind: "error"; message: string };

type ResumeState =
  | { kind: "idle" }
  | { kind: "reading" }
  | { kind: "done" }
  | { kind: "error"; message: string };

function readString(source: Profile, key: keyof MarketProfile): string {
  const value = source[key];
  return typeof value === "string" ? value : "";
}

/**
 * Accept bare domains in URL fields. A non-empty value without an http(s)
 * scheme gets https:// prepended, so "andrechuabio.github.io" is saved as
 * "https://andrechuabio.github.io" rather than rejected.
 */
function normalizeUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function fromProfile(source: Profile): MarketProfile {
  return {
    name: readString(source, "name"),
    title: readString(source, "title"),
    about: readString(source, "about"),
    voice_tone: readString(source, "voice_tone"),
    github_url: readString(source, "github_url"),
    linkedin_url: readString(source, "linkedin_url"),
    scholar_url: readString(source, "scholar_url"),
    site_url: readString(source, "site_url"),
    resume_text: readString(source, "resume_text"),
    selected_repos: readStringList(source, "selected_repos"),
  };
}

/** selected_repos arrives from a jsonb column, so anything else means empty. */
function readStringList(source: Profile, key: keyof MarketProfile): string[] {
  const value = source[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

interface ProfileFormProps {
  /** Called after the profile saves successfully, to advance the flow. */
  onSaved?: () => void;
}

export function ProfileForm({ onSaved }: ProfileFormProps) {
  const [profile, setProfile] = useState<MarketProfile>(EMPTY_PROFILE);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>({ kind: "idle" });
  const [autofill, setAutofill] = useState<AutofillState>({ kind: "idle" });
  const [resume, setResume] = useState<ResumeState>({ kind: "idle" });
  const [repos, setRepos] = useState<ReposState>({ kind: "idle" });

  useEffect(() => {
    let active = true;
    api.market
      .getProfile()
      .then((result) => {
        if (!active) return;
        setProfile(fromProfile(result));
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(
          err instanceof Error ? err.message : "Could not load your profile.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  /**
   * Load the repos behind the pasted GitHub URL so the user can tick the ones
   * worth reading. A profile URL says who somebody is; it does not say which of
   * forty repos should shape their site or their outreach drafts.
   */
  async function loadRepos() {
    setRepos({ kind: "loading" });
    try {
      // Pass the typed URL so repos list even before the profile is saved;
      // the server otherwise reads only the stored profile.
      const result = await api.publish.listRepos(
        profile.github_url.trim() || undefined,
      );
      setRepos({ kind: "done", repos: result.repos });
      // Only adopt the stored selection when the user has not picked yet in
      // this session, so loading the list never discards their current ticks.
      if (profile.selected_repos.length === 0 && result.selected.length > 0) {
        update("selected_repos", result.selected);
      }
    } catch (err: unknown) {
      setRepos({
        kind: "error",
        message:
          err instanceof Error ? err.message : "Could not read your repositories",
      });
    }
  }

  function toggleRepo(url: string) {
    const chosen = profile.selected_repos.includes(url)
      ? profile.selected_repos.filter((item) => item !== url)
      : [...profile.selected_repos, url];
    update("selected_repos", chosen);
  }

  function update<K extends keyof MarketProfile>(
    key: K,
    value: MarketProfile[K],
  ) {
    setProfile((prev) => ({ ...prev, [key]: value }));
    if (save.kind === "saved" || save.kind === "error") {
      setSave({ kind: "idle" });
    }
  }

  /**
   * Ask the backend what it can read from the pasted links.
   *
   * The response is held as a proposal and nothing is written into the form
   * until the user accepts a field, because overwriting an About paragraph
   * somebody wrote by hand is worse than not autofilling at all.
   */
  async function runAutofill() {
    setAutofill({ kind: "running" });
    try {
      const result = await api.market.autofillProfile({
        github_url: normalizeUrl(profile.github_url),
        linkedin_url: normalizeUrl(profile.linkedin_url),
        scholar_url: normalizeUrl(profile.scholar_url),
        site_url: normalizeUrl(profile.site_url),
      });
      setAutofill({
        kind: "done",
        proposed: result.proposed,
        sources: result.sources,
      });
    } catch (err: unknown) {
      setAutofill({
        kind: "error",
        message:
          err instanceof Error ? err.message : "Could not read your links.",
      });
    }
  }

  /** Accept one proposed field. Never assigns the proposal wholesale. */
  function accept(key: AutofillField, value: string) {
    update(key, value);
    setAutofill((prev) => {
      if (prev.kind !== "done") return prev;
      const remaining = { ...prev.proposed };
      delete remaining[key];
      return { ...prev, proposed: remaining };
    });
  }

  /**
   * Extract text from an uploaded PDF or .docx into the resume field.
   *
   * The file is not stored anywhere: the backend returns the words and the
   * user still presses Save profile, so nothing changes behind their back.
   */
  async function handleResume(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) return;
    setResume({ kind: "reading" });
    try {
      const result = await api.market.uploadResume(file);
      update("resume_text", result.resume_text);
      setResume({ kind: "done" });
    } catch (err: unknown) {
      setResume({
        kind: "error",
        message:
          err instanceof Error ? err.message : "Could not read that file.",
      });
    } finally {
      // Clear the input so re-picking the same file fires change again.
      input.value = "";
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSave({ kind: "saving" });
    try {
      const payload: Profile = {
        ...profile,
        github_url: normalizeUrl(profile.github_url),
        linkedin_url: normalizeUrl(profile.linkedin_url),
        scholar_url: normalizeUrl(profile.scholar_url),
        site_url: normalizeUrl(profile.site_url),
      };
      const result = await api.market.putProfile(payload);
      setProfile(fromProfile(result));
      setSave({ kind: "saved" });
      onSaved?.();
    } catch (err: unknown) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : "Could not save profile.",
      });
    }
  }

  // Only the fields the form knows how to set, and only where the backend
  // actually proposed something.
  const proposals =
    autofill.kind === "done"
      ? AUTOFILL_FIELDS.map((key) => ({
          key,
          value: autofill.proposed[key] ?? "",
        })).filter((proposal) => proposal.value.trim().length > 0)
      : [];

  if (loading) {
    return (
      <Card>
        <div className="flex items-center gap-3 text-muted">
          <Spinner size={18} />
          <span className="text-sm">Loading your profile</span>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>Step 1: Your profile</CardTitle>
          <CardDescription>
            This is what every draft is written from. Name and About are
            required; everything else is optional but makes drafts sharper.
          </CardDescription>
        </div>
      </div>

      {loadError ? (
        <div className="mb-5 rounded-2xl bg-warning/10 px-4 py-3 text-sm text-ink">
          Started with a blank profile. {loadError}
        </div>
      ) : null}

      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <div className="grid gap-5 sm:grid-cols-2">
          <Input
            name="name"
            label="Name (required)"
            placeholder="Ada Lovelace"
            value={profile.name}
            onChange={(e) => update("name", e.target.value)}
          />
          <Input
            name="title"
            label="Title (optional)"
            placeholder="Research Engineer"
            value={profile.title}
            onChange={(e) => update("title", e.target.value)}
          />
        </div>

        <Textarea
          name="about"
          label="About (required)"
          placeholder="A few sentences on who you are and what you build."
          value={profile.about}
          onChange={(e) => update("about", e.target.value)}
        />

        <Input
          name="voice_tone"
          label="Voice and tone (optional)"
          placeholder="Warm, direct, a little playful"
          value={profile.voice_tone}
          onChange={(e) => update("voice_tone", e.target.value)}
        />

        <div className="grid gap-5 sm:grid-cols-2">
          <Input
            name="github_url"
            label="GitHub URL (optional)"
            type="text"
            inputMode="url"
            placeholder="https://github.com/you"
            value={profile.github_url}
            onChange={(e) => update("github_url", e.target.value)}
          />
          <Input
            name="linkedin_url"
            label="LinkedIn URL (optional)"
            type="text"
            inputMode="url"
            placeholder="https://linkedin.com/in/you"
            value={profile.linkedin_url}
            onChange={(e) => update("linkedin_url", e.target.value)}
          />
          <Input
            name="scholar_url"
            label="Google Scholar URL (optional)"
            type="text"
            inputMode="url"
            placeholder="https://scholar.google.com/..."
            value={profile.scholar_url}
            onChange={(e) => update("scholar_url", e.target.value)}
          />
          <Input
            name="site_url"
            label="Personal site URL (optional)"
            type="text"
            inputMode="url"
            placeholder="https://you.dev"
            value={profile.site_url}
            onChange={(e) => update("site_url", e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 px-4 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">Which repositories to read</p>
              <p className="text-sm text-slate-600">
                Your GitHub URL says who you are. Pick the repos worth reading so
                drafts and your site are built from the right work.
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={loadRepos}
              disabled={repos.kind === "loading" || !profile.github_url.trim()}
            >
              {repos.kind === "loading" ? (
                <>
                  <Spinner size={16} />
                  Loading
                </>
              ) : (
                "Load my repositories"
              )}
            </Button>
          </div>

          {!profile.github_url.trim() && (
            <p className="text-sm text-slate-500">
              Add your GitHub URL above first.
            </p>
          )}

          {repos.kind === "error" && (
            <p className="text-sm text-red-600">{repos.message}</p>
          )}

          {repos.kind === "done" && repos.repos.length === 0 && (
            <p className="text-sm text-slate-500">
              No public repositories found for that account.
            </p>
          )}

          {repos.kind === "done" && repos.repos.length > 0 && (
            <ul className="max-h-64 space-y-2 overflow-y-auto">
              {repos.repos.map((repo) => (
                <li key={repo.html_url} className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    id={`repo-${repo.full_name}`}
                    className="mt-1"
                    checked={profile.selected_repos.includes(repo.html_url)}
                    onChange={() => toggleRepo(repo.html_url)}
                  />
                  <label
                    htmlFor={`repo-${repo.full_name}`}
                    className="text-sm leading-snug"
                  >
                    <span className="font-medium">{repo.full_name}</span>
                    {repo.language && (
                      <span className="text-slate-500"> · {repo.language}</span>
                    )}
                    {repo.stars > 0 && (
                      <span className="text-slate-500"> · {repo.stars}★</span>
                    )}
                    {repo.fork && (
                      <span className="text-slate-500"> · fork</span>
                    )}
                    {repo.description && (
                      <span className="block text-slate-600">
                        {repo.description}
                      </span>
                    )}
                  </label>
                </li>
              ))}
            </ul>
          )}

          {profile.selected_repos.length > 0 && (
            <p className="text-sm text-slate-600">
              {profile.selected_repos.length} selected. Saved with your profile.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3 rounded-2xl bg-primary-50/60 px-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              onClick={runAutofill}
              disabled={autofill.kind === "running"}
            >
              {autofill.kind === "running" ? (
                <>
                  <Spinner size={16} />
                  Reading your links
                </>
              ) : (
                "Autofill from my links"
              )}
            </Button>
            <span className="text-sm text-muted">
              Reads the links above and proposes values. Nothing changes until
              you accept a field and save.
            </span>
          </div>

          {autofill.kind === "error" ? (
            <span className="text-sm font-medium text-danger">
              {autofill.message}
            </span>
          ) : null}

          {autofill.kind === "done" ? (
            <>
              <ul className="flex flex-col gap-1 text-sm">
                {autofill.sources.map((source) => (
                  <li key={source.source}>
                    <span
                      className={
                        source.ok
                          ? "font-medium text-success"
                          : "font-medium text-danger"
                      }
                    >
                      {source.source}
                    </span>
                    <span className="text-muted">
                      {": "}
                      {source.ok
                        ? "read"
                        : source.detail || "could not be read"}
                    </span>
                  </li>
                ))}
              </ul>

              {proposals.length === 0 ? (
                <span className="text-sm text-muted">
                  Nothing to propose from those links.
                </span>
              ) : (
                <ul className="flex flex-col gap-3">
                  {proposals.map((proposal) => (
                    <li
                      key={proposal.key}
                      className="flex flex-col gap-1 rounded-2xl bg-surface px-4 py-3"
                    >
                      <span className="font-display text-sm font-medium text-ink">
                        {FIELD_LABELS[proposal.key]}
                      </span>
                      <span className="text-sm text-muted">
                        Now: {profile[proposal.key] || "(empty)"}
                      </span>
                      <span className="text-sm text-ink">
                        Proposed: {proposal.value}
                      </span>
                      <div>
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() => accept(proposal.key, proposal.value)}
                        >
                          Use this
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor="resume_file"
            className="font-display text-sm font-medium text-ink"
          >
            Upload a resume (optional)
          </label>
          <input
            id="resume_file"
            name="resume_file"
            type="file"
            accept=".pdf,.docx"
            disabled={resume.kind === "reading"}
            onChange={handleResume}
            className="text-sm text-ink file:mr-3 file:rounded-2xl file:border-0 file:bg-primary-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary"
          />
          <span className="text-xs text-muted">
            PDF or .docx, under 5 MB. The file itself is never stored: only the
            text below, and only once you save.
          </span>
          {resume.kind === "reading" ? (
            <span className="text-sm text-muted">Reading the file</span>
          ) : null}
          {resume.kind === "done" ? (
            <span className="text-sm font-medium text-success">
              Text pulled in. Check it, then press Save profile.
            </span>
          ) : null}
          {resume.kind === "error" ? (
            <span className="text-sm font-medium text-danger">
              {resume.message}
            </span>
          ) : null}
        </div>

        <Textarea
          name="resume_text"
          label="Resume text (optional)"
          placeholder="Paste your resume or a longer bio for richer drafts."
          className="min-h-40"
          value={profile.resume_text}
          onChange={(e) => update("resume_text", e.target.value)}
        />

        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" disabled={save.kind === "saving"}>
            {save.kind === "saving" ? (
              <>
                <Spinner size={16} className="border-white/40 border-t-white" />
                Saving
              </>
            ) : (
              "Save profile"
            )}
          </Button>
          {save.kind === "saved" ? (
            <span className="text-sm font-medium text-success">
              Saved. Your drafts will use the latest profile.
            </span>
          ) : null}
          {save.kind === "error" ? (
            <span className="text-sm font-medium text-danger">
              {save.message}
            </span>
          ) : null}
        </div>
      </form>
    </Card>
  );
}
