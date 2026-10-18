-- 002: merge interactive specs into problem_specifications and drop the leftover tables.
-- DESTRUCTIVE: back up the database first. Apply only after 001.
-- Design: docs/superpowers/specs/2026-10-18-phase0-foundation-design.md

begin;

-- The old interactive table stored the Interaction section in output_specification.
-- In the merged table it lives in interaction_specification and output_specification stays NULL.
-- If a problem somehow exists in both tables, keep its standard row and just add the interaction text.
insert into public.problem_specifications
  (problem_id, time_limit_ms, memory_limit_mb, statement_text, input_specification,
   output_specification, interaction_specification, notes)
select problem_id, time_limit_ms, memory_limit_mb, statement_text, input_specification,
       null, output_specification, notes
from public.interactive_problem_specifications
on conflict (problem_id) do update
  set interaction_specification = excluded.interaction_specification;

-- Refuse to drop anything unless every interactive row arrived intact.
do $$
declare
  unmerged integer;
begin
  select count(*) into unmerged
  from public.interactive_problem_specifications i
  left join public.problem_specifications p using (problem_id)
  where p.interaction_specification is distinct from i.output_specification;

  if unmerged > 0 then
    raise exception '% interactive specification row(s) were not merged; nothing was dropped', unmerged;
  end if;
end $$;

drop table public.interactive_problem_specifications;
drop table public."sample_tests_ARCHIEVED";

commit;
