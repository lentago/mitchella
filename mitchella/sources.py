"""Corpus sources: different document shapes, one `Entry` stream.

The same split the rest of the fleet uses. A source knows how one kind of
documentation tree is laid out; the corpus knows nothing about any of them. The
acceptance test is the familiar one — adding a source must not touch existing
sources, and must not touch `corpus.py` at all.

Three sources ship today:

- `flat`   — this repo's own `corpus/*.md`: one question, one answer, explicit
             frontmatter. The format to write *for* a desk.
- `wiki`   — an existing documentation tree of long-form pages with an `# H1`
             title. The format you already *have*, pointed at as-is, with
             nothing copied and nothing rewritten.
- `bundle` — a single published JSON artifact (uvularia's corpus bundle),
             addressed by URL or path and pinned by the digest it was named by.

`flat` and `wiki` read a *directory*. `bundle` reads one *artifact* — a URL or a
file — and declares its own fingerprint rather than having one computed from the
rendered bytes. A loader announces which it needs with a `reads` attribute
(`"directory"`, the default, or `"artifact"`); `corpus.load` honours it. That is
the one seam the bundle source cuts into `corpus.py`, and it is documented in
ADR-0006. Dir-based sources are still added without touching `corpus.py`.

The `wiki` source exists so a corpus can live outside this repo entirely. Point
`MITCHELLA_CORPUS_DIR` at a checkout somewhere else and no document is ever
copied in here — which matters when the documentation and the bot have
different homes, different licences, or different confidentiality rules. The
`bundle` source goes one step further: the corpus need not be a checkout at all,
only a URL that a publisher keeps current.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from .entry import CorpusError, Entry

#: A page carrying this phrase is telling the reader its contents are inferred
#: from records rather than observed on a live system. That is a load-bearing
#: caveat, not decoration: an assistant that drops it converts a careful
#: handbook into confident claims. Detected here, carried on the entry, and
#: enforced in the engine's instructions.
_INFERRED = re.compile(r"Evidence basis:\s*inferred", re.IGNORECASE)
_VERIFIED = re.compile(r"Evidence basis:\s*verified", re.IGNORECASE)

#: The notice is boilerplate repeated on every page of a well-run wiki. Strip it
#: from the body and keep the fact in metadata — on a large tree this is tens of
#: thousands of tokens of pure duplication, and the caveat survives intact.
_NOTICE_BLOCK = re.compile(
    # Greedy to the end of each line, then every following blockquote line.
    # A lazy quantifier here matches the opening fragment and stops.
    r"^>[^\n]*Evidence basis:[^\n]*(?:\n>[^\n]*)*\n?",
    re.MULTILINE | re.IGNORECASE,
)

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_YAML_LIST_ITEM = re.compile(r"^\s*-\s*(.+?)\s*$")


def _split_frontmatter(text: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(text)
    return (match.group(1), text[match.end():]) if match else ("", text)


def _yaml_tags(block: str) -> tuple[str, ...]:
    """Read a `tags:` key, in either the inline or block-list YAML form.

    Deliberately not a YAML parser. It reads the one key this needs and ignores
    everything else, which keeps the dependency list at zero and fails soft on
    frontmatter shapes it does not recognise.
    """
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("tags:"):
            continue
        inline = line.partition(":")[2].strip()
        if inline.startswith("[") and inline.endswith("]"):
            inner = inline[1:-1].strip()
            return tuple(p.strip().strip("\"'") for p in inner.split(",")) if inner else ()
        tags = []
        for follow in lines[i + 1:]:
            if follow.strip() and not follow.startswith((" ", "\t", "-")):
                break
            item = _YAML_LIST_ITEM.match(follow)
            if item:
                tags.append(item.group(1).strip("\"'"))
        return tuple(tags)
    return ()


def load_flat(root: Path) -> tuple[Entry, ...]:
    """This repo's own corpus format. Frontmatter is required and validated."""
    from .corpus import parse_flat_entry
    return tuple(parse_flat_entry(p, root) for p in sorted(root.rglob("*.md")))


