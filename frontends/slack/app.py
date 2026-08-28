"""Slack frontend — the first client.

Socket Mode, so the demo needs no public URL, no tunnel, and no inbound
firewall change. Two entry points: an app mention in a channel, and a direct
message.

Like the CLI, this imports `mitchella` and nothing deeper. Everything
Slack-specific — block rendering, event plumbing, the ephemeral caveat — stops
at this directory.

Setup:

    pip install -e '.[slack]'
    export SLACK_BOT_TOKEN=xoxb-...      # Bot User OAuth Token
    export SLACK_APP_TOKEN=xapp-...      # App-Level Token, scope connections:write
    python -m frontends.slack.app

Slack app scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`,
`im:write`. Event subscriptions: `app_mention`, `message.im`.
"""

from __future__ import annotations

import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from frontends.cli.main import build_engine
from mitchella import Answer, AnswerKind, Config, Query, opaque_ref

log = logging.getLogger("mitchella.slack")

_HEADER = {
    AnswerKind.ANSWERED: None,
    AnswerKind.INCIDENT: ":warning: *This looks like a live incident.*",
    AnswerKind.ESCALATED: ":inbox_tray: *I can't answer this one — here's a ticket draft.*",
    AnswerKind.DECLINED: None,
}


def to_blocks(answer: Answer) -> list[dict]:
    """Render an Answer as Slack blocks.

    The whole of mitchella's Slack-specific knowledge lives in this function.
    """
    blocks: list[dict] = []

    header = _HEADER[answer.kind]
    if header:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": answer.text or "_(no reply)_"}})

    if answer.incidents:
        lines = "\n".join(
            f"• *{i.title}* — {i.status} _(via {i.source})_" + (f"\n  <{i.url}|more>" if i.url else "")
            for i in answer.incidents
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lines}})

    if answer.ticket_draft:
        d = answer.ticket_draft
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{d.title}*  `{d.category}`\n```{d.body}```"},
        })
        # Deliberately not a "Submit" button. mitchella has no write access to
        # any system; a human copies this into the tracker. Adding a button
        # here would be adding a write path, and that is a different design.
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "_Draft only — mitchella cannot file tickets._"}],
        })

    if answer.sources:
        cited = "  ".join(f"`{s.doc_id}`" for s in answer.sources)
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"sources: {cited}"}]})

    if answer.degraded_signals:
        detail = "; ".join(answer.degraded_signals)
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                # Never fake green: an unreachable signal makes the answer more
                # cautious, and the reader is told why.
                "text": f":grey_question: _Couldn't confirm current state ({detail}). Treat as unknown, not healthy._",
            }],
        })

    return blocks


def build_app() -> App:
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    engine = build_engine(Config.from_env())

    def respond(text: str, event: dict, say) -> None:
        text = text.strip()
        if not text:
            return
        answer = engine.answer(Query(
            text=text,
            surface="slack",
            user_ref=opaque_ref(event.get("user", "unknown")),
            thread_ref=event.get("thread_ts") or event.get("ts"),
        ))
        say(blocks=to_blocks(answer), text=answer.text or "mitchella",
            thread_ts=event.get("thread_ts") or event.get("ts"))

    @app.event("app_mention")
    def on_mention(event, say):
        # Strip the leading <@Uxxxx> mention so the model sees the question only.
        body = event.get("text", "")
        respond(body.split(">", 1)[-1] if ">" in body else body, event, say)

    @app.event("message")
    def on_dm(event, say):
        if event.get("channel_type") != "im" or event.get("bot_id"):
            return
        respond(event.get("text", ""), event, say)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    SocketModeHandler(build_app(), os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
