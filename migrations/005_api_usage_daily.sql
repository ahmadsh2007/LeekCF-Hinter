-- 005: long-term request statistics of the public API. Additive, one transaction.
-- Cloudflare's Analytics Engine keeps data for three months; src/workers/usage/rollupUsage.py copies it here once a
-- day, so the history lasts as long as the project does. One row per day, app, route and status. No addresses and no
-- request contents are ever recorded, only counts and response times.
--
-- Row level security with no policies: the public (anon) key can neither read nor write this table. Only the secret
-- key used by the pipeline (which bypasses RLS) can. Supabase grants new tables to anon/authenticated by default, so
-- the grants are reset explicitly.

begin;

create table if not exists public.api_usage_daily (
  day               date             not null,
  client            text             not null,
  route             text             not null,
  status            integer          not null,
  requests          bigint           not null,
  cache_hits        bigint           not null,
  total_duration_ms double precision not null,
  updated_at        timestamptz      not null default now(),
  primary key (day, client, route, status)
);

alter table public.api_usage_daily enable row level security;
revoke all on public.api_usage_daily from public, anon, authenticated;

commit;
