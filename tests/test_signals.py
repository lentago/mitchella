"""Degrade gracefully; never fake green."""

import json

from mitchella import DroseraStatusProvider, ManualOverrideProvider, SignalPlane


def test_unreachable_status_feed_degrades_rather_than_reporting_healthy(tmp_path):
    plane = SignalPlane([DroseraStatusProvider(str(tmp_path / "absent.json"))])
    snap = plane.snapshot()
    assert snap.incidents == ()
    assert snap.degraded, "a missing feed must be recorded as unknown"


def test_no_data_site_is_unknown_not_an_incident(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"sites": [{"name": "lentago.dev", "status": "no data"}]}))
    snap = SignalPlane([DroseraStatusProvider(str(path))]).snapshot()
    assert snap.incidents == ()
    assert any("no data" in d for d in snap.degraded)


def test_failing_site_becomes_an_incident(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"sites": [{"name": "lentago.dev", "status": "down"}]}))
    snap = SignalPlane([DroseraStatusProvider(str(path))]).snapshot()
    assert len(snap.incidents) == 1
    assert snap.relevant_to("is lentago.dev up?")
    assert not snap.relevant_to("how do I dispatch a bullpen job?")


def test_manual_override_is_read(tmp_path):
    path = tmp_path / "incidents.toml"
    path.write_text(
        '[[incident]]\nid="x"\ntitle="Grafana is down"\nstatus="investigating"\n'
        'open=true\nsubjects=["grafana"]\n'
    )
    snap = SignalPlane([ManualOverrideProvider(path)]).snapshot()
    assert len(snap.incidents) == 1
    assert snap.degraded == ()
    assert snap.relevant_to("I can't load grafana")


def test_closed_incidents_are_ignored(tmp_path):
    path = tmp_path / "incidents.toml"
    path.write_text('[[incident]]\nid="x"\ntitle="over"\nopen=false\nsubjects=["grafana"]\n')
    assert SignalPlane([ManualOverrideProvider(path)]).snapshot().incidents == ()


def test_a_broken_provider_does_not_take_the_desk_down():
    class Exploding(ManualOverrideProvider):
        name = "exploding"

        def fetch(self):
            raise RuntimeError("boom")

    snap = SignalPlane([Exploding("nowhere")]).snapshot()
    assert snap.incidents == ()
    assert any("provider error" in d for d in snap.degraded)
