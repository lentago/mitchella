"""The corpus atom, shared by every source.

Its own module so that `corpus.py` (which assembles) and `sources.py` (which
parses) can both use it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass


class CorpusError(ValueError):
    """A corpus document is malformed. Fail loudly; never silently skip."""


@dataclass(frozen=True)
class Entry:
    """One corpus document."""

    doc_id: str
    title: str
    tags: tuple[str, ...]
    #: "stable" — the answer does not depend on current system state.
    #: "live"   — the answer depends on live state, so an answer cache must
    #:            never serve it.
    volatility: str
    body: str
    path: str
    #: How much weight this document's claims carry: "verified" (observed on a
    #: live system), "inferred" (assembled from records and not checked), or
    #: "unknown" (the source tree says nothing either way).
    #:
    #: This exists because a good handbook is often explicit that its contents
    #: are inferred, and an assistant that quietly drops that caveat turns
    #: careful writing into confident assertion. The engine is required to
    #: preserve it in the answer.
    certainty: str = "unknown"

    @property
    def is_live(self) -> bool:
        return self.volatility == "live"

    @property
    def is_inferred(self) -> bool:
        return self.certainty == "inferred"
