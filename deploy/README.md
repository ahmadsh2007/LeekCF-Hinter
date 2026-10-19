# Deploying to Google Cloud Run

> **Status: written, not run.** These files and commands were prepared without Docker or `gcloud` available, so
> none of the images has been built and nothing has been deployed. What *was* checked: every pipeline stage starts
> without secrets (`--help`), the sync script runs from exactly the files `Dockerfile.sync` copies, and the API
> server boots, refuses a secret key and answers `/v1/health`. Expect to fix a typo or a flag on the first real
> attempt, and read the output of each command before running the next.

Three images, built from the repository root:

| Image | Dockerfile | What it runs | Needs |
|---|---|---|---|
| `hints-api` | `deploy/Dockerfile.api` | the public API (a Cloud Run **service**) | `SUPABASE_DATABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` |
| `hints-sync` | `deploy/Dockerfile.sync` | contest and problem sync from the Codeforces API (a **job**) | `SUPABASE_DATABASE_URL`, `SUPABASE_DATABASE_SECRET_KEY` |
| `hints-worker` | `deploy/Dockerfile.worker` | `run-pipeline.sh`: scrape, dedup, protect, tutorials, hints (a **job**) | the two Supabase variables, `ANTHROPIC_API_KEY` |

Secrets are never part of an image (`.dockerignore` excludes every `.env`); they are injected from Secret Manager.

## 0. One-time setup

```bash
export PROJECT_ID=your-gcp-project
export REGION=europe-west1          # pick the region closest to your Supabase project
gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com
gcloud artifacts repositories create hints --repository-format=docker --location=$REGION
```

Create the secrets (each command reads the value from your terminal; nothing is stored in shell history):

```bash
for name in supabase-url supabase-secret-key supabase-publishable-key anthropic-api-key; do
  printf "Value for $name: " && read -rs value && echo
  printf %s "$value" | gcloud secrets create $name --data-file=-
done
```

The Cloud Run service account needs `roles/secretmanager.secretAccessor` on those secrets
(`gcloud secrets add-iam-policy-binding NAME --member=serviceAccount:... --role=roles/secretmanager.secretAccessor`).

## 1. Build the images

```bash
REPO=$REGION-docker.pkg.dev/$PROJECT_ID/hints
for image in api sync worker; do
  gcloud builds submit . --config deploy/cloudbuild.yaml --substitutions _IMAGE=$image,_REPO=$REPO
done
```

To build locally instead: `docker build -f deploy/Dockerfile.api -t hints-api .` and so on.

## 2. The public API (a service)

```bash
gcloud run deploy hints-api \
  --image $REPO/hints-api --region $REGION \
  --allow-unauthenticated \
  --max-instances 3 --memory 256Mi --cpu 1 \
  --set-secrets SUPABASE_DATABASE_URL=supabase-url:latest,SUPABASE_PUBLISHABLE_KEY=supabase-publishable-key:latest \
  --set-env-vars RATE_LIMIT_PER_MINUTE=60
```

- `--allow-unauthenticated` is what makes it public. The service only reads the gated database view.
- `--max-instances` bounds cost and the total request rate (the rate limiter counts per instance).
- The per-client limit is `RATE_LIMIT_PER_MINUTE` per instance. For a real abuse defence put Cloud Armor or an API
  gateway in front later.

Check it (use the URL `gcloud` prints):

```bash
curl -s $URL/v1/health
curl -s -i $URL/v1/problems/1944/C/hints       # 404 until hints exist and the contest is over
```

## 3. The pipeline (two jobs, run daily)

```bash
gcloud run jobs create hints-sync \
  --image $REPO/hints-sync --region $REGION \
  --set-secrets SUPABASE_DATABASE_URL=supabase-url:latest,SUPABASE_DATABASE_SECRET_KEY=supabase-secret-key:latest \
  --task-timeout 30m --max-retries 0

gcloud run jobs create hints-pipeline \
  --image $REPO/hints-worker --region $REGION \
  --set-secrets SUPABASE_DATABASE_URL=supabase-url:latest,SUPABASE_DATABASE_SECRET_KEY=supabase-secret-key:latest,ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --set-env-vars HINT_LIMIT=20,INCLUDE_WITHOUT_TUTORIAL=false \
  --task-timeout 60m --max-retries 0
```

The model defaults to Claude Opus 5.5 at high effort (`ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` change that). Each job run
is capped by `HINT_LIMIT` problems, so it also caps spending per run. Run both once by hand and read the logs before scheduling:

```bash
gcloud run jobs execute hints-sync --region $REGION --wait
gcloud run jobs execute hints-pipeline --region $REGION --wait
```

Schedule them (sync first, pipeline half an hour later), using a service account that may run jobs
(`roles/run.invoker`):

```bash
SA=scheduler@$PROJECT_ID.iam.gserviceaccount.com
for job in "hints-sync:0 3 * * *" "hints-pipeline:30 3 * * *"; do
  name=${job%%:*}; cron=${job#*:}
  gcloud scheduler jobs create http $name-daily --location $REGION --schedule "$cron" --time-zone UTC \
    --uri "https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$name:run" \
    --http-method POST --oauth-service-account-email $SA
done
```

## After the first real run, check

- `hints-sync` log: "Successfully synced N contests / N problems".
- `hints-pipeline` log: each of the five `== n/5 ==` sections ran; the scraper did not stop with "blocking";
  the tutorial finder lists "Found the tutorial of ..."; the generator says "Generated: N".
- In Supabase: `select stage_status, count(*) from problems group by 1 order by 1;`
- `curl $URL/v1/problems/{contestId}/{index}/hints` for a problem that reached `HINTS_GENERATED` whose contest
  ended more than 2 hours ago returns 200 with five hints.

## Knobs

`run-pipeline.sh` reads `SCRAPE_LIMIT` (default 1000), `TUTORIAL_CONTEST_LIMIT` (50), `HINT_LIMIT` (20) and
`INCLUDE_WITHOUT_TUTORIAL` (`false`). Turn the last one on only after the pilot hints look good, and see
`docs/superpowers/specs/2026-10-18-phases1-5-design.md` for what it does. The first backfill of the historic
problems is better run from your own machine with higher limits than from a scheduled job.
