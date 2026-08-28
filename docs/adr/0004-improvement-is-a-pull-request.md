# ADR-0004: Improvement is a pull request, not a weight update

**Status:** accepted · **Date:** 2026-08-27

## Context

"It should get better over time" usually gets built as something that adjusts
itself in place — a feedback score, a growing answer cache, a self-edited
prompt. All of those work, and all of them produce a system whose current
behaviour cannot be explained by reading anything.

A related trap is worth naming because the vocabulary invites it. Prompt cache
hit rate is a **cost** metric: it reports how much of the prompt prefix was
reused and says nothing about whether an answer was right. A bot answering the
same question wrong four hundred times has an excellent cache hit rate.
Improvement has to be measured on something else.

## Decision

The only improvement mechanism is `jobs/promote.py`: read the turn log, cluster
the questions the desk could not answer, draft corpus entries for the clusters
that recur, and put them on a branch for a human to review and merge. The merge
is the deploy.

Three things fall out of that shape and each is deliberate. Improvement is a
diff, so it is reviewable. It is in git history, so it is auditable without any
new machinery. And it requires a human, so "the bot changed its own behaviour
overnight" never needs explaining to anyone.

The job will not invent an answer it does not have. Where the underlying answer
is unknown, it proposes a stub that states the question and marks the answer as
undocumented. A stub a person completes is useful; a confident invention is
worse than the gap it fills.

## Consequences

- The flywheel runs at the speed of review. For a desk, that is fast enough.
- Three distinct mechanisms keep their own names and are not conflated: the
  **prompt cache** (cost), an **answer cache** (not built — see below), and this
  **promotion loop** (improvement).
- An answer cache that serves a stored reply to a near-identical question is
  deliberately not built. On a service desk it is actively dangerous: a cached
  "have you tried restarting it?" served during an outage is worse than silence.
  If one is ever added, it must be gated to entries marked `volatility: stable`.
