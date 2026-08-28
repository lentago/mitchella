"""Runtime configuration. Environment in, frozen dataclass out."""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Claude Opus 5. One model for every stage, on purpose.
#:
#: The tempting shape is a cheap classifier in front of an expensive answerer.
#: Resist it until measurement justifies it: prompt caches are model-scoped, so
#: a two-model cascade forfeits cache reuse across the pair — and the corpus
#: prefix is where nearly all the tokens are. Turning `effort` down is the
#: cheaper lever and it keeps one cache namespace.
DEFAULT_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class Config:
    model: str = DEFAULT_MODEL

    #: Triage during an incident is intelligence-sensitive, so this starts at
    #: `high`. `medium` is the documented step-down to measure against a sample
    #: of real questions before adopting — not a default to assume.
    effort: str = "high"

    #: Generous on purpose. Thinking tokens count against this, and a truncated
    #: answer costs a full retry.
    max_tokens: int = 16_000

    #: A cache read refreshes the entry's timer for free, so continuous traffic
    #: keeps a 5-minute entry warm indefinitely and the 1-hour TTL buys nothing
    #: but a doubled write price. A service desk goes quiet between questions,
    #: so 1h is the right call here — and it is a real decision, not a default.
    cache_ttl: str = "1h"

    corpus_dir: str = "corpus"
    #: Which document shape `corpus_dir` holds: "flat" (this repo's own
    #: question/answer format) or "wiki" (a long-form documentation tree,
    #: read in place and never copied here).
    corpus_source: str = "flat"
    incidents_file: str = "signals/incidents.toml"
    #: URL or local path to drosera's status.json. Empty disables the provider.
    drosera_status: str = ""
    turnlog_path: str = "var/turns.jsonl"

    #: Server-side refusal fallbacks. Recommended default for Opus 5; set
    #: MITCHELLA_REFUSAL_FALLBACK=0 to call the non-beta endpoint instead.
    refusal_fallback: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            model=os.environ.get("MITCHELLA_MODEL", DEFAULT_MODEL),
            effort=os.environ.get("MITCHELLA_EFFORT", "high"),
            max_tokens=int(os.environ.get("MITCHELLA_MAX_TOKENS", "16000")),
            cache_ttl=os.environ.get("MITCHELLA_CACHE_TTL", "1h"),
            corpus_dir=os.environ.get("MITCHELLA_CORPUS_DIR", "corpus"),
            corpus_source=os.environ.get("MITCHELLA_CORPUS_SOURCE", "flat"),
            incidents_file=os.environ.get("MITCHELLA_INCIDENTS", "signals/incidents.toml"),
            drosera_status=os.environ.get("MITCHELLA_DROSERA_STATUS", ""),
            turnlog_path=os.environ.get("MITCHELLA_TURNLOG", "var/turns.jsonl"),
            refusal_fallback=os.environ.get("MITCHELLA_REFUSAL_FALLBACK", "1") != "0",
        )
