# CLAUDE.md — mitchella

> Read [README.md](README.md) for the project pitch. This file is operational
> notes for Claude: the conventions to respect and the invariants not to break.
> Fleet-wide rules (PR workflow, attribution, live-state discipline) live in
> `~/repos/CLAUDE.md` and should NOT be restated here — call out only this
> repo's deviations.

## Persona — introduce yourself

When Claude initializes in this directory, open the first response with a brief
self-introduction as **Mitchella Claude** — keeper of the estate front desk
(the corpus, the signal plane, and the promotion loop). One sentence is plenty;
don't make a meal of it.

## What this repo is

A corpus-backed chat assistant for the lab estate. It answers operator
questions from markdown in `corpus/`, checks live state before answering, and
drafts a ticket for a human when it can't. Slack is the first frontend; the
core is UI-agnostic.

## Invariants — breaking one of these is a bug, not a style choice

1. **Nothing per-request may render into the system prompt.** No clock, no
   username, no incident list, no conditional sections. The cached prefix must
   be byte-identical across turns or the cache silently stops hitting and only
   the bill notices. `test_nothing_volatile_renders_into_the_cached_prefix`
   guards this — if you find yourself editing that test to pass, stop.
2. **The incident gate stays in code.** `Engine._to_answer` upgrades `answered`
   to `incident` when a relevant incident is open. Do not move this into the
   prompt; prompt text is guidance, and guidance is what a model gets talked
   out of.
3. **Degraded signals are never dropped.** A signal source that can't be read
   is *unknown*, never *healthy*, and every frontend must surface it. Silently
   swallowing a degradation turns an honest system into a confident one.
4. **mitchella has no write access.** No tools, no submit button, no
   side effects. Its output for an actionable request is a draft. Adding a
   write path is a new ADR, not a feature.
5. **The corpus changes on merge and nowhere else.** No runtime writes to
   `corpus/`; `jobs/promote.py` proposes onto a branch for review.

## Conventions

- **Python ≥ 3.11, standard library first.** The only runtime dependency in the
  core is `anthropic`; `slack-bolt` belongs to the Slack frontend alone. Match
  the register of `betula/clients/aws/` — small modules, plain dataclasses,
  pytest.
- **Frontends import `mitchella` and nothing deeper.** Adding a frontend must
  not require editing a file outside `frontends/<name>/`. That is the
  agnosticism principle's acceptance test, and it is checkable by grep.
- **Corpus entries** need frontmatter with `id`, `title`, `tags`, `volatility`
  (`stable` | `live`). Mark an entry `live` when its answer depends on current
  system state. Malformed frontmatter fails loudly — never skip a document.
- **Comments explain why, not what.** The reader is an operator six months from
  now who needs to know which lines are load-bearing.
- **ADRs** live in `docs/adr/`. A decision that would surprise a reviewer gets
  one; changing an existing decision means superseding its ADR, not editing it
  quietly.

## Working on the model call

Before editing `engine.py` or `jobs/promote.py`, load the `claude-api` skill —
the API surface moves, and several patterns that look right from memory
(`budget_tokens`, assistant prefill, `output_format`) are now rejected outright.
Current shape here: `claude-opus-5`, `thinking={"type": "adaptive"}`,
`output_config={"effort": ..., "format": ...}`, one cache breakpoint on the last
system block, live state as a `{"role": "system"}` message after the history.

## Tests

`python -m pytest`. They run against a fake client and make no API calls, so
they're free and fast. They deliberately do not assert what Claude says — they
assert the guarantees that hold whatever it says. New behaviour in the engine
wants a test of that kind.
