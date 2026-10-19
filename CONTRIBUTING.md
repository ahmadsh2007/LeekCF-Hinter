# Contributing

Thank you for wanting to help. Small fixes and big ideas are both welcome.

## Run it locally

```bash
npm install
python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m unittest discover -s tests      # Python tests, all offline
node --test tests/*.test.ts                        # TypeScript tests, all offline
```

Nothing in the test suites touches Codeforces, Supabase or an AI model, so you can run them with no accounts and no keys.
`README.md` explains the pipeline, and `docs/superpowers/specs/` has the design decisions behind it.

## How we work

- **Tests first.** A new behaviour gets a test that fails for the right reason before the code that makes it pass. Fixes for
  bugs found on real data (a page the scraper rejected, a hint the checker let through) are especially welcome: add the
  failing case as a test.
- **Match the surrounding code**: camelCase names, short comments that say *why*, dependencies injected so tests stay offline.
- **Keep changes focused** and describe what you checked, including what you could not check.
- **Never commit secrets** (`.env`, keys, service account files). `config/.env` is git-ignored; keep real keys outside the repo.

## Ideas that would help most

- A browser extension that shows the hints on codeforces.com (the public API is documented at `GET /` and `/v1/openapi.json`).
- More model providers behind `src/services/llm/` (the interface is `generate(system, user, schema)` plus a `.model` name).
- A bigger, honest evaluation of hint quality: sample problems, compare hints with the editorials, publish the numbers.
- Hints in other languages, and better handling of problems with unusual layouts.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`), the same as the project.
