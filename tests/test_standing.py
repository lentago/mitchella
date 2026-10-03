"""StandingProvider — the box cannot assert compliance the board denies.

The guarantee under test: a row the public board publishes as in breach
(`amber`/`red`) suppresses a corpus answer on that obligation's subjects, and a
row the board could not compute (`no-data`) is reported as unknown, never as a
silent green. The committed fixture is the real demo standing file.
"""

import json

import pytest

from mitchella import AnswerKind, Query, SignalPlane, StandingProvider

FIXTURES = "tests/fixtures/uvularia"


def _row(**over):
    row = {
        "id": "ma-oml-meeting-notice",
        "state": "green",
        "satisfied_by": "2026-10-17-notice",
        "deadline": "2026-10-15",
        "published_at": "2026-10-03T00:00:00Z",
        "gap": -12,
    }
    row.update(over)
    return row


def _standing(tmp_path, rows):
    path = tmp_path / "standing.json"
    path.write_text(json.dumps(rows))
    return str(path)


# -- the breach becomes an incident on the obligation's subjects ----------

def test_red_row_is_an_incident_on_the_obligation_subjects(tmp_path):
    loc = _standing(tmp_path, [_row(id="ob-meeting", state="red")])
    provider = StandingProvider(loc, obligations={"ob-meeting": ["meeting", "notice"]})

    incidents, degraded = provider.fetch()
    assert degraded is None
    assert [i.status for i in incidents] == ["red"]
    assert incidents[0].subjects == ("meeting", "notice")
    assert incidents[0].source == "uvularia-standing"


def test_a_red_row_suppresses_a_corpus_answer_on_its_subjects(tmp_path, make_engine):
    """The headline: the model says "answered", the board says "in breach", and
    the board wins. This is the whole reason the provider exists."""
    loc = _standing(tmp_path, [_row(id="ob-meeting", state="red")])
    plane = SignalPlane([StandingProvider(loc, obligations={"ob-meeting": ["meeting"]})])
    engine = make_engine(plane)

    answer = engine.answer(Query(text="is our meeting notice posted on time?", surface="test"))
    assert answer.kind is AnswerKind.INCIDENT
    assert answer.incidents and answer.incidents[0].status == "red"


def test_a_breach_does_not_hijack_an_unrelated_question(tmp_path, make_engine):
    loc = _standing(tmp_path, [_row(id="ob-meeting", state="red")])
    plane = SignalPlane([StandingProvider(loc, obligations={"ob-meeting": ["meeting"]})])
    engine = make_engine(plane)

    answer = engine.answer(Query(text="how do I share a file on the LAN?", surface="test"))
    assert answer.kind is AnswerKind.ANSWERED
    assert answer.incidents == ()


def test_amber_is_a_breach_too(tmp_path):
    loc = _standing(tmp_path, [_row(id="ob-filing", state="amber")])
    incidents, _ = StandingProvider(loc, obligations={"ob-filing": ["filing"]}).fetch()
    assert [i.status for i in incidents] == ["amber"]


def test_green_rows_surface_nothing(tmp_path):
    loc = _standing(tmp_path, [_row(state="green"), _row(id="ob-other", state="green")])
    assert StandingProvider(loc).fetch() == ((), None)


# -- no-data is unknown, never a fake green -------------------------------

def test_a_no_data_row_degrades_rather_than_asserting_green(tmp_path):
    loc = _standing(tmp_path, [
        _row(id="ob-minutes", state="no-data",
             satisfied_by=None, deadline=None, published_at=None, gap=None),
    ])
    incidents, degraded = StandingProvider(loc).fetch()
    assert incidents == ()
    assert degraded and "ob-minutes" in degraded


def test_an_unrecognised_state_is_unknown_not_green(tmp_path):
    loc = _standing(tmp_path, [_row(id="ob-weird", state="chartreuse")])
    incidents, degraded = StandingProvider(loc).fetch()
    assert incidents == ()
    assert degraded and "ob-weird" in degraded


def test_an_unreachable_standing_file_degrades(tmp_path):
    incidents, degraded = StandingProvider(str(tmp_path / "absent.json")).fetch()
    assert incidents == ()
    assert degraded


# -- subject sourcing -----------------------------------------------------

def test_an_obligation_pack_supplies_titles_and_subjects(tmp_path):
    """Subjects and titles can arrive as a pack of obligation objects (the
    rules-release shape), not only as a bare mapping."""
    loc = _standing(tmp_path, [_row(id="ob-known", state="red"), _row(id="ob-unknown", state="red")])
    pack = [{"id": "ob-known", "title": "Meeting notice posted 48h ahead", "subjects": ["meeting"]}]

    incidents = {i.incident_id: i for i in StandingProvider(loc, obligations=pack).fetch()[0]}
    assert incidents["standing:ob-known"].subjects == ("meeting",)
    assert "Meeting notice posted 48h ahead" in incidents["standing:ob-known"].title
    # An obligation the pack does not describe still surfaces, keyed on its id,
    # rather than vanishing because its subjects are unknown.
    assert incidents["standing:ob-unknown"].subjects == ("ob-unknown",)


# -- the real published fixture -------------------------------------------

def test_the_real_standing_fixture_surfaces_its_published_breach():
    incidents, degraded = StandingProvider(f"{FIXTURES}/standing.json").fetch()
    assert degraded is None
    assert [i.status for i in incidents] == ["amber"]
    assert incidents[0].incident_id == "standing:ma-ag-charity-annual-filing"
