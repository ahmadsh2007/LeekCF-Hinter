# Launching the public API (free)

The API is read-only, needs no key from its users, and is documented by itself: `GET /` is a readable page and
`GET /v1/openapi.json` is an OpenAPI 3.1 description that any API tool can import. This guide puts it online for free.

## What "online" means here

Three pieces, each with its own job:

| Piece | Job | Where it runs | Cost |
|---|---|---|---|
| Pipeline (`scripts/daily.sh`, `scripts/backfill.sh`) | finds problems, scrapes, writes hints into the database | your Mac, or GitHub Actions (`docs/automation.md`) | free |
| Database (Supabase) | stores everything; the `public_hints` view is the only thing the public key can read | Supabase free plan | free |
| API (`src/api`) | answers `GET /v1/problems/{contest}/{index}/hints` and serves the docs | **Cloudflare Workers** (this guide) | free |

Why Cloudflare Workers: the free plan allows 100,000 requests a day
([pricing](https://developers.cloudflare.com/workers/platform/pricing/)), needs no server to look after, caches answers at
the edge (most requests never reach the database), and keeps request logs. Other free hosts exist but sleep when idle
(Render's free tier, about 30-50 seconds to wake) or forbid commercial use (Vercel's Hobby plan).

## What you need to do (about 20 minutes, once)

1. **Make a free Cloudflare account** (dash.cloudflare.com). No domain is needed: you get an address like
   `https://leekcf-hinter-api.YOUR-SUBDOMAIN.workers.dev`.
2. **Log in from the terminal:** `npx wrangler login` (opens the browser once).
3. **Give the Worker its two settings** (they are stored at Cloudflare, not in git):
   ```bash
   npx wrangler secret put SUPABASE_DATABASE_URL        # paste the project URL
   npx wrangler secret put SUPABASE_PUBLISHABLE_KEY     # paste the PUBLISHABLE key, never the secret key
   ```
   The Worker refuses to start with a secret key.
4. **Deploy:** `npx wrangler deploy`. It prints the address. (Afterwards every change to the API on `main` can be
   deployed by GitHub itself: see "Backups and API deploys" in `docs/automation.md`.)
5. **Put that address in `wrangler.toml`** as `PUBLIC_BASE_URL` and deploy again, so the documentation shows the real URL.
6. **Check it:**
   ```bash
   curl https://YOUR-ADDRESS/v1/health
   curl https://YOUR-ADDRESS/v1/problems/1061/A/hints      # 200 with hints once that problem has them
   ```
   Then open the address in a browser for the documentation page.

What was verified before this guide was written: the Worker bundles with `wrangler` (753 KiB, far below the free limit),
runs in Cloudflare's real Workers runtime on a laptop (`wrangler dev`), reads the real database view with the publishable
key, and the public key can read nothing but that view. **Not verified:** the actual `wrangler deploy` to your account,
Cloudflare's edge cache and Analytics Engine behaviour in production. Run the two curl checks above after deploying.

## Which Supabase project is the public one

The project that holds the data is the public one. Nothing needs copying: the finished database (schema, problems, tutorials,
hints, the locked-down `public_hints` view) is where the pipeline has been writing. The Worker is pointed at it with
`SUPABASE_DATABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (step 3 above).

**Give it a name you will not delete by accident.** In the Supabase dashboard open the project, go to *Project Settings →
General* (the same page that holds "Delete project") and change the project name to something distinctive such as
`LeekCF-Hinter-PRODUCTION-do-not-delete`. Per [Supabase's guide](https://supabase.com/docs/guides/platform/delete-project.md)
deleting a project makes you type its exact name, so a long, odd name is a real speed bump, and deleting it also makes its
backups and keys unusable. The project reference in the address should not change when you rename it; check that the
address in the browser and in `~/leekcf-env/staging.env` still works afterwards (any `curl` of the API, or ask for a check).

**Keep your own copy of the data.** The hints cost days of model time to produce, and a deleted or lost project takes them
with it. Do not rely only on Supabase: export the tables to files on your own disk from time to time.

## Before you announce it

- **Run the pipeline on the production database**, not only the staging project (`docs/staging-runbook.md`, "Production"),
  and point the Worker at that project's URL and publishable key.
- **Supabase's free plan pauses a project after a week without activity.** The daily pipeline and API traffic count as
  activity, but check the project is awake before the first announcement.
- **Ask Codeforces.** Their [terms](https://codeforces.com/terms) forbid commercializing site material and are silent about
  scraping and reposting. The API serves only hints and links back to the problems, and the project asks for donations
  only to cover costs, but a short message to the Codeforces team asking whether that is acceptable is worth sending first.
- **Say what the hints are.** They are written by an AI model from the statement and the editorial and can be wrong. The docs
  page says so, and the response says whether the hints were written with the editorial (`groundedInTutorial`).

## What you will know about usage

Built in today (no extra work):

- **Every request is logged** as one JSON line: route, status, response time, the app that made it, and whether the
  answer came from the cache. **No IP address is logged or stored.**
- **Cloudflare's dashboard** shows requests, errors, response times and cache hit rate for the Worker, free.
- **Per-app statistics:** integrators are asked (in the docs) to send `X-Client: their-app/1.0`, or, in a browser, to add
  `?client=their-app/1.0` to the URL (no preflight request); otherwise the User-Agent's product name is used. It is
  self-declared, so it is good for statistics and not for security.
- **Statistics for years:** the Worker writes one data point per request to Cloudflare's Analytics Engine, and a daily job
  copies the totals into the database. Setup and example queries: `docs/usage-stats.md`.
- **Rate limiting:** 60 requests a minute per client address per Cloudflare location (a soft limit); Cloudflare's own
  rules can add a hard one in the dashboard.

Limits to know about:

- Workers Logs keep only **3 days** ([limits](https://developers.cloudflare.com/workers/platform/pricing/)) and the
  Analytics Engine keeps data for **3 months** ([limits](https://developers.cloudflare.com/analytics/analytics-engine/limits/)).
  That is why `docs/usage-stats.md` copies the daily totals into your own database, where they stay.
  (Written to Cloudflare's documented shape but not tried against a real dataset.)
- There are no user accounts or API keys, so "users" means apps and anonymous clients, not people. If abuse ever
  appears, API keys per integrator are the next step.
- The Supabase dashboard has its own database usage numbers, separate from the above.

## Alternatives

- **Supabase directly (no Worker at all):** `https://PROJECT.supabase.co/rest/v1/public_hints?contest_id=eq.1944&index=eq.C`
  with the publishable key works today and costs nothing, but it has no documentation page, no rate limit of your own, and
  your database layout becomes the public contract. Fine for a first test, not for a public launch.
- **Your own server (`node src/api/server.ts`):** the same API as a normal Node service (`deploy/README.md` has Cloud Run
  instructions). It needs a host that is always on.
