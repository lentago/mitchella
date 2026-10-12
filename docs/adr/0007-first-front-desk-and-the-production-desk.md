# ADR-0007: The uvularia Ask function is the first front desk; mitchella is the production desk with many front ends

**Status:** accepted · **Date:** 2026-10-12

## Context

`mitchella/` is a UI-agnostic engine, and every surface is a client of it
(ADR-0003): a frontend converts its native event into a `Query`, calls
`Engine.answer`, and renders an `Answer`. Two frontends ship in this repo,
Slack and the CLI, and ADR-0003 anticipated a web surface, an n8n node, and an
email responder as further directories under `frontends/`.

lentago/.github [ADR-0009](https://github.com/lentago/.github/blob/main/docs/adr/0009-uvularia-client-owned-records-vault.md)
(2026-10-03) made this engine the Ask box over a uvularia records vault, and
ADR-0006 added the bundle source and the two signal providers that box needs.
ADR-0009 also records the packaging: "mitchella gains two signal providers and
a serverless packaging; its first live API call happens here." That packaging
is uvularia's
[`templates/ask-function`](https://github.com/lentago/uvularia/blob/main/templates/ask-function/README.md):
an AWS Lambda behind a public Function URL in the client's own account, the
API key in an SSM SecureString read once at cold start, a durable daily cap as
one DynamoDB counter per UTC day, a kill switch in the rules repo's
`policy.yaml`, citations rendered only from ids the engine verified, an
optional Cloudflare Turnstile check in front, and CORS locked to the client's
site. The site's Ask widget POSTs a question to the URL and renders the reply
and the citations. It is uvularia's Phase 1, the third rung of its adoption
ladder, and it is deployed for uvularia's demonstration client.

Two documents in this repo said otherwise. `ROADMAP.md` ("Where it is today")
stated that no live API call had ever been made and listed the CLI and Slack
as the frontends; issue #1 is written the same way. Both predate ADR-0009 and
were not revised when ADR-0006 landed. Nothing recorded how the Ask function
and mitchella relate — whether the function is the product, a fork of it, or a
front end — and the ROADMAP's claim was contradicted by the fleet ADR and by
uvularia's template.

On 2026-10-12, during the offerings-map review, the maintainer decided the
positioning: "call the uvularia ask function the naive first swing at 'front
desk', with mitchella the eventual proper production version, supporting
various front ends (Slack, website, RT, etc.)".

## Decision

**The uvularia Ask function is the first front desk, and it is deliberately
narrow.** One website widget, one corpus (the vault's published bundle), hard
caps (a durable daily cap and a kill switch), no write path, running in the
client's own account. It is a client of this engine in the ADR-0003 sense: the
runtime wires the bundle source and the standing and announcement providers
(ADR-0006) and renders the `Answer` as JSON for the widget. Its narrowness is
the design. It answers one question — what do the records say? — for one site,
and it is the smallest desk that could be hardened end to end and handed to a
client who owns every piece of it.

**mitchella is the production front desk.** It is the engine plus the set of
front ends that staff it, and it stays front-end agnostic by ADR-0003. The
named front ends are:

| Front end | Status |
|---|---|
| Slack | shipped, `frontends/slack/` |
| The CLI | shipped, `frontends/cli/`; also the development harness |
| A website widget | shipped as uvularia's Ask widget over the Ask function; a general one is a new `frontends/` directory |
| Email | planned |
| A ticket system, such as RT (Request Tracker) | planned |

Each is a client of the same engine, and ADR-0003's acceptance test still
holds: adding one must not touch another.

**The two receipts are kept apart.** The engine's "first live answer" receipt
is uvularia's Phase 1 receipt — a live answer that cites a record, and a live
refusal during a manufactured breach — recorded in uvularia when it is run. It
is not mitchella's M1. M1 remains "mitchella's own desk answers live through
one of its own front ends": the CLI or Slack, against this repo's corpus, with
the cache shown to hit (issue #1). The two receipts prove different things,
and neither substitutes for the other.

## Alternatives

- **Treat the Ask function as the product and mitchella as its library.**
  Rejected. It inverts ADR-0003 — the engine is the product and surfaces are
  its clients — and it would make a records-vault widget the ceiling of what
  the desk can be: no thread conversation, no filing on a person's behalf, no
  estate signals from drosera or the manual incidents file.
- **Fold mitchella into uvularia.** Rejected. uvularia is one client of the
  engine, for one kind of corpus (public records), and its own invariants name
  Ask runtimes as clients of its core. The estate desk reads drosera's
  `status.json` and `signals/incidents.toml`, which a records vault never
  will. The companion boundary stays: uvularia owns the vault, the board, and
  the site; mitchella owns the engine and its front ends.
- **Leave the ROADMAP as it was.** Rejected. A roadmap that denies a live
  packaging exists misdirects the next contributor, and the contradiction was
  already visible from the fleet ADR.

## Consequences

- `ROADMAP.md` ("Where it is today") is corrected in the same change: the
  "no live API call" bullet is replaced with the state above, and the website
  widget is named among the front ends. The M1, M2, and M3 milestones are
  unchanged.
- The website widget is a named front end on the roadmap. Today it is
  uvularia's; a general one lands as `frontends/web/` with no core change, as
  ADR-0003 already allows.
- The ticket-filing write path (M2, #4–#8) is expected to land as a consumer
  of the fleet's notification-sink contract
  ([lentago/drosera#272](https://github.com/lentago/drosera/issues/272)): one
  event shape; sinks for a GitHub Issue, email, a webhook, and ntfy push; and
  routing in a `notify.yaml` in the client's repo. mitchella is a consumer of
  that contract, not the pager. A ticket system as a *front end* (questions
  arrive from a ticket) and as a *sink* (a confirmed draft is filed into one)
  are different pieces; the sink contract covers the second.
- Until ADR-0005 is superseded by #4, neither desk has a write path. The Slack
  renderer's "Draft only — mitchella cannot file tickets." line stays true, and
  the Ask function keeps the same property.
- ADR-0003 and ADR-0005 are unchanged. This ADR names the front ends ADR-0003
  anticipated and records where the engine first ran live.
