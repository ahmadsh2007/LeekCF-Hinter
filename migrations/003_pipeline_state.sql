-- 003: bookkeeping for the hint generator and the tutorial finder. Additive, one transaction.
-- Design: docs/superpowers/specs/2026-10-18-phases1-5-design.md

begin;

-- Counts failed hint generations (scrape_attempts keeps counting failed scrapes).
alter table public.problems add column hint_attempts smallint not null default 0;

-- One official tutorial per problem, so the finder can upsert instead of piling up rows.
-- Fails (and rolls everything back) if duplicate rows already exist.
alter table public.tutorials add constraint tutorials_problem_id_key unique (problem_id);

commit;
