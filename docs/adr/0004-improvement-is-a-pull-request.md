# ADR-0004: Improvement is measured demand, closed by a human

**Status:** accepted · **Date:** 2026-08-27 (revised the same day; see *History*)

## Context

"It should get better over time" usually gets built as something that adjusts
itself in place: a feedback score, a growing answer cache, a self-edited prompt.
All of those work, and all of them produce a system whose current behaviour
cannot be explained by reading anything.

A related trap is worth naming because the vocabulary invites it. Prompt cache
hit rate is a **cost** metric. It reports how much of the prompt prefix was
reused and says nothing about whether an answer was right; a bot answering the
same question wrong four hundred times has an excellent cache hit rate.
Improvement has to be measured on something else.

## Decision

The desk logs every turn and reports **demand**: which questions it could not
answer, how many distinct people asked, and which kind of work would close each
gap. `jobs/promote.py` produces that report. It writes no documentation.

Closing a gap is a person's job, because the corpus is curated. The routes it
distinguishes are the kinds of work that actually close a gap:

| Route | What closes it |
|---|---|
| `intake` | Capture the source, then write a page from it |
| `research` | A dated memo about something outside the estate |
| `verification` | Go and look |
| `decision` | Someone decides, usually after talking to other people |
| `ticket` | Not a documentation gap; an action |

Improvement therefore still lands as a reviewed change in git, in whichever
repository owns the corpus. Nothing learns in place, there is no drifting state
to audit, and "the bot changed its own behaviour overnight" never needs
explaining to anyone.

## History

The first version of this decision had `promote.py` draft corpus entries
directly and open a pull request with them. That is right for a corpus the desk
owns and wrong for a curated one, and the reason is worth keeping: an agent
writing documentation for an estate it has only read *about* produces confident
text with nothing behind it, which is the failure a curated intake process
exists to prevent. Demand is the part a desk can measure honestly; synthesis is
the part that needs a person and a captured source.

## Consequences

- The flywheel runs at the speed of intake, so **intake lag is the metric to
  watch**, not retrieval precision. There is no retrieval to tune.
- Distinct-asker counts make "is this worth documenting?" a measurement rather
  than a guess.
- The desk cannot close a gap on its own. That is the accepted cost, and it is
  the same trade as having no write access (ADR-0005).
- Three mechanisms keep their own names and are not conflated: the **prompt
  cache** (cost), an **answer cache** (not built), and this **demand loop**
  (improvement).
- An answer cache that serves a stored reply to a near-identical question is
  deliberately not built. On a service desk it is dangerous: a cached "have you
  tried restarting it?" served during an outage is worse than silence. If one is
  ever added it must be gated to entries marked `volatility: stable`.