def load_wiki(root: Path, *, ignore: tuple[str, ...] = ()) -> tuple[Entry, ...]:
    """A documentation tree of long-form pages.

    Structure is inferred rather than required, because the tree belongs to
    someone else and should not have to change shape to be readable here:

    - **id** from the path (`wiki/systems/jenkins.md` -> `systems-jenkins`)
    - **title** from the first `# H1`; a page without one is skipped, since a
      page with no title is almost always an index or a fragment
    - **tags** from frontmatter plus the parent directory name, so a page's
      section is searchable even when nobody wrote tags
    - **certainty** from the evidence-basis notice, if the tree uses one
    - **volatility** defaults to `stable`; current-state questions are the
      signal plane's job, not the corpus's
    """
    entries: list[Entry] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(pattern in str(rel) for pattern in ignore):
            continue

        text = path.read_text(encoding="utf-8")
        front, body = _split_frontmatter(text)

        title_match = _H1.search(body)
        if not title_match:
            continue
        title = title_match.group(1)

        certainty = "unknown"
        if _VERIFIED.search(body):
            certainty = "verified"
        elif _INFERRED.search(body):
            certainty = "inferred"

        body = _NOTICE_BLOCK.sub("", body).strip()

        doc_id = "-".join(rel.with_suffix("").parts).lower()
        doc_id = re.sub(r"[^a-z0-9]+", "-", doc_id).strip("-")

        section = rel.parts[-2] if len(rel.parts) > 1 else "root"
        tags = tuple(dict.fromkeys((*_yaml_tags(front), section)))

        entries.append(Entry(
            doc_id=doc_id,
            title=title,
            tags=tags,
            volatility="stable",
            certainty=certainty,
            body=body,
            path=str(rel),
        ))
    return tuple(entries)


#: Required keys on a bundle entry. The bundle is already in mitchella's entry
#: shape (uvularia `bundle.schema.json`), so there is no frontmatter to parse —
#: only a shape to verify. A record missing any of these is a malformed bundle,
#: and a malformed corpus fails loudly rather than loading half-read.
_BUNDLE_FIELDS = ("doc_id", "title", "tags", "volatility", "body", "path", "certainty")


def _read_artifact(location: str, timeout: float) -> str:
    """Read a single artifact from a URL or a local path.

    Unlike a signal source, a corpus that cannot be read is fatal, not a
    degradation: there is nothing to answer *from*. So this raises `CorpusError`
    rather than returning an "unknown", matching how `corpus.load` already
    treats a missing directory.
    """
    try:
        if location.startswith(("http://", "https://")):
            with urllib.request.urlopen(location, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        return Path(location).read_text(encoding="utf-8")
    except (OSError, urllib.error.URLError) as exc:
        raise CorpusError(f"could not read bundle at {location}: {exc}") from exc


def _entry_from_bundle_record(rec: dict) -> Entry:
    missing = [k for k in _BUNDLE_FIELDS if k not in rec]
    if missing:
        raise CorpusError(f"bundle record {rec.get('doc_id', '?')!r} missing {missing}")
    volatility = str(rec["volatility"])
    if volatility not in ("stable", "live"):
        raise CorpusError(
            f"bundle record {rec['doc_id']!r}: volatility must be 'stable' or 'live'"
        )
    return Entry(
        doc_id=str(rec["doc_id"]),
        title=str(rec["title"]),
        tags=tuple(rec["tags"]),
        volatility=volatility,
        certainty=str(rec["certainty"]),
        body=str(rec["body"]),
        path=str(rec["path"]),
    )


def load_bundle(location: str, *, timeout: float = 5.0) -> tuple[tuple[Entry, ...], str]:
    """A published corpus bundle: one JSON artifact, pinned by its digest.

    The bundle is how a vault hands mitchella a corpus without handing over the
    vault (uvularia ADR-0009): a URL the publisher keeps current, carrying every
    published record already in this package's entry shape, plus the `digest`
    it was named by.

    Three things set it apart from the directory sources, and all three are the
    point:

    - **It is addressed by URL or path**, so the corpus need not live on disk.
    - **The digest is the fingerprint.** A consumer pins exactly the artifact
      the vault published; two hosts that fetched the same URL agree on the
      cache prefix without re-deriving it. Returned alongside the entries so
      `corpus.load` can use it in place of a hash of the rendered bytes.
    - **`archived` records are dropped.** They stay in the vault's record but
      leave the prompt — the bundle's way of letting old documents age out of
      context without being forgotten (ADR-0009's `archived` flag).
    """
    try:
        payload = json.loads(_read_artifact(location, timeout))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"bundle at {location} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "digest" not in payload or "records" not in payload:
        raise CorpusError(f"bundle at {location} is missing 'digest'/'records'")

    entries = tuple(
        _entry_from_bundle_record(rec)
        for rec in payload["records"]
        if not rec.get("archived")
    )
    return entries, str(payload["digest"])


#: This source reads one artifact (a URL or file), not a directory, and brings
#: its own fingerprint. `corpus.load` branches on this.
load_bundle.reads = "artifact"

#: Source name -> loader. Adding a source is one entry here and one function.
LOADERS = {"flat": load_flat, "wiki": load_wiki, "bundle": load_bundle}
