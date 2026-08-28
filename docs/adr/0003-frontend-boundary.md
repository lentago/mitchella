# ADR-0003: Frontends are clients of a UI-agnostic core

**Status:** accepted · **Date:** 2026-08-27

## Context

Slack is the obvious first surface and the wrong thing to build against
directly. The fleet's agnosticism principle applies: the current implementation
is always "the first client", never the product, and it comes with a mechanical
acceptance test — **adding a client must not touch existing clients.**

## Decision

`mitchella/` is UI-agnostic and knows nothing about Slack. A frontend converts
its native event into a `Query`, calls `Engine.answer`, and renders an `Answer`.
It imports `mitchella` and nothing deeper.

Ship two frontends from the start. A boundary with one implementation behind it
is a boundary nobody has tested, and the CLI costs almost nothing while doubling
as the local development harness — no workspace, no tokens, no tunnel.

## Consequences

- A web surface, an n8n node, or an email responder is a new directory under
  `frontends/`, with no core change.
- `Answer` must carry everything any surface might need to render, including
  `degraded_signals`, rather than pre-formatted text.
- Rendering discipline moves to the frontends. Each one is responsible for
  surfacing `degraded_signals`; a frontend that drops it is a bug, because it
  turns "unknown" into an implied "fine".
