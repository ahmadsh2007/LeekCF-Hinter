-- 004: the single door the public API reads through. Additive, one transaction.
-- Design: docs/superpowers/specs/2026-10-18-phases1-5-design.md
--
-- A row appears here only when BOTH contests involved are over:
--   * the contest of the problem that was asked for, and
--   * the contest of the problem that actually holds the hints (a duplicate resolves to its canonical),
-- where "over" means phase FINISHED and at least 2 hours after the scheduled end (keep in sync with
-- COOLDOWN in src/workers/contest_monitor/contestProtector.py). The hint holder must also be HINTS_GENERATED.
-- So even if some worker wrote hints early, nothing is served while a contest is live.
--
-- The view runs with its owner's rights (Postgres default), so it can read the tables that have RLS and no
-- policies. That makes it the only thing the public (anon) key can read. Supabase grants new objects to
-- anon/authenticated by default, so the grants are reset explicitly.

begin;

create or replace view public.public_hints as
select
  p.id                       as problem_id,
  p.contest_id,
  p."index",
  p.name,
  p.rating,
  p.tags,
  src.id                     as hints_problem_id,
  h.hint_level,
  h.content,
  h.grounded_in_tutorial,
  h.llm_model_used,
  h.created_at               as generated_at
from public.problems p
join public.contests pc  on pc.id = p.contest_id
join public.problems src on src.id = coalesce(p.canonical_problem_id, p.id)
join public.contests sc  on sc.id = src.contest_id
join public.hints h      on h.problem_id = src.id
where src.stage_status = 'HINTS_GENERATED'
  and pc.phase = 'FINISHED'
  and sc.phase = 'FINISHED'
  and now() >= pc.start_time + pc.duration_seconds * interval '1 second' + interval '2 hours'
  and now() >= sc.start_time + sc.duration_seconds * interval '1 second' + interval '2 hours';

revoke all on public.public_hints from public, anon, authenticated;
grant select on public.public_hints to anon, authenticated;

commit;
