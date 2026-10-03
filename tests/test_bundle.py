"""The bundle source: one published artifact, pinned by its digest.

`flat` and `wiki` read a directory and hash the rendered bytes. The bundle reads
a single URL-or-file and carries its own digest, so these tests cover the two
things that makes different: the digest *is* the fingerprint, and `archived`
records leave the prompt. The committed fixture is the real demo bundle from
`lentago.github.io/uvularia-demo-records`.
"""

import json

import pytest

import mitchella
from mitchella import CorpusError

FIXTURES = "tests/fixtures/uvularia"
BUNDLE = f"{FIXTURES}/corpus-latest.json"


def _rec(doc_id, *, archived=False, volatility="stable", **over):
    rec = {
        "doc_id": doc_id,
        "title": f"Title {doc_id}",
        "tags": ["x"],
        "volatility": volatility,
        "body": f"body of {doc_id}",
        "path": f"records/{doc_id}.md",
        "certainty": "verified",
        "archived": archived,
    }
    rec.update(over)
    return rec


def _write_bundle(tmp_path, records, *, digest="a" * 64):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(
        {"digest": digest, "published_at": "2026-10-03T00:00:00Z", "records": records}
    ))
    return str(path)


def test_loads_the_published_demo_bundle():
    corpus = mitchella.load_corpus(BUNDLE, "bundle")
    assert corpus.source == "bundle"
    assert len(corpus.entries) > 50
    assert all(e.volatility in ("stable", "live") for e in corpus.entries)


def test_the_digest_is_the_fingerprint():
    with open(BUNDLE, encoding="utf-8") as fh:
        digest = json.load(fh)["digest"]
    # Not a hash of the rendered bytes — the publisher's digest verbatim, so two
    # hosts that fetched the same URL pin the same prefix without re-deriving it.
    assert mitchella.load_corpus(BUNDLE, "bundle").fingerprint == digest


def test_loading_is_deterministic():
    a = mitchella.load_corpus(BUNDLE, "bundle")
    b = mitchella.load_corpus(BUNDLE, "bundle")
    assert a.rendered == b.rendered
    assert a.fingerprint == b.fingerprint


def test_archived_records_leave_the_prompt(tmp_path):
    loc = _write_bundle(tmp_path, [_rec("keep"), _rec("gone", archived=True)])
    corpus = mitchella.load_corpus(loc, "bundle")
    assert [e.doc_id for e in corpus.entries] == ["keep"]
    assert "gone" not in corpus.rendered


def test_certainty_reaches_the_rendered_prefix():
    corpus = mitchella.load_corpus(BUNDLE, "bundle")
    # The demo bundle carries a few inferred records; the caveat must survive
    # into the prompt the model sees, as it does for the wiki source.
    assert corpus.has_inferred_content
    assert 'certainty="inferred"' in corpus.rendered


def test_a_bundle_missing_its_digest_fails_loudly(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"records": [_rec("x")]}))
    with pytest.raises(CorpusError, match="digest"):
        mitchella.load_corpus(str(path), "bundle")


def test_a_record_missing_a_field_fails_loudly(tmp_path):
    loc = _write_bundle(tmp_path, [{"doc_id": "x", "title": "t"}])
    with pytest.raises(CorpusError, match="missing"):
        mitchella.load_corpus(loc, "bundle")


def test_a_record_with_a_bad_volatility_fails_loudly(tmp_path):
    loc = _write_bundle(tmp_path, [_rec("x", volatility="whenever")])
    with pytest.raises(CorpusError, match="volatility"):
        mitchella.load_corpus(loc, "bundle")


def test_a_missing_bundle_file_fails_loudly(tmp_path):
    with pytest.raises(CorpusError, match="could not read"):
        mitchella.load_corpus(str(tmp_path / "absent.json"), "bundle")


def test_invalid_json_fails_loudly(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text("{ not json")
    with pytest.raises(CorpusError, match="not valid JSON"):
        mitchella.load_corpus(str(path), "bundle")
