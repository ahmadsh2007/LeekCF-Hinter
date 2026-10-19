-- 003: bookkeeping for the hint generator and the tutorial finder, and interactive problems that have no Input
-- section. Additive, one transaction. Apply it before running the new scraper.
-- Design: docs/superpowers/specs/2026-10-18-phases1-5-design.md

begin;

-- Counts failed hint generations (scrape_attempts keeps counting failed scrapes).
alter table public.problems add column hint_attempts smallint not null default 0;

-- One official tutorial per problem, so the finder can upsert instead of piling up rows.
-- Fails (and rolls everything back) if duplicate rows already exist.
alter table public.tutorials add constraint tutorials_problem_id_key unique (problem_id);

-- Some interactive problems (e.g. Codeforces 1155E) go from the statement straight to the Interaction section, so
-- they have no Input text. Every other problem still must have one.
alter table public.problem_specifications alter column input_specification drop not null;
alter table public.problem_specifications add constraint problem_specifications_input_or_interaction_check
  check (input_specification is not null or interaction_specification is not null);

commit;
