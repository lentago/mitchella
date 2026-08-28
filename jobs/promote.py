"""The demand loop: turn unanswered questions into intake work orders.

An earlier version of this drafted corpus entries directly. That was wrong for
a curated corpus, and worth recording why: an agent writing documentation for
an estate it has only read *about* produces confident text with nothing behind
it, which is the exact failure a curated intake process exists to prevent. The
corpus gets better when a person captures a source and synthesises from it, not
when a model fills a gap from inference.

So this job does not write documentation. It reads the turn log and reports
**demand**: which questions people actually asked that the desk could not
answer, how many distinct people asked, and which kind of work would close each
gap. The output is the input to a human's next intake session.

    turn log ──▶ cluster ──▶ rank by distinct askers ──▶ work orders
                                                             │
                                          a person runs the session,
                                          captures the source, writes the page

Run it:

    python -m jobs.promote --since 7
    python -m jobs.promote --since 7 --out demand.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mitchella import Config, load_corpus

#: Turn outcomes that represent unmet demand.
MISS_KINDS = {"escalated", "declined"}

#: How a gap gets closed. The desk cannot close any of these itself; each is a
#: different kind of human work, and naming which one is most of the value.
ROUTES = {
    "intake": "Documented somewhere in the estate but not yet harvested. "
              "Capture the source, then synthesise a page from it.",
    "research": "The answer lives outside the estate and decays. "
                "A dated research memo, re-verifiable later.",
    "verification": "Nobody has checked. Going and looking settles it.",
    "decision": "No one has decided yet. Needs a person, and probably a "
                "conversation with other people.",
    "ticket": "Not a documentation gap. Someone needs to do something.",
}

PROMPT = """\
You are triaging a service desk's unanswered questions to decide what work \
would close each gap.

Group the questions below into clusters that share an underlying need. For each \
cluster, choose the single route that would close it:

- intake: the answer almost certainly exists in the organisation's own systems \
or documentation and simply has not been captured into the corpus yet.
- research: the answer is outside the estate (vendor capabilities, tooling \
landscape, version support) and goes stale, so it needs a dated memo.
- verification: nobody has checked a fact about the estate. Going and looking \
would settle it.
- decision: nothing is being looked up, because no one has decided yet.
- ticket: not a documentation gap at all. Someone needs to take an action.

You are given the corpus's entry titles for context. Judge only what is in \
front of you: if a cluster's route is genuinely unclear, say so in the \
`uncertainty` field rather than picking confidently. Do not attempt to answer \
any of the questions, and do not draft documentation."""

SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "need": {"type": "string"},
                        "route": {"type": "string",
                                  "enum": ["intake", "research", "verification",
                                           "decision", "ticket"]},
                        "questions": {"type": "array", "items": {"type": "string"}},
                        "session_question": {"type": "string"},
                        "uncertainty": {"type": "string"},
                    },
                    "required": ["need", "route", "questions",
                                 "session_question", "uncertainty"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["clusters"],
        "additionalProperties": False,
    },
}


def read_misses(path: Path, since_days: int) -> dict[str, set[str]]:
    """Unanswered questions in the window, mapped to their distinct askers."""
    if not path.exists():
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    demand: dict[str, set[str]] = defaultdict(set)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            when = datetime.fromisoformat(row["ts"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if when >= cutoff and row.get("kind") in MISS_KINDS:
            demand[row["question"]].add(row.get("user_ref", "?"))
    return dict(demand)


def render(clusters: list[dict], demand: dict[str, set[str]], days: int) -> str:
    """A work order a person can act on, ordered by how many people asked."""
    def askers(cluster: dict) -> int:
        people: set[str] = set()
        for q in cluster["questions"]:
            people |= demand.get(q, set())
        return len(people)

    out = [
        f"# Desk demand, last {days} day(s)",
        "",
        f"{len(demand)} unanswered question(s) in {len(clusters)} cluster(s). "
        "Ordered by distinct people who asked.",
        "",
        "Nothing here is documentation. Each row is a gap and the kind of work "
        "that would close it.",
        "",
    ]
    for cluster in sorted(clusters, key=askers, reverse=True):
        n = askers(cluster)
        out.append(f"## {cluster['need']}")
        out.append("")
        out.append(f"- **Route**: `{cluster['route']}` — {ROUTES[cluster['route']]}")
        out.append(f"- **Distinct askers**: {n}")
        out.append(f"- **Session question**: {cluster['session_question']}")
        if cluster.get("uncertainty"):
            out.append(f"- **Unclear**: {cluster['uncertainty']}")
        out.append("")
        out.append("Asked as:")
        out += [f"  - {q}" for q in cluster["questions"]]
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mitchella-promote")
    parser.add_argument("--since", type=int, default=7, help="window in days (default 7)")
    parser.add_argument("--out", help="write the report here instead of stdout")
    args = parser.parse_args(argv)

    config = Config.from_env()
    demand = read_misses(Path(config.turnlog_path), args.since)
    if not demand:
        print(f"No unanswered questions in the last {args.since} day(s).")
        return 0

    corpus = load_corpus(config.corpus_dir, config.corpus_source)
    listing = "\n".join(
        f"- ({len(people)} distinct asker(s)) {q}"
        for q, people in sorted(demand.items(), key=lambda kv: -len(kv[1]))
    )

    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=[{"type": "text", "text": PROMPT}],
        messages=[{"role": "user", "content":
                   "Corpus entry titles, for context only:\n"
                   + "\n".join(f"- {e.title}" for e in corpus.entries)
                   + f"\n\nUnanswered questions:\n{listing}"}],
        thinking={"type": "adaptive"},
        # Triage, not live answering, and it runs unattended. A reasonable
        # place to spend less than the desk does.
        output_config={"effort": "medium", "format": SCHEMA},
    )
    if response.stop_reason == "refusal":
        print("Model declined to triage the batch; nothing written.", file=sys.stderr)
        return 1

    text = next(b.text for b in response.content if b.type == "text")
    report = render(json.loads(text)["clusters"], demand, args.since)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
