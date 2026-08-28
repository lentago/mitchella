"""Slack rendering, tested without a workspace, tokens, or slack_bolt."""

from mitchella import Answer, AnswerKind, Incident, Source, TicketDraft
from frontends.slack.render import to_blocks


def texts(blocks):
    """Every string a reader would see, flattened."""
    out = []
    for b in blocks:
        if "text" in b and isinstance(b["text"], dict):
            out.append(b["text"]["text"])
        for el in b.get("elements", []):
            out.append(el.get("text", ""))
    return "\n".join(out)


def test_every_answer_kind_renders():
    """A frontend that forgets a kind should fail here, not in a channel."""
    for kind in AnswerKind:
        blocks = to_blocks(Answer(kind=kind, text="something"))
        assert blocks and texts(blocks)


def test_incident_leads_with_a_warning():
    answer = Answer(
        kind=AnswerKind.INCIDENT,
        text="Grafana is down.",
        incidents=(Incident("i1", "Grafana is down", "investigating",
                            ("grafana",), "manual-override", url="https://example.test"),),
    )
    rendered = texts(to_blocks(answer))
    assert "live incident" in rendered
    assert "Grafana is down" in rendered
    assert "https://example.test" in rendered


def test_degraded_signals_are_always_surfaced():
    """Dropping this turns 'unknown' into an implied 'fine'."""
    answer = Answer(kind=AnswerKind.ANSWERED, text="Here you go.",
                    degraded_signals=("drosera-status: unreachable",))
    rendered = texts(to_blocks(answer))
    assert "drosera-status: unreachable" in rendered
    assert "not healthy" in rendered


def test_ticket_draft_is_marked_as_not_filed_and_has_no_button():
    answer = Answer(
        kind=AnswerKind.ESCALATED, text="Routing this.",
        ticket_draft=TicketDraft("VPN drops", "Every 20 minutes.", "network"),
    )
    blocks = to_blocks(answer)
    assert "cannot file tickets" in texts(blocks)
    # ADR-0005: no write path, so no actionable element of any kind.
    assert not any(b["type"] == "actions" for b in blocks)


def test_sources_are_cited():
    answer = Answer(kind=AnswerKind.ANSWERED, text="See below.",
                    sources=(Source("pub-lan-drop", "Sharing a file", "corpus/pub-lan-drop.md"),))
    assert "pub-lan-drop" in texts(to_blocks(answer))


def test_empty_reply_does_not_render_an_empty_block():
    """Slack rejects a section block with empty text."""
    blocks = to_blocks(Answer(kind=AnswerKind.DECLINED, text=""))
    for b in blocks:
        if b["type"] == "section":
            assert b["text"]["text"].strip()
