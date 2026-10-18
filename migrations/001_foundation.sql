-- 001: foundation. Additive, one transaction, safe to apply before deploying the new code.
-- Apply this BEFORE running the new scripts: the old ones write memory_limit_ms, which this renames.
-- Design: docs/superpowers/specs/2026-10-18-phase0-foundation-design.md

begin;

-- Defaults: new rows no longer need the caller to invent stage_status / timestamps,
-- so an upsert can leave them out and never overwrite existing values.
alter table public.problems alter column stage_status set default 'DISCOVERED';
alter table public.problems alter column created_at set default now();
alter table public.problems alter column updated_at set default now();
alter table public.hints alter column created_at set default now();
alter table public.tutorials alter column scraped_at set default now();
-- A contest's start time must always be supplied, never "now".
alter table public.contests alter column start_time drop default;

-- Unrated problems are NULL (was -1).
update public.problems set rating = null where rating = -1;

-- The value is megabytes.
alter table public.problem_specifications rename column memory_limit_ms to memory_limit_mb;
alter table public.interactive_problem_specifications rename column memory_limit_ms to memory_limit_mb;

-- Status columns were free text.
alter table public.problems add constraint problems_stage_status_check
  check (stage_status in ('DISCOVERED', 'SCRAPED_WAITING_FOR_CONTEST', 'WAITING_FOR_TUTORIAL',
                          'TUTORIAL_FOUND', 'HINTS_GENERATED', 'FAILED', 'DUPLICATE'));
alter table public.contests add constraint contests_phase_check
  check (phase in ('BEFORE', 'CODING', 'PENDING_SYSTEM_TEST', 'SYSTEM_TEST', 'FINISHED'));
alter table public.contests add constraint contests_type_check
  check (type in ('CF', 'IOI', 'ICPC'));

-- Hints: one row per (problem, level), so regenerating is an upsert.
alter table public.hints add constraint hints_hint_level_check check (hint_level between 1 and 5);
alter table public.hints add constraint hints_problem_id_hint_level_key unique (problem_id, hint_level);
alter table public.hints add column grounded_in_tutorial boolean not null default false;

-- Dedup pointer and scraper retry bookkeeping.
-- canonical_problem_id has no ON DELETE action on purpose: deleting a canonical problem
-- that still has duplicates must fail loudly.
alter table public.problems
  add column canonical_problem_id character varying,
  add column scrape_attempts smallint not null default 0,
  add column last_error text;
alter table public.problems add constraint problems_canonical_problem_id_fkey
  foreign key (canonical_problem_id) references public.problems(id);
alter table public.problems add constraint problems_duplicate_pointer_check
  check ((stage_status = 'DUPLICATE') = (canonical_problem_id is not null));
alter table public.problems add constraint problems_canonical_not_self_check
  check (canonical_problem_id <> id);

-- One specs table for standard and interactive problems. A page may have an Output section,
-- an Interaction section, or both; it must have at least one.
alter table public.problem_specifications
  add column statement_hash text,
  add column interaction_specification text,
  alter column output_specification drop not null;
alter table public.problem_specifications add constraint problem_specifications_output_or_interaction_check
  check (num_nonnulls(output_specification, interaction_specification) >= 1);

-- Deleting a problem deletes its children.
alter table public.problem_specifications
  drop constraint problem_specifications_problem_id_fkey,
  add constraint problem_specifications_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;
alter table public.interactive_problem_specifications
  drop constraint interactive_problem_specifications_problem_id_fkey,
  add constraint interactive_problem_specifications_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;
alter table public.sample_tests
  drop constraint sample_tests_problem_id_fkey,
  add constraint sample_tests_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;
alter table public."sample_tests_ARCHIEVED"
  drop constraint sample_tests_problem_id_fkey,
  add constraint sample_tests_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;
alter table public.tutorials
  drop constraint tutorials_problem_id_fkey,
  add constraint tutorials_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;
alter table public.hints
  drop constraint hints_problem_id_fkey,
  add constraint hints_problem_id_fkey
    foreign key (problem_id) references public.problems(id) on delete cascade;

-- Fail the whole migration if any child foreign key was missed.
do $$
declare
  offenders text;
begin
  select string_agg(conrelid::regclass::text || ' (' || conname || ')', ', ')
    into offenders
  from pg_constraint
  where contype = 'f'
    and confrelid = 'public.problems'::regclass
    and conrelid <> 'public.problems'::regclass
    and confdeltype <> 'c';

  if offenders is not null then
    raise exception 'Foreign keys to problems without ON DELETE CASCADE: %', offenders;
  end if;
end $$;

commit;
