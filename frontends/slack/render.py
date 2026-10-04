"""Slack block rendering.

Separated from `app.py` so it can be tested without `slack_bolt`, tokens, or a
workspace. This module is the whole of mitchella's Slack-specific knowledge;
`app.py` is only transport.

Slack rejects a whole message (not just the offending block) when a section's
text passes 3000 characters or a message carries more than 50 blocks. A long
model answer must therefore be split here, because the failure otherwise shows
up as an answer that silently never arrives.
"""

from __future__ import annotations

from mitchella import Answer, AnswerKind

_HEADER = {
    AnswerKind.ANSWERED: None,
    AnswerKind.INCIDENT: ":warning: *This looks like a live incident.*",
    AnswerKind.ESCALATED: ":inbox_tray: *I can't answer this one — here's a ticket draft.*",
    AnswerKind.DECLINED: None,
}


#: Slack's hard limit is 3000 characters per section/context text; the margin
#: leaves room for the code fences wrapped around a ticket body chunk.
SECTION_LIMIT = 2900
#: Slack's hard limit is 50 blocks per message.
MAX_BLOCKS = 50
TRUNCATION_MARKER = "_…(truncated: the rest of this reply was too long for Slack)_"


def chunk_text(text: str, limit: int = SECTION_LIMIT) -> list[str]:
    """Split `text` into pieces of at most `limit` characters, preferring to
    break at a paragraph, then a line, then a space, and only then mid-word."""
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < limit // 2:  # no sensible boundary; a hard cut beats a tiny chunk
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
    if rest.strip() or not chunks:
        chunks.append(rest)
    return chunks


def _clip(text: str, limit: int = SECTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    keep = limit - len(TRUNCATION_MARKER) - 1
    return text[:keep] + "\n" + TRUNCATION_MARKER


def _sections(text: str, fmt: str = "{}") -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": fmt.format(c)}}
            for c in chunk_text(text)]


def to_blocks(answer: Answer) -> list[dict]:
    blocks: list[dict] = []

    header = _HEADER[answer.kind]
    if header:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header}})

    blocks += _sections(answer.text or "_(no reply)_")

    if answer.incidents:
        lines = "\n".join(
            f"• *{i.title}* — {i.status} _(via {i.source})_" + (f"\n  <{i.url}|more>" if i.url else "")
            for i in answer.incidents
        )
        blocks += _sections(lines)

    if answer.ticket_draft:
        d = answer.ticket_draft
        blocks.append({"type": "divider"})
        blocks += _sections(f"*{d.title}*  `{d.category}`")
        blocks += _sections(d.body or " ", "```{}```")
        # Deliberately not a "Submit" button. mitchella has no write access to
        # any system (ADR-0005); a human copies this into the tracker. A button
        # here would be a write path, and that is a different design.
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": "_Draft only — mitchella cannot file tickets._"}]})

    # The footer is held apart so the block cap can never trim it: a degraded
    # signal that falls off the end would read as healthy.
    body, blocks = blocks, []

    if answer.sources:
        cited = "  ".join(f"`{s.doc_id}`" for s in answer.sources)
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": _clip(f"sources: {cited}")}]})

    if answer.degraded_signals:
        detail = "; ".join(answer.degraded_signals)
        blocks.append({"type": "context", "elements": [{
            "type": "mrkdwn",
            # Never fake green: an unreachable signal makes the answer more
            # cautious, and the reader is told why.
            "text": _clip(f":grey_question: _Couldn't confirm current state ({detail}). "
                          "Treat as unknown, not healthy._"),
        }]})

    footer = blocks
    room = MAX_BLOCKS - len(footer)
    if len(body) > room:
        body = body[:room - 1] + [{"type": "section",
                                   "text": {"type": "mrkdwn", "text": TRUNCATION_MARKER}}]
    return body + footer
