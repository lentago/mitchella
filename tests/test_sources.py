"""The wiki source reads a foreign documentation tree without changing it."""

import mitchella

WIKI_PAGE = """\
---
tags:
  - service-management
  - operations
---

**Related**: [other](other.md)
**Last updated**: 2026-08-20

# Jenkins: the automation backbone

> **Evidence basis: inferred.** Unless a statement is marked verified, it
> was inferred from the system histories available when this page was
> written, not observed on a live system.
>
> Written from code; **not yet observed live**.

## 30-second brief

Jenkins runs the jobs.
"""


def build(tmp_path, name="systems/jenkins.md", text=WIKI_PAGE):
    page = tmp_path / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")
    return mitchella.load_corpus(tmp_path, "wiki")


def test_derives_id_title_and_section_tag(tmp_path):
    entry = build(tmp_path).entries[0]
    assert entry.doc_id == "systems-jenkins"
    assert entry.title == "Jenkins: the automation backbone"
    # frontmatter tags plus the directory the page lives in
    assert set(entry.tags) == {"service-management", "operations", "systems"}


def test_detects_inferred_certainty(tmp_path):
    corpus = build(tmp_path)
    assert corpus.entries[0].certainty == "inferred"
    assert corpus.entries[0].is_inferred
    assert corpus.has_inferred_content


def test_strips_the_repeated_notice_but_keeps_the_page(tmp_path):
    """The caveat moves to metadata; the boilerplate leaves the prompt.

    Repeated on every page of a large tree this is tens of thousands of tokens
    of duplication, and the caveat itself survives on `certainty`.
    """
    entry = build(tmp_path).entries[0]
    assert "Evidence basis" not in entry.body
    assert "not yet observed live" not in entry.body   # continuation lines too
    assert "Jenkins runs the jobs." in entry.body
    assert "**Related**" in entry.body                 # non-notice content intact


def test_page_without_frontmatter_still_loads(tmp_path):
    text = WIKI_PAGE.split("---\n", 2)[-1]
    entry = build(tmp_path, text=text).entries[0]
    assert entry.title == "Jenkins: the automation backbone"
    assert entry.tags == ("systems",)


def test_page_without_an_h1_is_skipped(tmp_path):
    (tmp_path / "a.md").write_text("no title here", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Real page\n\nbody", encoding="utf-8")
    corpus = mitchella.load_corpus(tmp_path, "wiki")
    assert [e.doc_id for e in corpus.entries] == ["b"]


def test_certainty_reaches_the_rendered_prefix(tmp_path):
    """The model must be able to see how much weight a document carries."""
    assert 'certainty="inferred"' in build(tmp_path).rendered


def test_unknown_source_is_rejected(tmp_path):
    (tmp_path / "a.md").write_text("# x\n\ny", encoding="utf-8")
    try:
        mitchella.load_corpus(tmp_path, "nope")
    except mitchella.CorpusError as exc:
        assert "unknown corpus source" in str(exc)
    else:
        raise AssertionError("an unknown source was silently accepted")
