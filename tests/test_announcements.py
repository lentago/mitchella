"""AnnouncementProvider — active notices lead the answer; stale ones stay dark.

The guarantees under test: an announcement surfaces only when it is active
(`publish_at <= now`, not past its `expires`) AND its subjects match the
question; an announcement that matches nothing does not surface at all. The
committed fixture is the real demo Atom feed.
"""

from datetime import datetime, timezone

from mitchella import AnnouncementProvider, AnswerKind, Query, SignalPlane

FIXTURES = "tests/fixtures/uvularia"

_FEED = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
)


def _entry(title, *, updated="2026-01-01T00:00:00Z", content="", categories=(), expires=None):
    cats = "".join(f'<category term="{t}"/>' for t in categories)
    exp = f"<expires>{expires}</expires>" if expires else ""
    slug = title.lower().replace(" ", "-")
    return (
        f"<entry><id>urn:uvularia:record:{slug}</id>"
        f"<title>{title}</title><updated>{updated}</updated>"
        f"{cats}{exp}<content type=\"text\">{content}</content></entry>"
    )


def _feed(tmp_path, *entries):
    path = tmp_path / "feed.xml"
    path.write_text(_FEED.format(entries="".join(entries)))
    return str(path)


def _at(year, month, day):
    return lambda: datetime(year, month, day, tzinfo=timezone.utc)


# -- subject matching -----------------------------------------------------

def test_a_matched_announcement_surfaces(tmp_path):
    loc = _feed(tmp_path, _entry(
        "Ridge Loop ford closed", categories=("ridge-loop", "ford"),
        content="Use the footbridge route until further notice.",
    ))
    snap = SignalPlane([AnnouncementProvider(loc, clock=_at(2026, 10, 1))]).snapshot()
    relevant = snap.relevant_to("is the ridge-loop ford open?")
    assert len(relevant) == 1
    assert relevant[0].status == "announcement"
    assert relevant[0].source == "uvularia-announcements"


def test_an_unmatched_announcement_does_not_surface(tmp_path):
    """The failing case the issue asks for: an active announcement whose
    subjects are nowhere in the question must not appear."""
    loc = _feed(tmp_path, _entry("Ridge Loop ford closed", categories=("ridge-loop", "ford")))
    snap = SignalPlane([AnnouncementProvider(loc, clock=_at(2026, 10, 1))]).snapshot()
    assert snap.incidents, "the announcement did load"
    assert snap.relevant_to("what are the winter visitor-center hours?") == ()


def test_subjects_are_recovered_from_the_title_without_categories(tmp_path):
    loc = _feed(tmp_path, _entry("Lower Brook Trail reopened"))
    snap = SignalPlane([AnnouncementProvider(loc, clock=_at(2026, 10, 1))]).snapshot()
    assert snap.relevant_to("is the lower brook trail open?")
    assert snap.relevant_to("how do I dispatch a bullpen job?") == ()


# -- the active window ----------------------------------------------------

def test_a_future_dated_announcement_stays_dark(tmp_path):
    loc = _feed(tmp_path, _entry(
        "Upcoming closure", updated="2026-12-01T00:00:00Z", categories=("closure",)))
    incidents, degraded = AnnouncementProvider(loc, clock=_at(2026, 10, 1)).fetch()
    assert incidents == ()
    assert degraded is None


def test_an_expired_announcement_drops_off(tmp_path):
    loc = _feed(tmp_path, _entry(
        "Old notice", updated="2026-01-01T00:00:00Z",
        expires="2026-06-01T00:00:00Z", categories=("notice",)))
    incidents, _ = AnnouncementProvider(loc, clock=_at(2026, 10, 1)).fetch()
    assert incidents == ()


def test_an_active_announcement_is_included(tmp_path):
    loc = _feed(tmp_path, _entry(
        "Current notice", updated="2026-01-01T00:00:00Z",
        expires="2026-12-01T00:00:00Z", categories=("notice",)))
    incidents, _ = AnnouncementProvider(loc, clock=_at(2026, 10, 1)).fetch()
    assert len(incidents) == 1


# -- degrade, never crash -------------------------------------------------

def test_an_unreachable_feed_degrades(tmp_path):
    incidents, degraded = AnnouncementProvider(str(tmp_path / "absent.xml")).fetch()
    assert incidents == ()
    assert degraded


def test_an_unparseable_feed_degrades(tmp_path):
    path = tmp_path / "feed.xml"
    path.write_text("this is not xml <<<")
    incidents, degraded = AnnouncementProvider(str(path)).fetch()
    assert incidents == ()
    assert degraded


# -- the real published fixture -------------------------------------------

def test_the_real_feed_leads_with_a_current_closure(tmp_path, make_engine):
    plane = SignalPlane([AnnouncementProvider(f"{FIXTURES}/feed.xml", clock=_at(2026, 10, 3))])
    engine = make_engine(plane)

    answer = engine.answer(Query(text="is the ridge loop ford open right now?", surface="test"))
    assert answer.kind is AnswerKind.INCIDENT
    assert any("ford" in i.title.lower() for i in answer.incidents)


def test_the_real_feed_does_not_hijack_an_offtopic_question(tmp_path, make_engine):
    plane = SignalPlane([AnnouncementProvider(f"{FIXTURES}/feed.xml", clock=_at(2026, 10, 3))])
    engine = make_engine(plane)

    answer = engine.answer(Query(text="how do I reset my VPN password?", surface="test"))
    assert answer.kind is AnswerKind.ANSWERED
    assert answer.incidents == ()
