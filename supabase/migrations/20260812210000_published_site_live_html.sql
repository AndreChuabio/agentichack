-- Publish v2 correction: separate the draft render from the one being served.
--
-- published_site.html was doing both jobs, so a rebuild of an already-live site
-- replaced the public page instantly with no second action -- the exact thing
-- "draft by default" exists to prevent. A user who ticked another piece of
-- evidence and rebuilt to preview it would have published it by doing so, while
-- the wizard told them they were looking at a private draft.
--
-- html is now the draft. live_html is what /u/<slug> serves, and it changes only
-- when the user takes the explicit publish action. A shared link keeps serving
-- the previously published render until then, so neither rebuilding nor
-- unpublishing can surprise anyone.

alter table public.published_site add column live_html text not null default '';

-- Rows that predate this column and were already live keep serving what they
-- were serving rather than going blank.
update public.published_site set live_html = html where published = true;
