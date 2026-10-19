# Gemini 4 Argon on Vertex AI (paid by the Google Cloud free-trial credit)

The pipeline can write hints with **Gemini 4 Argon** on Vertex AI, paid by the Google Cloud trial credit ($300, 90 days;
[terms](https://docs.cloud.google.com/free/docs/free-cloud-features)). When the credit or the 90 days run out, Google stops
the project's services and does not bill you unless you upgrade by hand. A model chain (`LLM_PROVIDER=vertex,gemini`)
then continues with the free Gemini Flash.

Things to know first:

- The introductory price of Argon ($2 / $10 per million input / output tokens, thinking counted as output) ends on
  **Nov 30, 2026**, then it doubles. Spending the credit before then buys twice as many hints. Vertex's own price may
  differ from the one printed after each run, which is an estimate.
- Each hint records which model wrote it (`hints.llm_model_used`), so a chain never hides which problems got which model.

## One-time setup (about 10 minutes)

1. **Project.** In the Google Cloud console, open the project that holds the free-trial credit and note its **project id**
   (not its name or number).
2. **Enable the API.** *APIs & Services → Library →* **Vertex AI API → Enable**.
3. **Service account.** *IAM & Admin → Service Accounts → Create service account* (name it `hinter`), give it the role
   **Vertex AI User**, then open it → *Keys → Add key → Create new key → JSON*. A `.json` file downloads.
   (If key creation is blocked by an organisation policy, install the `gcloud` tool instead, run
   `gcloud auth application-default login`, and leave `GOOGLE_APPLICATION_CREDENTIALS` unset.)
4. **Keep the key private.** It is a password. Move it out of Downloads and lock it:
   `mv ~/Downloads/YOUR-KEY.json ~/leekcf-env/gcp-key.json && chmod 600 ~/leekcf-env/gcp-key.json`. Never put it in the repository.
5. **Tell the pipeline.** Add to `~/leekcf-env/staging.env`:

   ```
   LLM_PROVIDER=vertex,gemini
   VERTEX_PROJECT=your-project-id
   GOOGLE_APPLICATION_CREDENTIALS=/Users/YOU/leekcf-env/gcp-key.json
   GEMINI_API_KEY=...            # free key from Google AI Studio (the fallback)
   GEMINI_MODEL=gemini-3.8-flash
   ```

   Optional: `VERTEX_MODEL` (default `gemini-4-argon`), `VERTEX_LOCATION` (default `global`),
   `VERTEX_THINKING_LEVEL` (`low`, `medium` or `high`; unset lets the model decide, and it thinks by default).

## Check it with one cheap call

```bash
ENV_FILE=~/leekcf-env/staging.env venv/bin/python -u -m src.workers.hint_generator.generateHints --dry-run --limit 1
```

It prints the hints and a `Usage:` line with the tokens and an estimated cost. Then open *Billing → Reports* in the console
and check that the charge is covered by the trial credit. This is the proof that the credit really pays for Argon on Vertex.
Common errors, all printed with Google's own message: `403 ... API has not been used` (step 2), `403 permission` (the role in
step 3), `404 model not found` (try another `VERTEX_LOCATION`, or the model name Vertex shows in its Model Garden).
