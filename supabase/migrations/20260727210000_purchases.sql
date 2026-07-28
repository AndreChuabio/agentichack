-- Purchases: Merit's own one-time revenue (the paid O-1A dossier unlock).
--
-- Rows are created 'pending' when a Stripe Checkout session starts and moved to
-- 'paid' only by the signature-verified webhook (server-side, service role).
-- The dossier route gates on a 'paid' row for (user_id, 'dossier').

create table public.purchases (
    id                    uuid primary key default gen_random_uuid(),
    user_id               uuid not null references auth.users(id) on delete cascade,
    product               text not null,
    status                text not null default 'pending',
    amount_cents          integer,
    currency              text not null default 'usd',
    stripe_session_id     text unique,
    stripe_payment_intent text,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);

create index purchases_user_product on public.purchases (user_id, product);

-- App-level isolation: the backend connects as service role and always scopes
-- by user_id. RLS adds defense in depth for any direct client read. Writes
-- happen only via the webhook (service role, which bypasses RLS), so there is no
-- authenticated insert/update policy -- a client can never grant itself a purchase.
alter table public.purchases enable row level security;

create policy purchases_select_own on public.purchases
    for select to authenticated using ((select auth.uid()) = user_id);

grant select on public.purchases to authenticated;
