# Announcement and funding appeal: DRAFT

This is a draft for you to edit and publish yourself. Everything in **[brackets]** is a blank to fill in with a real
number or a decision. Do not publish a claim you have not measured. Before posting, send Codeforces a short message
asking whether a free, donation-supported service that serves hints (never statements or editorials) and links back to
the problems is acceptable (their [terms](https://codeforces.com/terms) forbid commercializing site material and do not
mention scraping).

---

## LeekCF Hinter: free, graduated hints for Codeforces problems

**Stuck on a Codeforces problem, but don't want the full editorial?** Hinter gives you 2 to 5 hints, gentlest first,
written for each problem. The first hint is only an observation; the last is the full solution. Reveal them one at a
time. It is free, needs no account, and has a public API so other tools and browser extensions can use it too.

### How it works

1. It follows the official Codeforces API and picks up new problems and contests automatically.
2. It only ever serves hints for a contest that has finished (plus a 2-hour margin for system tests), so a live round is
   never spoiled. This is enforced in the database, not just in code.
3. It finds the official editorial and writes the hints with it at hand, so they follow the real solution. Where no
   editorial exists the hints are marked as such (`groundedInTutorial: false`).
4. An AI model writes the hints. A checker rejects hints that name the algorithm too early and asks the model to try again.

### Using the API

```
GET https://[YOUR-API-ADDRESS]/v1/problems/1944/C/hints
```

No key, JSON in, JSON out, documented at `https://[YOUR-API-ADDRESS]/` and as OpenAPI at `/v1/openapi.json`. Please send
an `X-Client: your-app/1.0` header so usage can be counted per app (no IP addresses are stored). Please cache answers and
keep to the rate limit.

### How good are the hints?

AI hints can be wrong. **[Fill in after you have checked a sample: "We checked N hints against the official editorials:
X were correct, Y were partly right, Z were wrong. The model was ___."]** The hints are only as good as the model that
writes them, and so far it has been a free-tier model. [If you ran a comparison: "On the same N problems model B got ... right".]

### Why we are asking for support

Hinter is a hobby project run by one person with no budget. It runs on free services, which is why it exists at all, but
free models are the weakest link: they are the ones most likely to write a wrong or unhelpful hint. The most capable
("frontier") models cost real money per problem.

**Donations will pay for exactly three things, in this order:**

1. **Model API usage**: better models for the hints. Rough numbers [update from `docs/cost-estimate.md` and your own
   measured cost per problem]: about **$[0.12] per problem** with a top-tier model, so about **$[1,300]** to redo all
   [10,679] problems, and about **$[8] a month** to keep up with new contests.
2. **Hosting and the database**: free today; money would go to a paid database plan if the free one is outgrown.
3. **A domain name** [about $10 a year], if wanted.

There is no advertising, no paywall, and no plan to sell anything. Spending will be published here: **[where, e.g. a
public ledger on Open Collective, or a monthly note]**. If more is given than is needed, it stays in the "model costs"
fund for the next round of hints and is not spent on anything else.

**[Add your link and platform here: GitHub Sponsors / Open Collective / Ko-fi / ...]**

### What is not done yet

- Hints are being generated for the whole problem list; **[N of 10,679]** are ready today.
- Problems without an official editorial get hints written without one, which are less reliable.
- There is no browser extension yet. The API is open so anyone can build one.

### Open source

The code is open source under the [Apache License 2.0](LICENSE): use it, copy it, change it, build on it, including
commercially. The one condition is credit: keep the copyright notice and the `NOTICE` file, which names the author.

### Credits

Problems and editorials belong to their authors and to Codeforces; Hinter links back to every problem and serves only
the hints. Code: https://github.com/ahmadsh2007/LeekCF-Hinter (Apache-2.0). Created by Ahmad Z. Shatnawi (Leeking).
