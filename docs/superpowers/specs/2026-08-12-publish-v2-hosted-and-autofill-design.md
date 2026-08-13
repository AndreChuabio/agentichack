# Publish v2: hosted link, repo picker, profile autofill, resume upload

Status: approved design, not yet implemented
Date: 2026-08-12
Supersedes parts of: `2026-08-12-portfolio-site-generator-design.md`

## Context

Publish v1 shipped a zip the user pushes to their own `<user>.github.io` repo.
Four changes were asked for after seeing it:

1. The feature should hand back a **link**, not a zip.
2. The Market profile's GitHub field is a bare profile URL. The user should pick
   **which repos** get read, both when building a site and when creating a profile.
3. The profile form should **autofill** from pasted links so nobody hand-writes
   an About paragraph.
4. Resume should accept a **PDF or Word upload**, not only pasted text.

Merit-hosted was chosen over a GitHub push for the link, with the zip retained
and the push deferred to v3 behind an interface. Nav order changed separately:
Market now leads, ahead of Productize.

## Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Link | `meritai.me/u/<slug>`, Merit-hosted | Live immediately, no OAuth, no stored GitHub tokens. GitHub push deferred behind `PublishTarget` |
| Zip | Retained beside the link | Anyone who wants the files still gets them; no capability is removed |
| Going live | Draft by default, explicit second action to publish | A zip is inert until the user pushes. A hosted URL is live on click, carrying whatever evidence was ticked |
| Repo selection | Fetch the user's repo list, user ticks | Replaces the v1 URL textarea and the bare profile URL in Market |
| Autofill sources | GitHub, personal site, Scholar, LinkedIn best-effort | Chosen with the LinkedIn login wall known and accepted |
| Resume | PDF and DOCX upload, text extracted server-side | `resume_text` stays the stored field, so nothing downstream changes |

## A. Hosted publishing

### Schema

One row per user, so a person has one site.

```sql
create table public.published_site (
    user_id    uuid primary key references auth.users(id) on delete cascade,
    slug       text not null unique,
    html       text not null default '',
    published  boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.published_site enable row level security;

-- Anonymous readers may see only a LIVE site. A draft is invisible to everyone
-- but the service-role backend, which is what makes "draft by default" a real
-- boundary rather than a UI convention.
create policy published_site_select_live on public.published_site
    for select to anon, authenticated using (published = true);

grant select on public.published_site to anon, authenticated;
```

Writes happen only through the backend as service role, which bypasses RLS, so
there is no insert or update policy: a client can never publish itself live.

`user_profile` gains the repo selection:

```sql
alter table public.user_profile
    add column selected_repos jsonb not null default '[]'::jsonb;
```

### PublishTarget

```python
class PublishTarget(Protocol):
    def save_draft(self, user_id: str, slug: str, html: str) -> None: ...
    def publish(self, user_id: str) -> str: ...
    def unpublish(self, user_id: str) -> None: ...
```

Three verbs rather than two, because building and going live are separate
actions here: `save_draft` files the render, `publish` flips an already-filed
draft and returns the public URL, `unpublish` removes it. `HostedTarget` is the
only implementation in v2. The GitHub-push adapter in v3 implements the same
three, so nothing in the generator changes when it lands.

### Slugs

Derived with the existing `site_slug`, then made unique by appending `-2`, `-3`
on collision. A reserved list (`login`, `signup`, `market`, `productize`,
`track`, `publish`, `cfp`, `privacy`, `api`, `auth`, `u`) is refused so a site
can never shadow an app route. Slug is stable once assigned: rebuilding updates
the HTML in place rather than minting a second URL, so a shared link keeps working.

### The public page

`web/app/u/[slug]/page.tsx`, outside the `(app)` group and absent from
`PROTECTED_PREFIXES`, so it is public. It reads `published_site` through the
Supabase **anon** client, which means RLS is what serves the page: a draft
returns no row and the route renders 404. Reading as service role here would
make the draft boundary a code convention instead of a database one.

The stored HTML is injected with `dangerouslySetInnerHTML`. That is safe for the
same reason v1's zip was: every value in it was escaped by `site_render._e` at
generation time and the model never emits markup. The route re-states that in a
comment, because it is the one place in the app where stored HTML is rendered.

### Lifecycle

- **Build** writes the row with `published = false` and returns the preview and zip.
- **Publish** flips the flag and returns the URL.
- **Unpublish** deletes the row outright. Setting a flag would leave the HTML,
  and the evidence in it, sitting in a table after the user asked for it gone.

## B. Repo picker

