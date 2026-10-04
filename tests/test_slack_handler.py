"""Slack failure modes, tested with fakes — no Slack, no Anthropic, no slack_bolt."""

import json
import logging

from mitchella import Answer, AnswerKind
from frontends.slack.handler import FAILURE_TEXT, Heartbeat, Responder, SeenEvents
from frontends.slack.render import MAX_BLOCKS, SECTION_LIMIT, chunk_text, to_blocks


class FakeEngine:
    def __init__(self, answer=None, error=None):
        self.answer_obj = answer or Answer(kind=AnswerKind.ANSWERED, text="hi")
        self.error = error
        self.calls = 0
        self.corpus = type("C", (), {"entries": (1, 2), "fingerprint": "abc"})()

    def answer(self, query):
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer_obj


class Say:
    def __init__(self, fail_blocks=False):
        self.posts = []
        self.fail_blocks = fail_blocks

    def __call__(self, **kw):
        if self.fail_blocks and "blocks" in kw:
            raise RuntimeError("invalid_blocks")
        self.posts.append(kw)


def make(engine=None, **kw):
    engine = engine or FakeEngine()
    return engine, Responder(engine, submit=lambda fn: fn(), **kw)


EVENT = {"user": "U1", "ts": "1.1", "channel": "C1", "text": "q"}


def test_engine_exception_posts_failure_in_thread_and_logs_traceback(caplog):
    engine, r = make(FakeEngine(error=TimeoutError("boom")))
    say = Say()
    with caplog.at_level(logging.ERROR, logger="mitchella.slack"):
        r.handle(EVENT, {"event_id": "E1"}, say, text="q")
    assert say.posts == [{"text": FAILURE_TEXT, "thread_ts": "1.1"}]
    assert any(rec.exc_info and "boom" in str(rec.exc_info[1]) for rec in caplog.records)


def test_failure_to_post_blocks_falls_back_to_plain_failure_notice():
    _, r = make()
    say = Say(fail_blocks=True)
    r.handle(EVENT, {"event_id": "E1"}, say, text="q")
    assert say.posts[0]["text"] == FAILURE_TEXT


def test_success_posts_blocks_in_thread():
    _, r = make()
    say = Say()
    r.handle({**EVENT, "thread_ts": "0.5"}, {"event_id": "E1"}, say, text="q")
    assert say.posts[0]["thread_ts"] == "0.5" and say.posts[0]["blocks"]


def test_redelivery_is_answered_once():
    engine, r = make()
    say = Say()
    assert r.handle(EVENT, {"event_id": "E1"}, say, text="q")
    assert not r.handle(EVENT, {"event_id": "E1"}, say, text="q")
    # A retry that arrives with a fresh event_id is still caught by client_msg_id.
    e2 = {**EVENT, "client_msg_id": "m1", "ts": "2.2"}
    assert r.handle(e2, {"event_id": "E2"}, say, text="q")
    assert not r.handle(e2, {"event_id": "E3"}, say, text="q")
    assert engine.calls == 2 and len(say.posts) == 2


def test_handle_returns_before_the_answer_is_produced():
    engine = FakeEngine()
    queued = []
    r = Responder(engine, submit=queued.append)
    r.handle(EVENT, {"event_id": "E1"}, Say(), text="q")
    assert engine.calls == 0 and len(queued) == 1


def test_seen_events_is_bounded():
    s = SeenEvents(capacity=2)
    for k in "abc":
        s.first_sight(k)
    assert s.first_sight("a")  # evicted, so it reads as new


def test_bot_mentions_and_bot_messages_are_ignored():
    engine, r = make(self_user_id="UBOT")
    say = Say()
    for i, ev in enumerate([
        {**EVENT, "bot_id": "B1"},
        {**EVENT, "subtype": "bot_message"},
        {**EVENT, "user": "UBOT"},
        {**EVENT, "subtype": "message_changed"},
    ]):
        assert not r.handle(ev, {"event_id": f"E{i}"}, say, text="q")
    assert engine.calls == 0 and not say.posts


def test_dm_only_filters_channel_messages():
    _, r = make()
    assert not r.handle({**EVENT, "channel_type": "channel"}, {}, Say(), text="q", dm_only=True)
    assert r.handle({**EVENT, "channel_type": "im"}, {}, Say(), text="q", dm_only=True)


def test_empty_text_is_ignored():
    engine, r = make()
    assert not r.handle(EVENT, {"event_id": "E1"}, Say(), text="  ")
    assert engine.calls == 0


def section_lengths(blocks):
    return [len(b["text"]["text"]) for b in blocks if b["type"] == "section"]


def test_long_answer_is_chunked_under_the_limit_without_loss():
    text = "\n\n".join(f"paragraph {i} " + "word " * 120 for i in range(20))
    blocks = to_blocks(Answer(kind=AnswerKind.ANSWERED, text=text))
    assert len(blocks) > 1 and max(section_lengths(blocks)) <= 3000
    assert "".join("".join(c.split()) for c in chunk_text(text)) == "".join(text.split())


def test_unbroken_text_is_hard_split():
    assert all(len(c) <= SECTION_LIMIT for c in chunk_text("x" * 10_000))


def test_long_ticket_body_and_incident_list_stay_under_the_limit():
    from mitchella import Incident, TicketDraft
    answer = Answer(
        kind=AnswerKind.ESCALATED, text="t",
        ticket_draft=TicketDraft("title", "y" * 7000, "cat"),
        incidents=tuple(Incident(f"i{n}", "T" * 200, "open", ("x",), "src") for n in range(40)),
    )
    blocks = to_blocks(answer)
    assert max(section_lengths(blocks)) <= 3000
    assert len(blocks) <= MAX_BLOCKS


def test_block_cap_truncates_with_marker_but_keeps_degraded_footer():
    answer = Answer(kind=AnswerKind.ANSWERED, text="line\n\n".join(["z" * 2000] * 80),
                    degraded_signals=("drosera: unreachable",))
    blocks = to_blocks(answer)
    assert len(blocks) <= MAX_BLOCKS
    flat = json.dumps(blocks)
    assert "truncated" in flat and "drosera: unreachable" in flat


def test_heartbeat_reports_corpus_and_writes_file(tmp_path, caplog):
    path = tmp_path / "hb.json"
    hb = Heartbeat(FakeEngine(), path=str(path), clock=lambda: 42.0)
    with caplog.at_level(logging.INFO, logger="mitchella.slack"):
        status = hb.beat()
    assert status["ok"] and json.loads(path.read_text())["corpus_entries"] == 2
    assert any("heartbeat" in r.getMessage() for r in caplog.records)


def test_heartbeat_is_not_ok_with_an_empty_corpus():
    engine = FakeEngine()
    engine.corpus.entries = ()
    assert not Heartbeat(engine).beat()["ok"]
