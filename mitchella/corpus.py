"""The corpus: markdown in git, rendered into one stable prompt prefix.

There is no vector store here, and for a corpus this size there should not be
one. See ADR-0002. The short version: a few hundred short documents fit inside
the model's context window, and putting the whole corpus in the prompt behind a
cache breakpoint deletes an entire category of failure ("why did it retrieve the
wrong document?") that a retrieval layer would introduce.

The constraint that buys is **byte stability**. A cached prefix survives only
while its bytes are identical, so the corpus may change on merge and at no other
time. Nothing per-request — no clock, no user name, no live incident state —
renders into this text. Those go after the cached prefix, in the message list.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

#: Rough characters-per-token. Only used to warn when the corpus is outgrowing
#: the whole-corpus strategy; never for billing.
_CHARS_PER_TOKEN = 4

#: When the rendered corpus passes this, the prefix is large enough that
#: retrieval starts to pay for itself. It is a prompt to reconsider ADR-0002,
#: not a hard limit — Claude Opus 5 has a 1M-token context window.
SOFT_TOKEN_CEILING = 150_000

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class CorpusError(ValueError):
    """A corpus document is malformed. Fail loudly; never silently skip."""


@dataclass(frozen=True)
class Entry:
    """One corpus document."""

    doc_id: str
    title: str
    tags: tuple[str, ...]
    #: "stable" — the answer does not depend on current system state.
    #: "live"   — the answer depends on live state, so an answer-cache must
    #:            never serve it and the signal plane always gets consulted.
    volatility: str
    body: str
    path: str

    @property
    def is_live(self) -> bool:
        return self.volatility == "live"


def _parse_scalar(raw: str) -> str | tuple[str, ...]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return ()
        return tuple(part.strip().strip("\"'") for part in inner.split(","))
    return raw.strip("\"'")


def _parse_entry(path: Path, root: Path) -> Entry:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        raise CorpusError(f"{path}: missing --- frontmatter block")

    meta: dict[str, str | tuple[str, ...]] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise CorpusError(f"{path}: frontmatter line is not 'key: value': {line!r}")
        key, _, value = line.partition(":")
        meta[key.strip()] = _parse_scalar(value)

    missing = {"id", "title", "volatility"} - set(meta)
    if missing:
        raise CorpusError(f"{path}: frontmatter missing {sorted(missing)}")

    volatility = meta["volatility"]
    if volatility not in ("stable", "live"):
        raise CorpusError(f"{path}: volatility must be 'stable' or 'live', got {volatility!r}")

    tags = meta.get("tags", ())
    if isinstance(tags, str):
        tags = (tags,) if tags else ()

    return Entry(
        doc_id=str(meta["id"]),
        title=str(meta["title"]),
        tags=tuple(tags),
        volatility=str(volatility),
        body=text[match.end():].strip(),
        path=str(path.relative_to(root)),
    )


@dataclass(frozen=True)
class Corpus:
    """The loaded corpus and its rendered, cacheable form."""

    entries: tuple[Entry, ...]
    rendered: str
    fingerprint: str

    @property
    def estimated_tokens(self) -> int:
        return len(self.rendered) // _CHARS_PER_TOKEN

    @property
    def is_outgrowing_prefix(self) -> bool:
        """True when it is time to revisit ADR-0002 and add retrieval."""
        return self.estimated_tokens > SOFT_TOKEN_CEILING

    def by_id(self, doc_id: str) -> Entry | None:
        return next((e for e in self.entries if e.doc_id == doc_id), None)


def load(corpus_dir: str | Path) -> Corpus:
    """Load every `*.md` under `corpus_dir` into one deterministic block.

    Determinism is the requirement, not a nicety: the files are sorted by id and
    rendered with fixed separators so that the same corpus always produces the
    same bytes, and therefore the same cache entry, on every process on every
    host.
    """
    root = Path(corpus_dir)
    if not root.is_dir():
        raise CorpusError(f"corpus directory not found: {root}")

    entries = tuple(sorted(
        (_parse_entry(p, root) for p in root.rglob("*.md")),
        key=lambda e: e.doc_id,
    ))
    if not entries:
        raise CorpusError(f"no corpus documents found under {root}")

    seen: set[str] = set()
    for entry in entries:
        if entry.doc_id in seen:
            raise CorpusError(f"duplicate corpus id: {entry.doc_id}")
        seen.add(entry.doc_id)

    blocks = []
    for entry in entries:
        blocks.append(
            f"<entry id=\"{entry.doc_id}\" volatility=\"{entry.volatility}\">\n"
            f"# {entry.title}\n"
            f"tags: {', '.join(entry.tags) if entry.tags else '(none)'}\n\n"
            f"{entry.body}\n"
            f"</entry>"
        )
    rendered = "\n\n".join(blocks)
    fingerprint = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    return Corpus(entries=entries, rendered=rendered, fingerprint=fingerprint)
