"""Slack frontend — the first client.

Socket Mode, so the demo needs no public URL, no tunnel, and no inbound
firewall change. Two entry points: an app mention in a channel, and a direct
message.

Like the CLI, this imports `mitchella` and nothing deeper. Block rendering
lives in `render.py` so it can be tested without tokens or a workspace; this
module is transport only.

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
from frontends.slack.render import to_blocks
from mitchella import Config, Query, opaque_ref

log = logging.getLogger("mitchella.slack")

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