`github_ingest.list_user_repos(owner: str, limit: int = 100) -> list[RepoSummary]`
using the existing `_gh_client()`. `RepoSummary` carries `full_name`, `html_url`,
`description`, `language`, `stars`, `updated_at`, `fork`. Sorted by last push,
forks last.

`GET /publish/repos` returns the list for the caller's stored `github_url`.
The Publish wizard replaces its URL textarea with this checklist, and the Market
profile gains the same picker so the GitHub field stops being a bare profile
link. The selection persists to `user_profile.selected_repos` and pre-ticks next
visit; the build still sends explicit repo URLs, so the stored selection is a
convenience default and never the authority — the same rule the evidence ids follow.

## C. Profile autofill

`POST /market/profile/autofill` takes the URLs already on the form and returns
**proposed** values. It never writes the profile.

Each source is fetched independently and a failure is reported, never hidden:

| Source | How | Expectation |
|---|---|---|
| GitHub | `list_user_repos` + profile bio via `_gh_client()` | Reliable |
| Personal site | `nimble_client.extract(url, session_id)` | Usually works |
| Google Scholar | `nimble_client.extract` | Blocks intermittently |
| LinkedIn | `nimble_client.extract` with render | Usually blocked by the login wall |

`nimble_client.extract` returns `None` on misconfiguration, timeout, or non-2xx
and never raises, so a dead source is a `None` to report rather than an
exception to catch.

One LLM call turns whatever came back into proposed `name`, `title`, `about`,
`voice_tone`. The response carries per-source status so the UI can say
**"LinkedIn could not be read - paste your About or upload your resume"** rather
than leaving a silently empty field. The user reviews and accepts per field;
nothing overwrites a field the user already filled without their click.

## D. Resume upload

`POST /market/profile/resume`, multipart, the first upload path in the codebase.

- Accepts `application/pdf` and `.docx`. Legacy `.doc` is refused by name.
- 5 MB cap, enforced by reading at most that many bytes rather than trusting
  the declared content length.
- Type is checked by magic bytes (`%PDF`, `PK\x03\x04`), not by the client's
  declared content type or the filename extension.
- Text extracted with `pypdf` and `python-docx`, both new dependencies.
- Returns extracted text for review; the user saves it into `resume_text` as
  normal. The endpoint does not write the profile.
- The file itself is never stored. Only the extracted text reaches the database,
  which keeps a resume full of a home address out of blob storage.

## Quota

Autofill and resume extraction spend Merit's key and third-party calls, so both
count against a new quota:

```python
ENRICH = Quota(kind_prefix="profile_enrich", limit=20, window_days=30, noun="profile autofill")
```

Both endpoints must emit a `profile_enrich.end` trace event on a session bound to
the caller. A quota whose event is never emitted, or is emitted against an
unbound session, counts zero forever — the bug found in v1 and previously in the
dossier. A regression test asserts the emitted kind satisfies the quota's `LIKE`
pattern and carries the caller's `user_id`.

## Error handling

Follows the established ladder: 400 on invalid input, 403 on ownership, 413 on
an oversized upload, 415 on a rejected file type, 429 from a quota, 502 on
pipeline failure, deliberate `HTTPException`s re-raised rather than masked.
A dead autofill source degrades to a reported status, never a failed request.

## Testing

- Slug collision yields `-2`; a reserved slug is refused.
- A draft row is not readable by the anon client; flipping `published` makes it readable.
- Unpublish deletes the row rather than flagging it.
- Rebuilding keeps the same slug.
- `list_user_repos` sorts by push date with forks last.
- Autofill with every source returning `None` still returns 200 with per-source
  failure statuses and proposes nothing.
- Autofill never writes `user_profile`.
- Resume upload: a 6 MB file is 413; a `.doc` is 415; a PDF whose magic bytes
  say otherwise is 415; a real PDF and a real DOCX both extract text.
- Both enrichment endpoints emit a countable `profile_enrich.end` bound to the caller.
- Playwright: the public `/u/<slug>` route renders a live site and 404s a draft.

## Out of scope for v2

GitHub OAuth push, custom domains, analytics on the hosted page, multi-page
sites, and storing the uploaded file itself.

## Verification

1. `pytest` green from the repo root.
2. `cd web && npm run lint && npx tsc --noEmit` clean.
3. Build a site, confirm `/u/<slug>` 404s while it is a draft.
4. Publish it, confirm the URL renders for a logged-out browser.
5. Unpublish, confirm the row is gone and the URL 404s again.
6. Autofill with a LinkedIn URL and confirm the UI names the failure.
7. Upload a real PDF resume and a real DOCX and confirm text lands in the field.
