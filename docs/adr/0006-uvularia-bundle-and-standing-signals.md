# ADR-0006: A corpus can be a published bundle, and compliance is a signal

**Status:** accepted · **Date:** 2026-10-03

## Context

uvularia (lentago/.github ADR-0009) makes mitchella's engine the Ask box over a
client-owned records vault. The vault does not hand mitchella a checkout; it
publishes three artifacts on merge and keeps them current:

- `corpus-<digest>.json` — every published record, already in this package's
  `Entry` shape, plus an `archived` flag and the content `digest` the artifact
  is named by.
- `standing.json` — one row per posting obligation, each `green`, `amber`,
  `red`, or `no-data`.
- `feed.xml` — an Atom feed of announcements.

Three facts about these artifacts sit awkwardly against the core as it stood,
and this ADR records how each is resolved. All three new pieces are clients of
the existing core — they add a source and two signal providers and change no
frontend (ADR-0003) and nothing in `contract.py`.

## Decision

### 1. A source may be a single artifact that declares its own fingerprint

`flat` and `wiki` read a *directory* and the corpus fingerprint is a hash of the
rendered bytes. The bundle is one *artifact*, addressed by URL or path, and it
already carries a digest the publisher computed. Hashing the rendered bytes
again would invent a second fingerprint for a thing that already has the
authoritative one, and would let two hosts that fetched the identical URL
disagree on the cache prefix over a whitespace difference in rendering.

So the loader protocol grows one seam: a loader may set `reads = "artifact"` and
return `(entries, fingerprint)`. `corpus.load` honours it — reading a URL or
file instead of a directory, and pinning the declared digest instead of hashing.
Directory sources are unchanged and still add without touching `corpus.py`; this
is the one exception, and it is here rather than implicit. `archived` records are
dropped at load, so an old record leaves the prompt without leaving the vault.

### 2. An obligation in breach is an incident on that obligation's subjects

`StandingProvider` reads `standing.json`. A row in `amber` or `red` becomes an
incident whose subjects are the obligation's subjects, so a question in that
obligation's area is answered by the breach rather than by a corpus entry that
would otherwise assert the estate is in order. The box cannot claim compliance
the board denies. This rides the existing signals-before-corpus gate (ADR-0001)
with no new mechanism: a breach is simply another open incident.

`amber` suppresses as firmly as `red`. "At risk" is still "not safe to reassure
anyone", and a desk that waited for `red` would hand out false comfort right up
to the deadline.

Subjects come from the obligation pack — the rules release (uvularia's
`<org>-ask-rules`) — passed in at construction, because the standing row carries
only an obligation id and the subjects live with the rule. A breach whose
obligation is unknown still surfaces, keyed on its own id, rather than vanishing.

### 3. no-data is unknown, never a fake green

A `no-data` row — one the board could not compute — is reported in
`degraded_signals`, exactly as an unreachable status feed is (ADR-0001's
degrade-gracefully rule, invariant 3). It is never dropped and never treated as
compliant. An unrecognised state is handled the same way: unknown, never green.

### 4. Announcements are an ordinary signal

`AnnouncementProvider` reads `feed.xml` and surfaces each *active* announcement —
`publish_at <= now`, not past an optional `expires` — whose subjects match the
question, through the same incident channel. The operator channel leads with it,
which is the point: a current closure should answer "is the trail open?" ahead of
a corpus page that predates it.

Subjects ride on Atom `<category>` terms when the feed carries them. The demo
feed does not, so they are recovered from the title — its words minus
connectives and anything under four letters — matched as a substring, the same
crude-but-auditable rule the incident gate already uses. A feed that grows
`<category>` terms sharpens the match with no code change.

## Consequences

- mitchella can be pointed at a URL that a publisher keeps current, with no
  checkout and no copy — the `wiki` source's "documentation lives elsewhere"
  taken to its conclusion.
- The compliance board and the Ask box cannot disagree: both read the same
  `standing.json`, and a breach the board shows is a breach the box honours.
- `corpus_fingerprint` on a bundle-backed answer is the vault's digest, so a
  turn can be traced to the exact artifact that produced it.
- Subject precision for standing breaches is now an operational responsibility
  of the obligation pack, as incident subjects already are (ADR-0001). A pack
  with thin subjects yields breaches that match few questions.
- The providers are wired by the runtime that hosts the engine (uvularia's Ask
  function), not by the Slack or CLI frontend, which stay pointed at the
  estate's own corpus and manual overrides.
