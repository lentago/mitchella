# Roadmap to MVP

**MVP is a desk the team uses daily.** Concretely: it answers questions from the
curated corpus, defers to live state when something is broken, holds a
conversation in a Slack thread, files an issue when a person confirms one, stays
up on its own, and reports enough about itself to debug.

Everything below is filed. This page is the ordering and the reasoning; the
issues hold the detail.

## Where it is today

Working: the engine, the corpus loader with two document shapes, the signal
plane with honest degradation, the incident gate, the turn log, the demand loop,
a CLI, and a Slack frontend. 35 tests, all against a fake client.

Not working, or not proven:

- **No live API call has ever been made.** The request shape is checked against
  the SDK signature; the round trip is not.
- **No conversation.** Every question is answered with no memory of the previous
  one, so a thread follow-up cannot work.
- **No write path.** An escalated answer produces a draft that a person retypes
  somewhere else.
- **Nowhere to run.** It is a foreground process on a laptop.

## M1 — Prove the desk works

Nothing else is worth building until a real question gets a real answer.

| # | Issue | Why here |
|---|---|---|
| [#1](../../issues/1) | Exercise the real API path end to end | Blocks everything. Also the first chance to confirm the cache actually hits |
| [#2](../../issues/2) | Hold a conversation: thread context across turns | A chat bot that cannot follow up is a search box |
| [#3](../../issues/3) | Slack hardening: visible failures, block limits, retries | These fail in a channel in front of people, not in a test |

The trap in #2 is that conversation history must grow *after* the cached corpus
prefix. Get that wrong and the cache stops hitting, which shows up on the bill
rather than in the answers.

## M2 — File on the user's behalf

The capability that turns the desk from something you read into something that
does a thing for you. It is also the milestone that changes the architecture,
so it starts with a decision rather than code.

| # | Issue | Why here |
|---|---|---|
| [#4](../../issues/4) | ADR: supersede ADR-0005 to authorise one scoped write path | Lands before any filing code |
| [#7](../../issues/7) | Decide attribution: service account or per-user OAuth | Changes the cost of #6 substantially |
| [#5](../../issues/5) | Slack: confirm-before-file button and modal | The confirmation step |
| [#6](../../issues/6) | Issue tracker client: turn a confirmed draft into a filing | The write itself |
| [#8](../../issues/8) | Filing controls: idempotency, rate limits, kill switch, audit | Ships with the write path, not after it |

[ADR-0005](docs/adr/0005-no-write-access.md) currently says mitchella has no
write access to anything, and the reasoning is still sound: the corpus and the
questions are both prompt-injection vectors, injection is a containment problem
rather than a prevention one, and "the worst case is a wrong answer in a chat
message" is a short answer on a security review.

Filing issues gives that up, so it gets superseded deliberately rather than
eroded by a feature. The replacement keeps the shape: **one verb, one
destination, and a human who reads the draft and presses the button.** The
worst case becomes a spurious ticket that a named person created and can close,
which is a bounded and reversible failure. #8 is what makes that true rather
than aspirational, which is why it is in this milestone and not a later one.

The seam already exists. The desk produces a `TicketDraft` for the `escalated`
outcome and the Slack renderer already shows it, with a note that it cannot be
filed. MVP replaces the note with a button.

## M3 — Run it unattended

| # | Issue | Why here |
|---|---|---|
| [#9](../../issues/9) | Deploy the desk so it outlives a terminal | Guest lifecycle is Terraform enforced, so this lands as code |
| [#10](../../issues/10) | Ship telemetry to drosera | drosera owns the live pane; the desk should not grow its own |
| [#11](../../issues/11) | An eval set, so changes are measurable | Makes every later change judgeable |
| [#12](../../issues/12) | Bound the cost: caps and reporting | Cheap to add, awkward to retrofit after a surprise |

#11 is the one most likely to be skipped and the one that matters most over
time. Every current test asserts a guarantee that holds whatever the model says;
none assert that the answers are good. Without a fixed question set, a corpus
edit or a prompt change is judged by impression, and a regression is discovered
by a person on the desk getting a worse answer.

## Deliberately not in MVP

- **An answer cache.** Serving a stored reply to a near-identical question is
  dangerous on a service desk: a cached "have you tried restarting it?" during
  an outage is worse than silence. If it is ever built, it is gated to entries
  marked `volatility: stable`.
- **Retrieval.** The corpus fits in the context window behind a cache
  breakpoint. Adding a retriever now buys nothing and introduces a class of bug
  that does not currently exist ([ADR-0002](docs/adr/0002-whole-corpus-in-the-prompt.md)).
- **More corpus sources.** `flat` and `wiki` cover markdown trees. A source that
  reads an API needs a sync step, and that is a milestone of its own.
- **Decomposing `escalated`.** The desk currently routes to four outcomes. The
  finer taxonomy the demand loop already uses could move into the desk itself,
  but not before the desk is in daily use and the routes are observed rather
  than guessed.
