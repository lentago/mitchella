"""Slack block rendering.

Separated from `app.py` so it can be tested without `slack_bolt`, tokens, or a
workspace. This module is the whole of mitchella's Slack-specific knowledge;
`app.py` is only transport.
"""

from __future__ import annotations

from mitchella import Answer, AnswerKind

_HEADER = {
    AnswerKind.ANSWERED: None,
    AnswerKind.INCIDENT: ":warning: *This looks like a live incident.*",
    AnswerKind.ESCALATED: ":inbox_tray: *I can't answer this one — here's a ticket draft.*",
    AnswerKind.DECLINED: None,
}


def to_blocks(answer: Answer) -> list[dict]:
    blocks: list[dict] = []

    header = _HEADER[answer.kind]
    if header:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header}})

    blocks.append({"type": "section",
                   "text": {"type": "mrkdwn", "text": answer.text or "_(no reply)_"}})

    if answer.incidents:
        lines = "\n".join(
            f"• *{i.title}* — {i.status} _(via {i.source})_" + (f"\n  <{i.url}|more>" if i.url else "")
            for i in answer.incidents
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lines}})

    if answer.ticket_draft:
        d = answer.ticket_draft
        blocks.append({"type": "divider"})
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": f"*{d.title}*  `{d.category}`\n```{d.body}```"}})
        # Deliberately not a "Submit" button. mitchella has no write access to
        # any system (ADR-0005); a human copies this into the tracker. A button
        # here would be a write path, and that is a different design.
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": "_Draft only — mitchella cannot file tickets._"}]})

    if answer.sources:
        cited = "  ".join(f"`{s.doc_id}`" for s in answer.sources)
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"sources: {cited}"}]})

    if answer.degraded_signals:
        detail = "; ".join(answer.degraded_signals)
        blocks.append({"type": "context", "elements": [{
            "type": "mrkdwn",
            # Never fake green: an unreachable signal makes the answer more
            # cautious, and the reader is told why.
            "text": f":grey_question: _Couldn't confirm current state ({detail}). "
                    "Treat as unknown, not healthy._",
        }]})

    return blocks
