"""Append-only turn log — the input to the promotion loop.

One JSON object per line. This is the only thing that makes mitchella improve
over time (ADR-0004): the nightly job reads these, finds questions that recur
and answers that got rejected, and opens a pull request against the corpus.

What is deliberately *not* here: usernames, message text from other people,
channel names. `user_ref` arrives already hashed. The log needs to know that the
same person asked twice; it does not need to know who they are.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .contract import Answer, Query


class TurnLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, query: Query, answer: Answer) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "surface": query.surface,
            "user_ref": query.user_ref,
            "question": query.text,
            "kind": answer.kind.value,
            "source_ids": [s.doc_id for s in answer.sources],
            "incident_ids": [i.incident_id for i in answer.incidents],
            "degraded_signals": list(answer.degraded_signals),
            "corpus_fingerprint": answer.corpus_fingerprint,
            "usage": asdict(answer.usage),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
