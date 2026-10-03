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
import re
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .contract import Incident


def _read_location(location: str, timeout: float) -> str:
    """Read a URL or a local path. Shared by the feed-backed providers.

    Raising is the caller's cue to record a degradation — never to crash. Each
    provider wraps this in the narrow except that turns an unreachable source
    into an honest *unknown*.
    """
    if location.startswith(("http://", "https://")):
        with urllib.request.urlopen(location, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    return Path(location).read_text(encoding="utf-8")


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
        return _read_location(self.location, self.timeout)

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


def _index_obligations(
    obligations: Mapping[str, Sequence[str]] | Sequence[dict] | None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Normalise an obligation pack into id -> subjects and id -> title.

    Accepts either a plain mapping (`id -> subjects`) or a sequence of
    obligation objects in uvularia `obligation.schema.json` shape, because a
    deployment loads its pack from the rules release while a test wants to hand
    over three lines of subjects. Both arrive here and leave in one shape.
    """
    subjects: dict[str, tuple[str, ...]] = {}
    titles: dict[str, str] = {}
    if obligations is None:
        return subjects, titles
    if isinstance(obligations, Mapping):
        for oid, subs in obligations.items():
            subjects[str(oid)] = tuple(subs)
        return subjects, titles
    for ob in obligations:
        oid = str(ob["id"])
        subjects[oid] = tuple(ob.get("subjects", ()))
        if ob.get("title"):
            titles[oid] = str(ob["title"])
    return subjects, titles


def _standing_detail(row: dict) -> str:
    bits = []
    if row.get("deadline"):
        bits.append(f"deadline {row['deadline']}")
    if row.get("gap") is not None:
        bits.append(f"gap {row['gap']} day(s)")
    if row.get("satisfied_by"):
        bits.append(f"last satisfied by {row['satisfied_by']}")
    return "; ".join(bits) or "no detail published"


class StandingProvider(SignalProvider):
    """The uvularia standing file: one row per posting obligation.

    This is the provider that lets the Ask box be honest about compliance it
    does not control. The public board (uvularia ADR-0009) publishes a row per
    obligation — `green`, `amber`, `red`, or `no-data`. Anything in breach
    (`amber` or `red`) becomes an incident on *the obligation's subjects*, so a
    question about that obligation's area is answered by the breach, not by a
    corpus entry that would otherwise assert the estate is in order. The box
    cannot claim compliance the board denies.

    `no-data` is the whole reason this is a provider and not a lookup table: a
    row the publisher could not compute is reported as degraded — unknown, never
    a fake green. Subjects come from the obligation pack (the rules release),
    passed in at construction; a row whose obligation is unknown still surfaces,
    keyed on its own id, rather than vanishing.
    """

    name = "uvularia-standing"

    #: States that deny compliance. Both suppress a corpus answer on the
    #: obligation's subjects; `amber` is "at risk", and a desk that waited for
    #: `red` to say so would be reassuring people right up to the deadline.
    _BREACH = {"amber", "red"}
    #: A row the board could not compute. Degraded, never green.
    _NO_DATA = {"no-data", "no_data"}

    def __init__(
        self,
        location: str,
        *,
        obligations: Mapping[str, Sequence[str]] | Sequence[dict] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.location = location
        self.timeout = timeout
        self._subjects, self._titles = _index_obligations(obligations)

    def fetch(self) -> tuple[tuple[Incident, ...], str | None]:
        try:
            rows = json.loads(_read_location(self.location, self.timeout))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            return (), f"{self.name}: unreachable ({exc})"
        if not isinstance(rows, list):
            return (), f"{self.name}: standing file is not a list of rows"

        incidents: list[Incident] = []
        unknowns: list[str] = []
        for row in rows:
            oid = str(row.get("id", "?"))
            state = str(row.get("state", "")).strip().lower()
            if state == "green":
                continue
            if state in self._BREACH:
                incidents.append(Incident(
                    incident_id=f"standing:{oid}",
                    title=f"Obligation not met: {self._titles.get(oid, oid)} ({state})",
                    status=state,
                    # A breach with no known subjects falls back to its own id,
                    # which is auditable and still matches a question that names
                    # the obligation — never the empty tuple, which matches all
                    # of nothing and would silently drop the breach.
                    subjects=self._subjects.get(oid) or (oid,),
                    source=self.name,
                    detail=_standing_detail(row),
                ))
                continue
            # no-data, a blank state, or a value outside the enum: all unknown,
            # none of them green.
            label = oid if state in self._NO_DATA or not state else f"{oid} (state {state!r})"
            unknowns.append(label)

        degraded = f"{self.name}: no data for {', '.join(unknowns)}" if unknowns else None
        return tuple(incidents), degraded


@dataclass(frozen=True)
class _Announcement:
    id: str
    title: str
    subjects: tuple[str, ...]
    publish_at: datetime | None
    expires: datetime | None
    summary: str | None


#: Atom's namespace. Every element the feed cares about lives in it.
_ATOM = "{http://www.w3.org/2005/Atom}"

#: Pure function words dropped when deriving subjects from a title. Deliberately
#: tiny: the domain words ("trail", "ford", "water") are exactly the subjects a
#: question matches on, so only connectives are removed.
_TITLE_STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "your"}


def _parse_dt(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _subjects_from_title(title: str) -> tuple[str, ...]:
    """Subjects for a feed entry that carries no explicit `<category>`.

    The uvularia demo feed publishes title, body, and timestamp but not the
    record's `subjects`, so they are recovered from the title: its words, minus
    connectives and anything under four letters. The match stays a substring
    test, the same crude-but-auditable rule the incident gate already uses
    (ADR-0001) — a notice about the "Ridge Loop ford" surfaces on a question
    that names the ridge loop, and on little else.
    """
    words = re.findall(r"[a-z0-9]+", title.lower())
    return tuple(dict.fromkeys(w for w in words if len(w) >= 4 and w not in _TITLE_STOPWORDS))


def _parse_announcement(entry: ElementTree.Element) -> _Announcement | None:
    title_el = entry.find(f"{_ATOM}title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    if not title:
        return None  # a titleless entry has nothing to surface or match on

    id_el = entry.find(f"{_ATOM}id")
    raw_id = (id_el.text or "").strip() if id_el is not None else ""
    ann_id = raw_id.rsplit(":", 1)[-1] if raw_id else title

    updated_el = entry.find(f"{_ATOM}updated")
    publish_at = _parse_dt(updated_el.text or "") if updated_el is not None else None

    # Expiry is optional and lives outside Atom's core vocabulary, so it is
    # matched by local name in whatever namespace a feed chooses. Absent means
    # the announcement never expires on its own.
    expires = None
    for child in entry:
        if child.tag.rsplit("}", 1)[-1] == "expires" and child.text:
            expires = _parse_dt(child.text)

    terms = tuple(c.get("term") for c in entry.findall(f"{_ATOM}category") if c.get("term"))
    content_el = entry.find(f"{_ATOM}content")
    content = (content_el.text or "").strip() if content_el is not None else ""

    return _Announcement(
        id=ann_id,
        title=title,
        subjects=terms or _subjects_from_title(title),
        publish_at=publish_at,
        expires=expires,
        summary=(content[:280] or None),
    )


class AnnouncementProvider(SignalProvider):
    """The uvularia announcement feed (Atom): what the estate is telling people.

    A trail closure, a change of hours, a high-water notice — current, public,
    and often the real answer to a question the corpus would answer with a
    stale yes. Each active announcement whose subjects match the question
    surfaces alongside the answer through the same signal channel as any other
    incident (ADR-0009): the operator channel leads with it.

    "Active" is `publish_at <= now` and not past an optional `expires`, so a
    future-dated notice stays dark until its day and an expired one drops off on
    its own. Subjects ride on Atom `<category>` terms when the feed carries
    them, and are recovered from the title when it does not.
    """

    name = "uvularia-announcements"

    def __init__(
        self,
        location: str,
        *,
        clock: Callable[[], datetime] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.location = location
        self.timeout = timeout
        # Injectable so a test can fix "now"; called per fetch so a long-lived
        # process sees announcements open and expire as wall-clock advances.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self) -> tuple[tuple[Incident, ...], str | None]:
        try:
            raw = _read_location(self.location, self.timeout)
        except (OSError, urllib.error.URLError) as exc:
            return (), f"{self.name}: unreachable ({exc})"
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            return (), f"{self.name}: unparseable feed ({exc})"

        now = self._clock()
        incidents: list[Incident] = []
        for entry in root.findall(f"{_ATOM}entry"):
            ann = _parse_announcement(entry)
            if ann is None:
                continue
            if ann.publish_at and ann.publish_at > now:
                continue  # not published yet
            if ann.expires and ann.expires <= now:
                continue  # expired
            incidents.append(Incident(
                incident_id=f"announcement:{ann.id}",
                title=ann.title,
                status="announcement",
                subjects=ann.subjects,
                source=self.name,
                detail=ann.summary,
            ))
        return tuple(incidents), None


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
