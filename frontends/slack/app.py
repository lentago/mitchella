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

Failure and retry behaviour (policy lives in `handler.py`): an engine error
posts a short failure notice in the thread and logs the traceback; listeners
acknowledge immediately and answer on a worker pool; events are deduplicated on
event_id / client_msg_id / channel+ts; messages from bots (including mentions)
are ignored.

Health: a heartbeat thread logs a `heartbeat {...}` line every
MITCHELLA_HEARTBEAT_SECONDS (default 30) with `ok` (corpus has entries),
entry count and corpus fingerprint. Set MITCHELLA_HEARTBEAT_FILE to also
rewrite that JSON to a file; supervise on its mtime going stale. Process alive
+ corpus loaded is all it claims — it does not probe Slack or the API.

Slack app scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`,
`im:write`. Event subscriptions: `app_mention`, `message.im`.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from frontends.cli.main import build_engine
from frontends.slack.handler import Heartbeat, Responder
from mitchella import Config

log = logging.getLogger("mitchella.slack")


def build_app() -> tuple[App, Heartbeat]:
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    engine = build_engine(Config.from_env())
    # Listeners only enqueue; the model call runs on this pool. Returning fast
    # is what gets the envelope acknowledged inside Slack's window, so Slack
    # doesn't redeliver while a slow answer is still being written.
    pool = ThreadPoolExecutor(max_workers=int(os.environ.get("MITCHELLA_SLACK_WORKERS", "4")),
                              thread_name_prefix="mitchella-answer")
    responder = Responder(engine, submit=pool.submit,
                          self_user_id=app.client.auth_test().get("user_id", ""))

    @app.event("app_mention")
    def on_mention(event, body, say):
        # Strip the leading <@Uxxxx> mention so the model sees the question only.
        text = event.get("text", "")
        responder.handle(event, body, say, text=text.split(">", 1)[-1] if ">" in text else text)

    @app.event("message")
    def on_dm(event, body, say):
        responder.handle(event, body, say, text=event.get("text", ""), dm_only=True)

    heartbeat = Heartbeat(engine, path=os.environ.get("MITCHELLA_HEARTBEAT_FILE", ""),
                          interval=float(os.environ.get("MITCHELLA_HEARTBEAT_SECONDS", "30")))
    return app, heartbeat


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app, heartbeat = build_app()
    heartbeat.start()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
