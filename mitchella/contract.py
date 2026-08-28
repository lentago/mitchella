"""The frontend boundary.

Everything a user interface needs in order to talk to mitchella lives in this
module. A frontend imports `Query`, `Answer`, and `Engine` — and nothing else
from this package.

That restraint is the whole point. The fleet's agnosticism principle says the
current implementation is always "the first client", never the product, and it
carries a mechanical acceptance test: **adding a client must not touch existing
clients.** Here that means adding a frontend must not require editing a single
file outside `frontends/<name>/`. Slack is the first client. The CLI is the
second, and it exists partly to keep the first one honest — a boundary with one
implementation behind it is a boundary nobody has tested.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AnswerKind(str, Enum):
    """What mitchella decided to do with a question.

    The four outcomes are deliberately exhaustive and deliberately small. A
    frontend renders each one differently, and a frontend that forgets one
    should fail loudly rather than fall through to a generic reply.
    """

    #: Answered from the corpus. Sources are attached.
    ANSWERED = "answered"
    #: The question is a symptom of a live incident. The corpus answer, if any,
    #: was suppressed — see ADR-0001.
    INCIDENT = "incident"
    #: Not answerable from the corpus. A ticket draft is attached for a human
    #: to review and submit. mitchella never submits it.
    ESCALATED = "escalated"
    #: Out of scope, or the model declined. No draft, no guess.
    DECLINED = "declined"


@dataclass(frozen=True)
class Source:
    """A corpus entry that contributed to an answer."""

    doc_id: str
    title: str
    path: str


@dataclass(frozen=True)
class Incident:
    """A live-state finding from the signal plane.

    `subjects` are free-text tags (`grafana`, `pub.lan`, `bullpen`) matched
    against the question. They are how the engine decides whether an open
    incident is *relevant* to what was asked, rather than announcing every
    open incident on every question.
    """

    incident_id: str
    title: str
    status: str
    subjects: tuple[str, ...]
    source: str
    url: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class TicketDraft:
    """A proposed ticket. Never submitted by mitchella.

    The bot has no write tools at all (ADR-0005). This is the entire mechanism
    by which a question becomes an action: mitchella fills in a draft, a human
    reads it and submits it. Blast radius is zero by construction, which is a
    one-sentence answer on a security questionnaire rather than a paragraph.
    """

    title: str
    body: str
    category: str


@dataclass(frozen=True)
class Usage:
    """Token accounting for one turn.

    `cache_read_input_tokens` is a **cost** metric, not a quality metric. It
    says how much of the prompt prefix was reused; it says nothing about
    whether the answer was right. Improvement is measured by the promotion
    loop (ADR-0004), not by this number.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def cached_fraction(self) -> float:
        """Share of billable input served from cache, 0.0–1.0."""
        total = self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens
        return (self.cache_read_input_tokens / total) if total else 0.0


@dataclass(frozen=True)
class Query:
    """One question, from any surface.

    `user_ref` should already be opaque by the time it gets here — frontends
    call `opaque_ref()` on whatever native identifier they hold. mitchella has
    no use for a real username and the turn log is better off without one.
    """

    text: str
    surface: str
    user_ref: str = "anonymous"
    thread_ref: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Answer:
    """The response, before any surface-specific rendering.

    `degraded_signals` is load-bearing and must be surfaced by every frontend.
    It names signal sources that could not be reached. Borrowed wholesale from
    drosera's status page rule: **degrade gracefully, never fake green.** An
    unreachable status feed means "unknown", never "all clear".
    """

    kind: AnswerKind
    text: str
    sources: tuple[Source, ...] = ()
    incidents: tuple[Incident, ...] = ()
    ticket_draft: TicketDraft | None = None
    degraded_signals: tuple[str, ...] = ()
    usage: Usage = field(default_factory=Usage)
    corpus_fingerprint: str = ""

    @property
    def is_trustworthy(self) -> bool:
        """False when the answer rests on an incomplete view of live state.

        Not a correctness claim — an honesty flag. A frontend should attach a
        visible caveat when this is False.
        """
        return not self.degraded_signals


def opaque_ref(native_id: str, *, salt: str = "mitchella") -> str:
    """Hash a native user id into a stable, non-reversible reference.

    Frontends call this before constructing a `Query`. Turn logs keep a
    consistent handle for "the same person asked twice" — which the promotion
    loop needs — without keeping who that person is.
    """
    digest = hashlib.sha256(f"{salt}:{native_id}".encode()).hexdigest()
    return digest[:16]
