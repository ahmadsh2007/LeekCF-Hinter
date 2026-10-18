-- Baseline: the public schema as exported from Supabase on 2026-10-18, BEFORE any file in this folder.
-- It is the starting point for 001/002. Run it ONLY on an empty database (e.g. a staging project), never on production.
-- Two fixes against the raw export so it runs: `tags` is text[] (the export wrote `ARRAY`), and the
-- mixed-case table name "sample_tests_ARCHIEVED" is quoted (the export left it bare, which Postgres lowercases).

CREATE TABLE public.contests (
  id integer NOT NULL,
  name text NOT NULL,
  type text NOT NULL,
  phase text NOT NULL,
  start_time timestamp with time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
  duration_seconds integer NOT NULL,
  last_check_at timestamp with time zone NOT NULL DEFAULT (now() AT TIME ZONE 'utc'::text),
  CONSTRAINT contests_pkey PRIMARY KEY (id)
);
CREATE TABLE public.problems (
  id character varying NOT NULL,
  contest_id integer NOT NULL,
  index text NOT NULL,
  name text NOT NULL,
  rating smallint,
  tags text[],
  stage_status text NOT NULL,
  created_at timestamp with time zone NOT NULL,
  updated_at timestamp with time zone NOT NULL,
  CONSTRAINT problems_pkey PRIMARY KEY (id),
  CONSTRAINT problems_contest_id_fkey FOREIGN KEY (contest_id) REFERENCES public.contests(id)
);
CREATE TABLE public.problem_specifications (
  problem_id character varying NOT NULL,
  time_limit_ms integer NOT NULL,
  memory_limit_ms integer NOT NULL,
  statement_text text NOT NULL,
  input_specification text NOT NULL,
  output_specification text NOT NULL,
  notes text,
  CONSTRAINT problem_specifications_pkey PRIMARY KEY (problem_id),
  CONSTRAINT problem_specifications_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
CREATE TABLE public."sample_tests_ARCHIEVED" (
  id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
  problem_id character varying NOT NULL,
  test_order integer NOT NULL,
  input_text text NOT NULL,
  output_text text NOT NULL,
  CONSTRAINT "sample_tests_ARCHIEVED_pkey" PRIMARY KEY (id),
  CONSTRAINT sample_tests_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
CREATE TABLE public.tutorials (
  id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
  problem_id character varying NOT NULL,
  contest_id integer NOT NULL,
  source_url text NOT NULL,
  raw_content text NOT NULL,
  author text,
  scraped_at timestamp with time zone NOT NULL,
  CONSTRAINT tutorials_pkey PRIMARY KEY (id),
  CONSTRAINT tutorials_contest_id_fkey FOREIGN KEY (contest_id) REFERENCES public.contests(id),
  CONSTRAINT tutorials_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
CREATE TABLE public.hints (
  id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
  problem_id character varying NOT NULL,
  hint_level smallint NOT NULL,
  content text NOT NULL,
  llm_model_used text NOT NULL,
  prompt_version text NOT NULL,
  created_at timestamp with time zone NOT NULL,
  CONSTRAINT hints_pkey PRIMARY KEY (id),
  CONSTRAINT hints_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
CREATE TABLE public.sample_tests (
  problem_id character varying NOT NULL,
  test_order integer NOT NULL,
  input_text text NOT NULL,
  output_text text NOT NULL,
  CONSTRAINT sample_tests_pkey PRIMARY KEY (problem_id, test_order),
  CONSTRAINT sample_tests_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
CREATE TABLE public.interactive_problem_specifications (
  problem_id character varying NOT NULL,
  time_limit_ms integer NOT NULL,
  memory_limit_ms integer NOT NULL,
  statement_text text NOT NULL,
  input_specification text NOT NULL,
  output_specification text NOT NULL,
  notes text,
  CONSTRAINT interactive_problem_specifications_pkey PRIMARY KEY (problem_id),
  CONSTRAINT interactive_problem_specifications_problem_id_fkey FOREIGN KEY (problem_id) REFERENCES public.problems(id)
);
