# mitchella

**Mitchella** (partridgeberry — the botanical codename line alongside `lentago`,
`solidago`, `kalmia`, `drosera`, `claytonia`, and `betula`) is a **corpus-backed
front desk for an infrastructure estate**: a chat assistant that answers
operator questions from documentation in git, checks live state before it
answers, and routes what it cannot answer to a human. Partridgeberry's paired
flowers fuse into a single berry — several sources, one answer.

Slack is the first surface. It is not the product: the core is UI-agnostic and
the CLI ships alongside it, because a boundary with one implementation behind it
is a boundary nobody has tested.

**Authorship:** The code and documentation in this repo are co-written with
[Claude](https://claude.ai) (Anthropic). I direct the work and review the
output; Claude writes the code. I'm an infrastructure operator, not a software
engineer — please don't read this repo as a portfolio of coding ability.

> 🌱 This repo is one exhibit in **[Lentago Labs](https://github.com/lentago)** —
> a team learning lab where IT-operations people build, break, and operate real
> systems at deliberately non-critical stakes. mitchella's job in that estate is
> the **front desk**: it answers from documentation, defers to
> [drosera](https://github.com/lentago/drosera) on what is happening right now,
> and hands everything else to a person.

## The three ideas worth stealing

**1. Live state is checked before the corpus is allowed to answer.**
The failure that kills documentation-backed bots is not a wrong answer — it's a
*right* answer to the wrong question. Mid-outage, someone asks "why can't I log
in?" and a bot with excellent documentation walks them through a password reset,
because that genuinely is the fix when the system is healthy. Forty people get
the same advice and the real incident goes unmentioned.

So an open incident matching the question overrides the corpus, and **the
override is a branch in Python, not a line in the prompt** — guidance is what a
model gets talked out of. See [ADR-0001](docs/adr/0001-signals-before-corpus.md).

**2. There is no vector database, on purpose.**
The whole corpus goes in the prompt behind one cache breakpoint. At this size
that is cheaper, simpler, and deletes a category of bug — "why did it retrieve
the wrong document?" is only possible if you are retrieving. It costs one
discipline: the cached prefix must be byte-stable, so nothing per-request ever
renders into the system prompt, and a test enforces that. See
[ADR-0002](docs/adr/0002-whole-corpus-in-the-prompt.md).

**3. It improves by opening pull requests.**
A nightly job clusters the questions the desk couldn't answer and proposes
corpus entries on a branch. A human merges; the merge is the deploy. Improvement
is a reviewable diff in git history rather than state that drifts somewhere
unreadable — the same shape as [claytonia](https://github.com/lentago/claytonia),
where an agent proposes and a human always merges. See
[ADR-0004](docs/adr/0004-improvement-is-a-pull-request.md).

## What it is not

- **It cannot change anything.** No tools, no write access, no submit button —
  its output for an actionable request is a ticket *draft* a human sends. The
  corpus and the questions are both prompt-injection vectors, and containment is
  the mitigation ([ADR-0005](docs/adr/0005-no-write-access.md)).
- **It does not own the live pane.** drosera does. mitchella reads drosera's
  published `status.json`; it never queries the log archive, which is betula's.
  Neither product grows into the other's role.
- **It does not measure its own quality by cache hit rate.** That is a cost
  metric. A bot answering the same question wrong four hundred times has an
  excellent cache hit rate.

## How it answers

```
question ──▶ signal plane ──┐
                            ├──▶ decide ──▶ answered / incident / escalated / declined
             corpus ────────┘
```

| Outcome | Meaning |
|---|---|
| `answered` | Answered from the corpus, with entry ids cited. |
| `incident` | A live incident explains the question. Corpus answer suppressed. |
| `escalated` | Not documented. A ticket draft is attached for a human to submit. |
| `declined` | Out of scope, or the model declined. No guess, no draft. |

Every outcome carries `degraded_signals` — the signal sources that could not be
read. Borrowed from drosera's status page rule: **degrade gracefully, never fake
green.** An unreachable feed means *unknown*, never *all clear*, and every
frontend is required to show it.

## Run it

```bash
pip install -e '.[dev,slack]'
export ANTHROPIC_API_KEY=...          # or `ant auth login`

python -m frontends.cli.main --corpus-info      # no API call
python -m frontends.cli.main --usage "how do I share a file on the LAN?"
python -m frontends.cli.main                    # interactive
```

Declare an incident by uncommenting the block in
[`signals/incidents.toml`](signals/incidents.toml), then ask a question that
mentions one of its `subjects` and watch the answer change. That one file is the
cheapest useful thing here: a person on the desk knows about an outage before
the monitoring does more often than anyone likes to admit.

Wire in drosera's live feed with `MITCHELLA_DROSERA_STATUS` (a URL, or a local
path to a `status.json` from a drosera build).

### Slack

```bash
export SLACK_BOT_TOKEN=xoxb-...   # Bot User OAuth Token
export SLACK_APP_TOKEN=xapp-...   # App-Level Token, scope connections:write
python -m frontends.slack.app
```

Socket Mode, so no public URL and no inbound firewall change. Scopes:
`app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`. Event
subscriptions: `app_mention`, `message.im`.

### The nightly loop

```bash
python -m jobs.promote --since 1            # dry run; proposes nothing
python -m jobs.promote --since 1 --write    # writes entries onto a branch
```

## Layout

| Path | What |
|---|---|
| `mitchella/contract.py` | The frontend boundary — `Query` in, `Answer` out |
| `mitchella/engine.py` | Prompt assembly, the incident gate, the API call |
| `mitchella/signals.py` | Live state; degrades to *unknown*, never to *healthy* |
| `mitchella/corpus.py` | Markdown → one deterministic, cacheable block |
| `corpus/` | The documentation, in git. Changes on merge and nowhere else |
| `signals/incidents.toml` | The manual override channel |
| `frontends/slack/`, `frontends/cli/` | The clients |
| `jobs/promote.py` | The nightly improvement loop |
| `docs/adr/` | Why it is shaped this way |

## Configuration

All optional; every value has a working default.

| Variable | Default | Notes |
|---|---|---|
| `MITCHELLA_MODEL` | `claude-opus-5` | One model for every stage — caches are model-scoped, so a cheap-classifier cascade forfeits prefix reuse |
| `MITCHELLA_EFFORT` | `high` | Triage is intelligence-sensitive. `medium` is the documented step-down to *measure*, not to assume |
| `MITCHELLA_CACHE_TTL` | `1h` | A desk goes quiet between questions; a 5-minute entry would expire in the gaps |
| `MITCHELLA_DROSERA_STATUS` | *(unset)* | URL or path to drosera's `status.json` |
| `MITCHELLA_INCIDENTS` | `signals/incidents.toml` | The manual override file |
| `MITCHELLA_TURNLOG` | `var/turns.jsonl` | Feeds `jobs/promote.py` |

## Tests

```bash
python -m pytest
```

They run against a fake client and cost nothing. They do not test what Claude
says — they test the guarantees that hold *whatever* it says: the cached prefix
is byte-stable, an open incident overrides an `answered` verdict, citations to
non-existent entries are dropped, a refusal is caught before content is read,
and an unreachable signal source degrades to unknown rather than healthy.
