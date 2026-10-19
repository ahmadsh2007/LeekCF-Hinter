# What hint generation costs

Written 2026-10-19 for **Claude Opus 5.5 at high effort**. Prices are the standard list prices on
https://platform.claude.com/docs/en/about-claude/pricing, read that day. Check them before you load credit.

| | Input | Output (includes thinking) |
|---|---|---|
| Opus 5.5, standard | $4 / MTok | $20 / MTok |
| Opus 5.5, Batch API (50% off, results within 24 h) | $2 / MTok | $10 / MTok |
| for comparison: Sonnet 5.5, standard | $2 / MTok | $10 / MTok |

Opus 5.5 defaults to *medium* effort; asking for *high* makes it think more, and thinking tokens are billed as output.

## What was measured, and what was assumed

**Measured** (staging project, live Codeforces pages):
- 10,742 problems synced, 63 of them same-name twins in the same round (Div. 1 / Div. 2), so about **10,679 unique problems**
  (10,606 rated). About 800 new problems per year (about 68 a month).
- Prompt size from a random sample of 39 problems built with the real prompt code: system prompt 2,278 characters; problem
  part averages 2,679 characters (median 2,560, 90th percentile 3,863).
- Editorial length from 19 real sections: averages 1,864 characters.

**Assumed** (no tokenizer or model call was available):
- 3.2 characters per token (range 2.8-4.0) plus 150 tokens for the schema, so about **2,300 input tokens** per call.
- **Output tokens per call** (the big unknown, mostly thinking): low 2,500, base 5,000, high 9,000.
- Retries: the validator rejects an answer now and then and the model is asked again: 1.0 / 1.1 / 1.3 calls per problem.

## Result for all 10,679 problems

| Scenario | Tokens in / out per call | Per problem | Per 1,000 problems | Standard | Batch API |
|---|---|---|---|---|---|
| Low | 1,855 / 2,500 | $0.057 | $57 | **$613** | $307 |
| **Base** | 2,282 / 5,000 | $0.12 | $120 | **$1,282** | **$641** |
| High | 2,586 / 9,000 | $0.25 | $247 | **$2,642** | $1,321 |

- Generating for problems **without** a tutorial too (`--include-without-tutorial`) means the model solves the problem
  itself and thinks longer. For an assumed 15% of problems add roughly $80 / $170 / $370.
- Keeping up with new rounds afterwards: about **$4 / $8 / $17 per month**.
- A 30-problem pilot: about $1.70 / $3.60 / $7.40.
- Every call is capped at 16,000 output tokens (thinking included), so one call can never cost more than about $0.33.

## Credit to load

1. **$10** for the pilot (`generateHints --dry-run --limit 30`).
2. Then the pilot's own `Usage:` line gives the real cost per problem; multiply by 10,679. Until then plan on
   **about $1,300 at standard prices (range $600-2,600), about $650 with the Batch API.**

## Two practical limits

- **Time.** The runner makes one call at a time. If a call with high-effort thinking takes about a minute (an assumption;
  the pilot will show the real figure), 10,679 problems take about a week. The Batch API removes both that wait and half
  the price, at the cost of results arriving within 24 hours; a batch mode for the one-off backfill is the next thing worth
  building. Daily upkeep (about 3 problems a day) needs none of this.
- **Quality, not just price.** A cheaper model or a lower effort level cuts the bill a lot (Sonnet 5.5 is half the price per
  token) but can only be judged by reading its hints. Run the same 30 problems at each setting
  (`ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT`) and compare before choosing.
