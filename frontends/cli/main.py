"""CLI frontend — the second client, and the one that keeps the boundary honest.

A boundary with one implementation behind it is a boundary nobody has tested.
This exists so that "mitchella supports multiple UIs" is a fact rather than an
intention, and it doubles as the local development harness: no Slack workspace,
no tokens, no tunnel.

Note what this file imports: `mitchella` and nothing deeper. Adding a frontend
must not require editing a single file outside its own directory.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from mitchella import (
    AnswerKind, Config, DroseraStatusProvider, Engine, ManualOverrideProvider,
    Query, SignalPlane, TurnLog, load_corpus, opaque_ref,
)

_ICON = {
    AnswerKind.ANSWERED: "✓",
    AnswerKind.INCIDENT: "▲",
    AnswerKind.ESCALATED: "→",
    AnswerKind.DECLINED: "·",
}


def build_engine(config: Config) -> Engine:
    corpus = load_corpus(config.corpus_dir)
    providers = [ManualOverrideProvider(config.incidents_file)]
    if config.drosera_status:
        providers.append(DroseraStatusProvider(config.drosera_status))
    return Engine(
        corpus=corpus,
        signal_plane=SignalPlane(providers),
        config=config,
        turnlog=TurnLog(config.turnlog_path),
    )


def render(answer, *, show_usage: bool) -> str:
    out = [f"{_ICON[answer.kind]} [{answer.kind.value}] {answer.text}"]

    if answer.incidents:
        out.append("\n  open incidents:")
        out += [f"    - {i.title} ({i.status}, via {i.source})" for i in answer.incidents]

    if answer.sources:
        out.append("\n  sources:")
        out += [f"    - {s.doc_id}  {s.path}" for s in answer.sources]

    if answer.ticket_draft:
        d = answer.ticket_draft
        out.append(f"\n  ticket draft [{d.category}] — not submitted; a human sends this")
        out.append(f"    {d.title}")
        out.append("\n".join(f"    | {ln}" for ln in d.body.splitlines()))

    if answer.degraded_signals:
        out.append("\n  ⚠ could not read some live signals — treat as unknown, not healthy:")
        out += [f"    - {d}" for d in answer.degraded_signals]

    if show_usage:
        u = answer.usage
        out.append(
            f"\n  usage: in={u.input_tokens} out={u.output_tokens} "
            f"cache_read={u.cache_read_input_tokens} "
            f"cache_write={u.cache_creation_input_tokens} "
            f"({u.cached_fraction:.0%} of input served from cache) "
            f"corpus={answer.corpus_fingerprint}"
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mitchella",
        description="Ask the estate front desk a question.",
    )
    parser.add_argument("question", nargs="*", help="the question; omit for an interactive loop")
    parser.add_argument("--usage", action="store_true", help="show token and cache accounting")
    parser.add_argument("--corpus-info", action="store_true", help="print corpus stats and exit")
    args = parser.parse_args(argv)

    config = Config.from_env()

    if args.corpus_info:
        corpus = load_corpus(config.corpus_dir)
        print(f"entries:     {len(corpus.entries)}")
        print(f"fingerprint: {corpus.fingerprint}")
        print(f"~tokens:     {corpus.estimated_tokens:,}")
        if corpus.is_outgrowing_prefix:
            print("NOTE: corpus is past the soft ceiling — time to revisit ADR-0002.")
        return 0

    engine = build_engine(config)
    user_ref = opaque_ref(getpass.getuser())

    def ask(text: str) -> None:
        answer = engine.answer(Query(text=text, surface="cli", user_ref=user_ref))
        print(render(answer, show_usage=args.usage))

    if args.question:
        ask(" ".join(args.question))
        return 0

    print("mitchella — ask a question, or Ctrl-D to leave.")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text:
            ask(text)


if __name__ == "__main__":
    sys.exit(main())
