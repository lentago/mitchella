"""Shared test scaffolding for the uvularia providers.

The new providers are clients of the engine, so proving a breach or an
announcement *suppresses or leads an answer* means running a turn. These turns
run against a fake client, exactly as `test_engine.py` does — the point is never
what Claude says, only that the gate holds whatever it says.
"""

import json
import types

import pytest

import mitchella
from mitchella import Config
from mitchella.engine import Engine

_ANSWERED = {
    "kind": "answered",
    "reply": "Here is what the corpus says.",
    "source_ids": [],
    "ticket_title": "",
    "ticket_body": "",
    "ticket_category": "",
}


class FakeClient:
    """Returns one fixed decision and records nothing. The model is not the
    subject under test here; the signal gate is."""

    def __init__(self, payload: dict | None = None) -> None:
        text = json.dumps(payload or _ANSWERED)
        self._resp = types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn",
            stop_details=None,
            usage=types.SimpleNamespace(
                input_tokens=1, output_tokens=1,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
        )
        self.messages = types.SimpleNamespace(create=self._create)
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return self._resp


@pytest.fixture
def make_engine():
    """Build an engine over the repo's own corpus and a caller-supplied plane.

    The model always returns `answered`; whether the turn stays answered is the
    signal plane's doing, which is exactly what these tests assert.
    """

    def _make(signal_plane, payload: dict | None = None) -> Engine:
        return Engine(
            corpus=mitchella.load_corpus("corpus"),
            signal_plane=signal_plane,
            client=FakeClient(payload),
            config=Config(),
        )

    return _make
