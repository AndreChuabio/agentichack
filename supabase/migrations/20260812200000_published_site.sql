-- Publish v2: one hosted portfolio site per user, plus the repo selection that
-- feeds it. Append-only; never edit an earlier migration.

create table public.published_site (
    user_id    uuid primary key references auth.users(id) on delete cascade,
    slug       text not null unique,
    html       text not null default '',
    published  boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.published_site enable row level security;

-- Anonymous readers may see only a LIVE site. A draft returns no row to the
-- anon client at all, which is what makes "draft by default" a database
-- boundary rather than a UI convention. Writes happen only through the backend
-- as service role (which bypasses RLS), so there is deliberately no insert or
-- update policy: a client can never publish itself live.
create policy published_site_select_live on public.published_site
    for select to anon, authenticated using (published = true);

grant select on public.published_site to anon, authenticated;

-- Which repos the user picked. Adding a NOT NULL column WITH a default is a
-- metadata-only change in Postgres 11+, so this does not rewrite the table.
alter table public.user_profile
    add column selected_repos jsonb not null default '[]'::jsonb;
