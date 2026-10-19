# Funding the project, and getting it noticed

Hinter is free to use and its code is open source (Apache-2.0). What it needs money for is, in order:

1. **Model API usage.** Better models write better hints, and the hints are only as good as the model. Measured so far: about
   2,700 tokens per problem; see `docs/cost-estimate.md` for what a top-tier model costs for the whole list and for upkeep.
2. **Hosting and the database**, free today; a paid database plan only if the free one is outgrown.
3. **A domain name**, if wanted.

There is no advertising and no paywall, and nobody is paid but the model providers and the hosts. Publish the spending
(a short monthly note or a public ledger) so supporters can see where money goes.

## Why Apache-2.0

It is OSI-approved and permissive, which is what most funding programs, companies and contributors look for, and it makes
credit a legal requirement: anyone who copies or redistributes the project must keep the copyright notice and the `NOTICE`
file, which names you, and say what they changed. A non-commercial licence would have kept companies from paying you for
nothing, but it is not "open source" in the sense most programs require, so it would have closed doors. No licence can
promise stars or funding; it only decides which doors are open.

## Where money can come from

Terms change, so check each programme's own page before relying on any of this. Nothing here has been applied for.

- **Donation platforms** (no hosting of your own needed): GitHub Sponsors, Open Collective (the Open Source Collective can host
  open-source projects), Ko-fi, Liberapay, Buy Me a Coffee. Pick one or two, not five. Availability and payouts depend on your
  country, so look at each platform's list of supported countries first. Put the link in `.github/FUNDING.yml` (the repository
  then gets a Sponsor button) and in the README.
- **Credits instead of cash.** The biggest cost is model usage, and several AI providers run programmes for open-source
  projects, researchers and students (for example OpenAI's "Codex for Open Source", described by third parties as API credits for
  public GitHub projects; look for Google, Anthropic and others too). Credits pay for exactly what the project needs. When you
  apply, send measured numbers: problems covered, cost per problem, a link to the live API and to the evaluation.
- **Direct asks.** A short, specific message to a provider's developer relations or to a company that benefits from the data
  ("this open API serves hints for N Codeforces problems; X would cover the cost of a better model for a year") often works better
  than a form.
- **Grants** exist for open-source infrastructure and education tools. Search for ones that fit; they usually want a clear plan,
  a licence and some evidence of use.

## Getting the project noticed (stars, contributors, a good CV line)

Stars follow usefulness and visibility, so the work is making it useful and easy to find:

1. **A live, working API** with the docs page (`docs/launch.md`). A link that works beats any description.
2. **Evidence of quality.** Check a sample of hints against the editorials and publish the numbers, good or bad. This is the single
   strongest thing for credibility and for funding applications.
3. **A strong README.** What it does in one sentence, a short example response, how to try it, how to contribute. A screenshot or a
   short recording of a browser extension showing hints would help a lot.
4. **Tell the people who need it.** A post for the Codeforces community (ask the Codeforces team first, see `docs/launch.md`), a
   "Show HN" post, relevant subreddits and Discord servers, dev.to. Be honest that the hints are AI-written and can be wrong.
5. **Make contributing easy.** `CONTRIBUTING.md` is there; add "good first issue" labels to small tasks (a browser extension is the
   obvious big one).
6. **Tag a release** (`v1.0.0`) and set the repository description and topics (`codeforces`, `competitive-programming`,
   `llm`, `api`, `hints`) so it shows up in searches.
7. **For the CV**: link the repository and the live API, and say what is true and checkable: a pipeline that scrapes, finds
   tutorials and generates hints for ~10,000 problems, a public documented API, hundreds of automated tests, and (once measured)
   how accurate the hints are.
