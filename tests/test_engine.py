"""The engine's invariants — the ones that must hold without the model's help.

Everything here runs against a fake client. These are not tests of what Claude
says; they are tests of the guarantees that hold *whatever* Claude says.
"""

import json
import types

import pytest

import mitchella
from mitchella import AnswerKind, Config, ManualOverrideProvider, Query, SignalPlane
from mitchella.engine import Engine


class FakeResponse:
    def __init__(self, payload, *, stop_reason="end_turn", stop_details=None):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = [types.SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = types.SimpleNamespace(
            input_tokens=10, output_tokens=20,
            cache_read_input_tokens=5000, cache_creation_input_tokens=0,
        )


class FakeClient:
    """Records the request so tests can assert on prompt structure."""

    def __init__(self, response):
        self.response = response
        self.calls = []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def decision(**over):
    base = {
        "kind": "answered", "reply": "Drop it in /mnt/lentago/web/.",
        "source_ids": ["pub-lan-drop"], "ticket_title": "",
        "ticket_body": "", "ticket_category": "",
    }
    base.update(over)
    return base


def build(response, incidents_file="signals/incidents.toml", config=None):
    return Engine(
        corpus=mitchella.load_corpus("corpus"),
        signal_plane=SignalPlane([ManualOverrideProvider(incidents_file)]),
        client=FakeClient(response),
        config=config or Config(),
    )


def ask(engine, text="how do I share a file?"):
    return engine.answer(Query(text=text, surface="test"))


# -- prompt assembly / the cache invariant --------------------------------

def test_nothing_volatile_renders_into_the_cached_prefix():
    """The prefix must be byte-identical across turns, or nothing ever caches.

    This is the test that protects the economics. If someone later interpolates
    a timestamp, a username, or the incident list into the system prompt, the
    cache silently stops hitting and only the bill notices.
    """
    engine = build(FakeResponse(decision()))
    ask(engine, "first question, asked by someone")
    ask(engine, "an entirely different question")

    first, second = (json.dumps(c["system"], sort_keys=True) for c in engine.client.calls)
    assert first == second


def test_live_state_rides_after_the_prefix_as_an_operator_message():
    engine = build(FakeResponse(decision()))
    ask(engine)
    messages = engine.client.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "system"]
    assert "LIVE STATE" in messages[-1]["content"]


def test_cache_breakpoint_sits_on_the_last_system_block():
    engine = build(FakeResponse(decision()))
    ask(engine)
    system = engine.client.calls[0]["system"]
    assert "cache_control" not in system[0]
    assert system[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_adaptive_thinking_and_effort_are_set():
    engine = build(FakeResponse(decision()))
    ask(engine)
    kwargs = engine.client.calls[0]
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == "high"


# -- ADR-0001: the incident gate is enforced in code ----------------------

def test_open_incident_overrides_an_answered_verdict(tmp_path):
    """The model may still say "answered". The gate does not depend on it.

    Prompt text is guidance, and guidance is what a model gets talked out of.
    """
    incidents = tmp_path / "incidents.toml"
    incidents.write_text(
        '[[incident]]\nid="i1"\ntitle="Grafana is down"\nstatus="investigating"\n'
        'open=true\nsubjects=["grafana"]\n'
    )
    engine = build(FakeResponse(decision()), incidents_file=str(incidents))
    answer = ask(engine, "why can't I load grafana?")
    assert answer.kind is AnswerKind.INCIDENT
    assert answer.incidents and answer.incidents[0].title == "Grafana is down"


def test_unrelated_incident_does_not_hijack_the_answer(tmp_path):
    incidents = tmp_path / "incidents.toml"
    incidents.write_text(
        '[[incident]]\nid="i1"\ntitle="Grafana is down"\nopen=true\nsubjects=["grafana"]\n'
    )
    engine = build(FakeResponse(decision()), incidents_file=str(incidents))
    answer = ask(engine, "how do I share a file on the LAN?")
    assert answer.kind is AnswerKind.ANSWERED
    assert answer.incidents == ()


# -- honesty guarantees ---------------------------------------------------

def test_fabricated_source_ids_are_dropped():
    engine = build(FakeResponse(decision(source_ids=["pub-lan-drop", "does-not-exist"])))
    answer = ask(engine)
    assert [s.doc_id for s in answer.sources] == ["pub-lan-drop"]


def test_refusal_is_detected_before_content_is_read():
    response = FakeResponse(
        "not json at all", stop_reason="refusal",
        stop_details=types.SimpleNamespace(category="cyber"),
    )
    answer = ask(build(response))
    assert answer.kind is AnswerKind.DECLINED
    assert "cyber" in answer.text


def test_unparseable_output_escalates_rather_than_guessing():
    answer = ask(build(FakeResponse("{ this is not json")))
    assert answer.kind is AnswerKind.ESCALATED
    assert answer.ticket_draft is not None
    assert answer.ticket_draft.category == "bot-fault"


def test_escalation_carries_a_draft_that_is_never_submitted():
    engine = build(FakeResponse(decision(
        kind="escalated", source_ids=[],
        ticket_title="VPN drops every 20 minutes",
        ticket_body="Reported on the CLI surface.", ticket_category="network",
    )))
    answer = ask(engine, "my vpn keeps dropping")
    assert answer.kind is AnswerKind.ESCALATED
    assert answer.ticket_draft.title == "VPN drops every 20 minutes"


def test_degraded_signals_reach_the_answer_and_flip_the_honesty_flag(tmp_path):
    engine = Engine(
        corpus=mitchella.load_corpus("corpus"),
        signal_plane=SignalPlane([mitchella.DroseraStatusProvider(str(tmp_path / "gone.json"))]),
        client=FakeClient(FakeResponse(decision())),
        config=Config(),
    )
    answer = ask(engine)
    assert answer.degraded_signals
    assert answer.is_trustworthy is False


def test_usage_reports_cache_reads():
    answer = ask(build(FakeResponse(decision())))
    assert answer.usage.cache_read_input_tokens == 5000
    assert 0.0 < answer.usage.cached_fraction <= 1.0
