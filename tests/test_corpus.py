"""The corpus must render identically every time, or the cache never hits."""

import mitchella


def test_loads_the_demo_corpus():
    corpus = mitchella.load_corpus("corpus")
    assert len(corpus.entries) >= 5
    assert all(e.volatility in ("stable", "live") for e in corpus.entries)


def test_rendering_is_deterministic():
    a = mitchella.load_corpus("corpus")
    b = mitchella.load_corpus("corpus")
    assert a.rendered == b.rendered
    assert a.fingerprint == b.fingerprint


def test_live_entries_are_marked():
    corpus = mitchella.load_corpus("corpus")
    live = [e.doc_id for e in corpus.entries if e.is_live]
    # Current-state questions must never be answered from frozen text.
    assert "estate-status" in live


def test_rejects_malformed_frontmatter(tmp_path):
    (tmp_path / "bad.md").write_text("no frontmatter here")
    try:
        mitchella.load_corpus(tmp_path)
    except mitchella.corpus.CorpusError as exc:
        assert "frontmatter" in str(exc)
    else:
        raise AssertionError("malformed document was silently accepted")
