"""The signal plane: what is broken right now.

mitchella consults this **before** the corpus decides anything (ADR-0001). The
failure this prevents is the one that kills service-desk bots: during an outage,
a corpus-backed assistant confidently tells forty people to reset their password
because the corpus says that is how you fix a login problem. The corpus is not
wrong. It is answering the wrong question.

Two rules govern everything in this module.

**Consume the live pane; do not build one.** drosera owns the live pane and
publishes a machine-readable `status.json` on a schedule, backed by Grafana
Cloud. betula owns capture and archive. mitchella reads the former and never
queries the latter — a log search is a firehose to hallucinate over, not an
authority. Neither product grows into the other's role.

**Degrade gracefully; never fake green.** Every provider fails independently and
a failure yields an explicit *unknown*, recorded in `degraded`, never a healthy
result. An unreachable status feed must make the answer more cautious, not
silently more confident.
"""

from __future__ import annotations

import json
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contract import Incident


@dataclass(frozen=True)
class SignalSnapshot:
    """Live state at one moment, plus an honest account of what is unknown."""

    incidents: tuple[Incident, ...]
    degraded: tuple[str, ...]
    fetched_at: datetime

    def relevant_to(self, text: str) -> tuple[Incident, ...]:
        """Incidents whose subjects appear in the question.

        Subject matching is deliberately a plain substring test. It is crude,
        it is auditable, and a human can predict its behaviour — which matters
        more here than recall, because this is the gate that overrides the
        corpus. A missed match degrades to a normal corpus answer; a false
        match tells someone their working system is broken.
        """
        haystack = text.lower()
        return tuple(
            inc for inc in self.incidents
            if any(subject.lower() in haystack for subject in inc.subjects)
        )


class SignalProvider:
    """One source of live state.

    Implementations return incidents and never raise: a provider that cannot
    answer reports its own degradation instead. The plane's contract is that a
    broken source is visible, not fatal.
    """

    name = "provider"

    def fetch(self) -> tuple[tuple[Incident, ...], str | None]:
        raise NotImplementedError


class ManualOverrideProvider(SignalProvider):
    """Incidents declared by hand, in `signals/incidents.toml`.

    The lowest-technology input and the highest-value one. On day one, before
    any feed is wired up, a person on the desk can flip a flag and every
    surface starts saying the right thing within one poll. Every automated
    signal added later is an optimisation of this; none of them replace it,
    because a human knows about the outage before the monitoring does more
    often than anyone likes to admit.
    """

    name = "manual-override"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self) -> tuple[tuple[Incident, ...], str | None]:
        if not self.path.exists():
            # Absence is a legitimate "nothing declared", not a degradation:
            # the file is optional and an empty desk is the normal case.
            return (), None
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return (), f"{self.name}: unreadable ({exc})"

        incidents = []
        for raw in data.get("incident", []):
            if not raw.get("open", True):
                continue
            incidents.append(Incident(
                incident_id=str(raw.get("id", "manual")),
                title=str(raw.get("title", "Declared incident")),
                status=str(raw.get("status", "investigating")),
                subjects=tuple(raw.get("subjects", ())),
                source=self.name,
                url=raw.get("url"),
                detail=raw.get("detail"),
            ))
        return tuple(incidents), None


class DroseraStatusProvider(SignalProvider):
    """The drosera estate status feed (`status.json`).

    Reads the machine-readable companion that `drosera/status-page/build.py`
    writes beside the published page. Accepts a URL or a local path so the demo
    runs offline against a checked-out drosera build.

    A site whose status is neither healthy nor explicitly unknown becomes an
    incident. A site reporting "no data" becomes a *degradation*, not an
    incident and not a green light — that distinction is drosera's own rule and
    it is preserved here rather than reinterpreted.
    """

    name = "drosera-status"

    #: Status words drosera's build treats as healthy.
    _HEALTHY = {"ok", "operational", "healthy", "up"}
    #: Status words meaning the probe itself failed to report.
    _UNKNOWN = {"no data", "no_data", "unknown", "none"}

    def __init__(self, location: str, *, timeout: float = 5.0) -> None:
        self.location = location
        self.timeout = timeout

    def _read(self) -> str:
        if self.location.startswith(("http://", "https://")):
            with urllib.request.urlopen(self.location, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        return Path(self.location).read_text(encoding="utf-8")

    def fetch(self) -> tuple[tuple[Incident, ...], str | None]:
        try:
            payload = json.loads(self._read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            return (), f"{self.name}: unreachable ({exc})"

        incidents: list[Incident] = []
        unknowns: list[str] = []
        for site in payload.get("sites", []):
            name = str(site.get("name", "unknown"))
            status = str(site.get("status", "unknown")).strip().lower()
            if status in self._HEALTHY:
                continue
            if status in self._UNKNOWN:
                unknowns.append(name)
                continue
            incidents.append(Incident(
                incident_id=f"drosera:{name}",
                title=f"{name} is reporting {status}",
                status=status,
                subjects=(name,),
                source=self.name,
                url=payload.get("page_url"),
                detail=site.get("note"),
            ))

        degraded = f"{self.name}: no data for {', '.join(sorted(unknowns))}" if unknowns else None
        return tuple(incidents), degraded


class SignalPlane:
    """Fans out to every provider and merges the result."""

    def __init__(self, providers: list[SignalProvider]) -> None:
        self.providers = providers

    def snapshot(self) -> SignalSnapshot:
        incidents: list[Incident] = []
        degraded: list[str] = []
        for provider in self.providers:
            try:
                found, problem = provider.fetch()
            except Exception as exc:  # a provider bug must not take the desk down
                degraded.append(f"{provider.name}: provider error ({exc})")
                continue
            incidents.extend(found)
            if problem:
                degraded.append(problem)
        return SignalSnapshot(
            incidents=tuple(incidents),
            degraded=tuple(degraded),
            fetched_at=datetime.now(timezone.utc),
        )
