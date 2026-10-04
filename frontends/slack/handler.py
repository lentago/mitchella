"""Slack event handling, free of `slack_bolt` so it can be tested with fakes.

`app.py` is transport; `render.py` is blocks; this module is the policy between
them: which events to answer, answering each at most once, and never leaving a
thread silent when the engine fails.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Callable

from frontends.slack.render import to_blocks
from mitchella import Query, opaque_ref

log = logging.getLogger("mitchella.slack")

FAILURE_TEXT = (
    ":warning: I hit an error while answering and couldn't produce a reply. "
    "Nothing was lost on your side — please try again in a minute, and if it "
    "keeps happening tell whoever runs mitchella."
)

#: Subtypes that are edits/housekeeping rather than a person asking something.
_IGNORED_SUBTYPES = {"bot_message", "message_changed", "message_deleted"}


def is_from_bot(event: dict, self_user_id: str = "") -> bool:
    """True for anything a person didn't type: other apps, integrations, and
    ourselves. Applies to mentions as well as DMs — a bot that @-mentions
    mitchella must not be able to start a reply loop."""
    return bool(
        event.get("bot_id")
        or event.get("subtype") in _IGNORED_SUBTYPES
        or (self_user_id and event.get("user") == self_user_id)
    )


class SeenEvents:
    """Bounded memory of event ids, so a redelivered event is answered once.

    Slack redelivers an event it believes went unacknowledged, and a Socket
    Mode reconnect can replay them. In memory only: a restart forgets, which
    costs at worst one duplicate right after a deploy.
    """

    def __init__(self, capacity: int = 2048) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def first_sight(self, *keys: str) -> bool:
        """Record the keys; return False if any was already recorded."""
        keys = tuple(k for k in keys if k)
        with self._lock:
            fresh = not any(k in self._seen for k in keys)
            for k in keys:
                self._seen[k] = None
                self._seen.move_to_end(k)
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            return fresh


def dedupe_keys(event: dict, body: dict | None) -> tuple[str, ...]:
    return (
        (body or {}).get("event_id", ""),
        event.get("client_msg_id", ""),
        f"{event.get('channel', '')}:{event.get('ts', '')}" if event.get("ts") else "",
    )


class Responder:
    """Filter, dedupe, then answer off the listener thread.

    `submit` runs the work; in production it is an executor, so the listener
    returns (and Slack's envelope is acknowledged) before the slow model call.
    Tests pass a synchronous submit.
    """

    def __init__(self, engine, *, submit: Callable[[Callable[[], None]], object],
                 self_user_id: str = "") -> None:
        self.engine = engine
        self._submit = submit
        self._self_user_id = self_user_id
        self._seen = SeenEvents()

    def handle(self, event: dict, body: dict | None, say, *, text: str,
               dm_only: bool = False) -> bool:
        """Returns True if the event was accepted for answering."""
        if dm_only and event.get("channel_type") != "im":
            return False
        if is_from_bot(event, self._self_user_id):
            return False
        text = text.strip()
        if not text:
            return False
        if not self._seen.first_sight(*dedupe_keys(event, body)):
            log.info("dropping redelivered event %s", dedupe_keys(event, body)[0])
            return False
        self._submit(lambda: self._respond(text, event, say))
        return True

    def _respond(self, text: str, event: dict, say) -> None:
        thread_ts = event.get("thread_ts") or event.get("ts")
        try:
            answer = self.engine.answer(Query(
                text=text,
                surface="slack",
                user_ref=opaque_ref(event.get("user", "unknown")),
                thread_ref=thread_ts,
            ))
            say(blocks=to_blocks(answer), text=answer.text or "mitchella",
                thread_ts=thread_ts)
        except Exception:
            # Broad on purpose: API error, timeout, corpus problem, or a bad
            # block payload all look the same to the person waiting.
            log.exception("failed to answer event ts=%s", event.get("ts"))
            try:
                say(text=FAILURE_TEXT, thread_ts=thread_ts)
            except Exception:
                log.exception("could not post the failure notice either")


class Heartbeat:
    """Health signal: process alive and corpus loaded.

    Each beat logs one line and, if a path is given, rewrites a small JSON file.
    A supervisor treats a stale file mtime (or a missing log line) as unhealthy.
    The corpus is checked at beat time, so an empty corpus reports `ok: false`
    rather than a cheerful pulse.
    """

    def __init__(self, engine, path: str = "", interval: float = 30.0,
                 clock: Callable[[], float] = time.time) -> None:
        self._engine = engine
        self._path = path
        self._interval = interval
        self._clock = clock
        self._stop = threading.Event()

    def beat(self) -> dict:
        corpus = getattr(self._engine, "corpus", None)
        entries = len(corpus.entries) if corpus is not None else 0
        status = {
            "ok": entries > 0,
            "ts": self._clock(),
            "corpus_entries": entries,
            "corpus_fingerprint": getattr(corpus, "fingerprint", ""),
        }
        log.info("heartbeat %s", json.dumps(status))
        if self._path:
            tmp = f"{self._path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(status, fh)
            os.replace(tmp, self._path)  # atomic: a reader never sees half a file
        return status

    def start(self) -> threading.Thread:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.beat()
                except Exception:
                    log.exception("heartbeat failed")
                self._stop.wait(self._interval)

        t = threading.Thread(target=loop, name="mitchella-heartbeat", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
