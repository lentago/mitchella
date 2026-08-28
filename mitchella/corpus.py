"""The corpus: documents from some source, rendered into one stable prefix.

There is no vector store here. See ADR-0002 — the short version is that a
documentation tree measured in the low hundreds of thousands of tokens fits
inside a 1M-token context window, and putting all of it in the prompt behind a
cache breakpoint deletes an entire category of failure that a retrieval layer
would introduce.

The constraint that buys is **byte stability**. A cached prefix survives only
while its bytes are identical, so the corpus may change when its source tree
changes and at no other time. Nothing per-request — no clock, no user name, no
live incident state — renders into this text. Those go after the cached prefix,
in the message list.

Where the documents come from is `sources.py`'s problem, not this module's.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .entry import CorpusError, Entry
from .sources import LOADERS

__all__ = ["Corpus", "CorpusError", "Entry", "load", "SOFT_TOKEN_CEILING"]

#: Rough characters-per-token. Only used to size a corpus for a human; never
#: for billing. Use the token-counting endpoint if a real number matters.
_CHARS_PER_TOKEN = 4

#: Past this, the prefix is large enough that keyword prefiltering starts to pay
#: for itself. A prompt to reconsider ADR-0002, not a hard limit — the context
#: window is far larger, and the real trigger is question volume, not size.
SOFT_TOKEN_CEILING = 250_000

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_scalar(raw: str) -> str | tuple[str, ...]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return tuple(p.strip().strip("\"'") for p in inner.split(",")) if inner else ()
    return raw.strip("\"'")


def parse_flat_entry(path: Path, root: Path) -> Entry:
    """Parse one document in this repo's own corpus format.

    Strict on purpose: these documents are written *for* the desk, so a missing
    field is an authoring mistake worth surfacing immediately rather than a
    foreign tree's shape worth tolerating.
    """
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
    if meta["volatility"] not in ("stable", "live"):
        raise CorpusError(f"{path}: volatility must be 'stable' or 'live'")

    tags = meta.get("tags", ())
    if isinstance(tags, str):
        tags = (tags,) if tags else ()

    return Entry(
        doc_id=str(meta["id"]),
        title=str(meta["title"]),
        tags=tuple(tags),
        volatility=str(meta["volatility"]),
        certainty=str(meta.get("certainty", "unknown")),
        body=text[match.end():].strip(),
        path=str(path.relative_to(root)),
    )


@dataclass(frozen=True)
class Corpus:
    entries: tuple[Entry, ...]
    rendered: str
    fingerprint: str
    source: str = "flat"

    @property
    def estimated_tokens(self) -> int:
        return len(self.rendered) // _CHARS_PER_TOKEN

    @property
    def is_outgrowing_prefix(self) -> bool:
        return self.estimated_tokens > SOFT_TOKEN_CEILING

    @property
    def has_inferred_content(self) -> bool:
        """True when any document says its claims are unverified.

        The engine uses this to decide whether the answer must carry the
        caveat. A corpus of verified material should not be hedged; a corpus
        that says it is inferred must not be stated as fact.
        """
        return any(e.is_inferred for e in self.entries)

    def by_id(self, doc_id: str) -> Entry | None:
        return next((e for e in self.entries if e.doc_id == doc_id), None)


def _render(entries: tuple[Entry, ...]) -> str:
    blocks = []
    for e in entries:
        blocks.append(
            f'<entry id="{e.doc_id}" certainty="{e.certainty}" volatility="{e.volatility}">\n'
            f"# {e.title}\n"
            f"tags: {', '.join(e.tags) if e.tags else '(none)'}\n\n"
            f"{e.body}\n"
            f"</entry>"
        )
    return "\n\n".join(blocks)


def load(corpus_dir: str | Path, source: str = "flat", **kwargs) -> Corpus:
    """Load a corpus from `corpus_dir` using the named source.

    Determinism is a requirement, not a nicety: entries are sorted by id and
    rendered with fixed separators, so the same tree always produces the same
    bytes — and therefore the same cache entry — on every process on every host.
    """
    root = Path(corpus_dir)
    if not root.is_dir():
        raise CorpusError(f"corpus directory not found: {root}")
    if source not in LOADERS:
        raise CorpusError(f"unknown corpus source {source!r}; known: {sorted(LOADERS)}")

    entries = tuple(sorted(LOADERS[source](root, **kwargs), key=lambda e: e.doc_id))
    if not entries:
        raise CorpusError(f"no corpus documents found under {root} (source={source})")

    seen: set[str] = set()
    for entry in entries:
        if entry.doc_id in seen:
            raise CorpusError(f"duplicate corpus id: {entry.doc_id}")
        seen.add(entry.doc_id)

    rendered = _render(entries)
    return Corpus(
        entries=entries,
        rendered=rendered,
        fingerprint=hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16],
        source=source,
    )
