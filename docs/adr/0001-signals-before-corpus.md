# ADR-0001: The signal plane is consulted before the corpus, and the gate lives in code

**Status:** accepted · **Date:** 2026-08-27

## Context

The failure that kills corpus-backed service desk bots is not a wrong answer.
It is a *right* answer to the wrong question. During an outage, someone asks
"why can't I log in?", and a bot backed by good documentation confidently walks
them through a password reset — because that genuinely is how you fix a login
problem, when the system is healthy. Forty people get the same advice, the real
incident goes unmentioned, and the desk fills with duplicate tickets.

The corpus cannot detect this on its own. Frozen text has no way to know that
today is different.

## Decision

Every turn consults the signal plane **before** the answer is settled, and an
open incident whose subjects match the question overrides a corpus answer.

The override is enforced in `Engine._to_answer`, not in the prompt. The
instructions do ask the model to lead with an open incident, and that guidance
is worth having — but guidance is what a model can be talked out of, by a
confusing question or by text inside a document. The gate is a branch in
Python: if a relevant incident is open and the model returned `answered`, the
verdict becomes `incident` regardless.

Subject matching is a plain substring test. Crude on purpose: a person can
predict its behaviour, which matters more here than recall. A missed match
degrades to an ordinary corpus answer; a false match tells someone their
working system is broken, which is the worse error.

## Consequences

- The desk is useful during an incident, which is when a desk matters most.
- Signal sources must be curated, not comprehensive. A log search is a firehose
  to hallucinate over; a small authoritative status feed is an answer.
- The `subjects` field becomes an operational responsibility. Incidents with no
  subjects match nothing.
