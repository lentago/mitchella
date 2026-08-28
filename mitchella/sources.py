"""Corpus sources: different document shapes, one `Entry` stream.

The same split the rest of the fleet uses. A source knows how one kind of
documentation tree is laid out; the corpus knows nothing about any of them. The
acceptance test is the familiar one — adding a source must not touch existing
sources, and must not touch `corpus.py` at all.

Two sources ship today:

- `flat`  — this repo's own `corpus/*.md`: one question, one answer, explicit
            frontmatter. The format to write *for* a desk.
- `wiki`  — an existing documentation tree of long-form pages with an `# H1`
            title. The format you already *have*, pointed at as-is, with
            nothing copied and nothing rewritten.

The `wiki` source exists so a corpus can live outside this repo entirely. Point
`MITCHELLA_CORPUS_DIR` at a checkout somewhere else and no document is ever
copied in here — which matters when the documentation and the bot have
different homes, different licences, or different confidentiality rules.
"""

from __future__ import annotations

import re
from pathlib import Path

from .entry import Entry

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


#: Source name -> loader. Adding a source is one entry here and one function.
LOADERS = {"flat": load_flat, "wiki": load_wiki}
