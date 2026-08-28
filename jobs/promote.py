"""The promotion loop: turn recurring unanswered questions into corpus entries.

This is the only mechanism by which mitchella improves (ADR-0004), and it is
deliberately the fleet's existing shape rather than anything new: an agent
proposes, a human merges, and the merge is the deploy. Nothing learns in place;
there is no drifting state to audit. What changed is a diff, reviewed by a
person, in git history.

    turn log  ->  cluster the misses  ->  draft entries  ->  branch + PR
                                                              ^
                                                     a human merges this

Run it nightly:

    python -m jobs.promote --since 1 --write

Without `--write` it prints what it would propose and changes nothing.

Note what is *not* here: any notion of the bot rewriting its own instructions,
or a feedback signal that adjusts behaviour without review. Both are buildable
and neither is worth the explanation it would cost.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mitchella import Config, load_corpus

#: Turn outcomes that represent a gap in the corpus.
MISS_KINDS = {"escalated", "declined"}

PROMPT = """\
You are reviewing a service desk's unanswered questions to decide what \
documentation is missing.

Below are questions the desk could not answer from its corpus. Group them into \
clusters that share an underlying need, then, for each cluster that appears \
worth documenting, draft a corpus entry.

Judgement, not volume:

- A cluster needs at least two distinct askers, or one question that clearly \
recurs, before it is worth an entry. One person asking one thing once is a \
ticket, not documentation.
- Draft only what you can write honestly. You do not know this estate beyond \
what the existing corpus tells you, so where the answer is unknown, write the \
entry as a stub that states the question and explicitly marks the answer as \
not yet documented. A stub a human completes is useful; a confident invention \
is worse than nothing.
- Set volatility to "live" if the answer depends on current system state, \
"stable" otherwise.
- Do not duplicate an existing entry. Existing ids are listed below.

Return each proposed entry with a kebab-case id, a title, tags, volatility, \
and the markdown body."""

SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "volatility": {"type": "string", "enum": ["stable", "live"]},
                        "body": {"type": "string"},
                        "rationale": {"type": "string"},
                        "asker_count": {"type": "integer"},
                    },
                    "required": ["id", "title", "tags", "volatility", "body",
                                 "rationale", "asker_count"],
                    "additionalProperties": False,
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["entries", "notes"],
        "additionalProperties": False,
    },
}

_SAFE_ID = re.compile(r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")


def read_misses(path: Path, since_days: int) -> list[dict]:
    """Turns that represent a corpus gap, within the window."""
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            when = datetime.fromisoformat(row["ts"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if when >= cutoff and row.get("kind") in MISS_KINDS:
            rows.append(row)
    return rows


def summarise(rows: list[dict]) -> str:
    """Render the misses for the model, with asker counts and no identities."""
    by_question: dict[str, set[str]] = {}
    for row in rows:
        by_question.setdefault(row["question"], set()).add(row.get("user_ref", "?"))

    lines = []
    for question, askers in sorted(by_question.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- ({len(askers)} distinct asker(s)) {question}")
    return "\n".join(lines)


def write_entry(corpus_dir: Path, entry: dict) -> Path:
    if not _SAFE_ID.match(entry["id"]):
        raise ValueError(f"unsafe corpus id from model: {entry['id']!r}")
    path = corpus_dir / f"{entry['id']}.md"
    if path.exists():
        raise FileExistsError(path)
    tags = ", ".join(entry.get("tags", []))
    path.write_text(
        "---\n"
        f"id: {entry['id']}\n"
        f"title: {entry['title']}\n"
        f"tags: [{tags}]\n"
        f"volatility: {entry['volatility']}\n"
        "---\n\n"
        f"{entry['body'].strip()}\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mitchella-promote")
    parser.add_argument("--since", type=int, default=1, help="window in days (default 1)")
    parser.add_argument("--write", action="store_true", help="write entries and open a branch")
    parser.add_argument("--min-askers", type=int, default=2,
                        help="drop clusters below this many distinct askers (default 2)")
    args = parser.parse_args(argv)

    config = Config.from_env()
    corpus = load_corpus(config.corpus_dir)
    rows = read_misses(Path(config.turnlog_path), args.since)

    if not rows:
        print(f"No unanswered questions in the last {args.since} day(s). Nothing to propose.")
        return 0

    print(f"{len(rows)} unanswered turn(s); "
          f"{len(Counter(r['question'] for r in rows))} distinct question(s).")

    import anthropic
    client = anthropic.Anthropic()

    existing = ", ".join(e.doc_id for e in corpus.entries)
    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=[{"type": "text", "text": PROMPT}],
        messages=[{"role": "user", "content":
                   f"Existing corpus ids: {existing}\n\n"
                   f"Unanswered questions:\n{summarise(rows)}"}],
        thinking={"type": "adaptive"},
        # Clustering is not intelligence-sensitive the way live triage is, and
        # this runs unattended overnight — a reasonable place to spend less.
        output_config={"effort": "medium", "format": SCHEMA},
    )

    if response.stop_reason == "refusal":
        print("Model declined to process the batch; nothing written.", file=sys.stderr)
        return 1

    text = next(b.text for b in response.content if b.type == "text")
    payload = json.loads(text)

    proposed = [e for e in payload["entries"] if e["asker_count"] >= args.min_askers]
    dropped = len(payload["entries"]) - len(proposed)

    if payload.get("notes"):
        print(f"\nnotes: {payload['notes']}")
    print(f"\n{len(proposed)} entry proposal(s)"
          f"{f'; {dropped} below the {args.min_askers}-asker floor' if dropped else ''}:")
    for entry in proposed:
        print(f"\n  {entry['id']}  [{entry['volatility']}]  {entry['title']}")
        print(f"    why: {entry['rationale']}")

    if not proposed:
        return 0

    if not args.write:
        print("\n(dry run — pass --write to create the files and a branch)")
        return 0

    branch = f"promote/{datetime.now(timezone.utc):%Y-%m-%d}"
    subprocess.run(["git", "checkout", "-b", branch], check=True)
    written = [write_entry(Path(config.corpus_dir), e) for e in proposed]
    subprocess.run(["git", "add", *map(str, written)], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"corpus: propose {len(written)} entries from unanswered questions",
         "-m", "Co-Authored-By: Claude <noreply@anthropic.com>"],
        check=True,
    )
    print(f"\nBranch {branch} has {len(written)} new entries. "
          "Review them, then open a PR — a human merges, and the merge is the deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
