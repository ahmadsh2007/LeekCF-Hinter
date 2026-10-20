# Usage statistics that last for years

The API records how it is used, without recording who uses it. This page explains what is kept where, how to switch the
long-term part on (about 15 minutes, once), and how to read the numbers.

## What is recorded

One data point per request: the route (`hints`, `docs`, `health`...), the status (200, 404, 429...), the app's name, how
long the answer took, and whether the edge cache answered. **Never an IP address, a user, or anything from the request
beyond that.**

The app's name is self-declared (statistics, not security), in this order: the `X-Client` header, then the `?client=`
query parameter, then the User-Agent's first word. Apps are asked to send `my-app/1.0`; a browser extension should use
`?client=my-extension/1.0`, because a custom header makes the browser send an extra preflight request.

## Where it lives

| Place | Keeps | How long |
|---|---|---|
| Workers Logs (Cloudflare dashboard) | every request line | about 3 days |
| Analytics Engine (Cloudflare) | one data point per request | **3 months** |
| `api_usage_daily` (your Supabase database) | daily totals per app, route and status | **as long as the project** |

Cloudflare cannot keep more than 3 months, so a daily job (`src/workers/usage/rollupUsage.py`) copies the daily totals
into the database. It re-reads the last 7 days every run and upserts, so a missed day heals itself; after a longer gap it
reads back as far as the last saved day, up to the 90 days Cloudflare still has. Run it at least once every 3 months or
older days are gone. The table is included in the backups (`src/workers/backup`), because unlike the hints it cannot be
regenerated.

## Switch it on (once)

1. **Create the table.** In the Supabase dashboard open *SQL Editor*, paste `migrations/005_api_usage_daily.sql`, run it.
   The public key can neither read nor write this table.
2. **Deploy the Worker:** `npx wrangler deploy`. The binding in `wrangler.toml` creates the dataset on the first write.
   If Cloudflare says Analytics Engine has to be enabled for the account, enable it in the dashboard
   (*Workers & Pages → Analytics Engine*) and deploy again.
3. **Make a read-only API token.** Cloudflare dashboard → *My Profile → API Tokens → Create Token → Create Custom Token*,
   permission **Account → Account Analytics → Read**. Copy the token once; it is shown only then.
4. **Find your account id:** the long hex string in the dashboard address after `dash.cloudflare.com/`, or on the right
   of *Workers & Pages → Overview*.
5. **Add both to `~/leekcf-env/staging.env`** (never to the repository):
   ```
   CLOUDFLARE_ACCOUNT_ID=...
   CLOUDFLARE_API_TOKEN=...
   ```
   For GitHub Actions add them as repository secrets with the same names.
6. **Try it** once some requests have arrived:
   ```bash
   ENV_FILE=~/leekcf-env/staging.env venv/bin/python -m src.workers.usage.rollupUsage
   ```
   It prints how many daily rows it saved. From then on `scripts/daily.sh` does it as its last stage, and skips it
   quietly when the two settings are missing.

**Not verified yet:** the query and the answer format follow Cloudflare's documentation but have not been run against a
real dataset. If the first run stops with "Unexpected row" or an HTTP error, the message says what Cloudflare sent.

## Reading the numbers

In the Supabase *SQL Editor*:

```sql
-- requests per app per week
select date_trunc('week', day)::date as week, client, sum(requests) as requests
from api_usage_daily where route = 'hints'
group by 1, 2 order by 1 desc, 3 desc;

-- hint answers per day, split into found and not found
select day, sum(requests) filter (where status = 200) as found, sum(requests) filter (where status = 404) as not_found
from api_usage_daily where route = 'hints' group by day order by day desc;

-- share answered by the edge cache, and the average response time
select sum(cache_hits)::float / nullif(sum(requests), 0) as cache_share,
       sum(total_duration_ms) / nullif(sum(requests), 0) as avg_ms
from api_usage_daily where route = 'hints';
```

Counts are exact up to Analytics Engine's sampling, which the export corrects for (each point is weighted by its sample
interval). The labels are chosen by the callers, so treat them as honest-but-unverified.
