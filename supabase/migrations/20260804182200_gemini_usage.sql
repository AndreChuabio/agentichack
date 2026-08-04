-- gemini_usage: per-call token usage for Gemini-on-Vertex-AI requests.
--
-- Written by paperpilot.vertex on every Vertex call (repo ingest, help
-- assistant) so the app's Google Cloud usage is verifiable in a simple
-- table rather than only buried in trace_log's jsonb payload. Mirrors
-- trace_log's per-user shape: tenant_id is nullable because a Vertex call
-- can happen outside a bound session (CLI/system paths), same as
-- trace_log.user_id.

create table public.gemini_usage (
    id          bigint generated always as identity primary key,
    ts          timestamptz not null default now(),
    surface     text not null,
    model       text not null,
    tokens_in   integer not null default 0,
    tokens_out  integer not null default 0,
    tenant_id   uuid references auth.users(id) on delete cascade
);
create index gemini_usage_tenant_ts on public.gemini_usage (tenant_id, ts desc);
create index gemini_usage_surface_ts on public.gemini_usage (surface, ts desc);

alter table public.gemini_usage enable row level security;

-- Read own, same as trace_log. Writes go through the service role (the
-- backend), so no insert policy is defined for authenticated.
create policy gemini_usage_select_own on public.gemini_usage
    for select to authenticated using ((select auth.uid()) = tenant_id);

grant select on public.gemini_usage to authenticated;
