# ADR-0002: The whole corpus goes in the prompt; there is no vector store

**Status:** accepted · **Date:** 2026-08-27

## Context

"Corpus-backed chatbot" is near-synonymous with "vector database" by reflex.
That reflex is worth resisting until the numbers require it. This corpus is a
few dozen short operational documents. Rendered, it is under 2,000 tokens
today, against a 1M-token context window.

A retrieval layer at this size buys nothing and costs a great deal: a chunking
strategy, an embedding provider and its own vendor decision, an index to keep in
sync with git, and — most expensively — an entire category of failure that does
not otherwise exist. "Why did it retrieve the wrong document?" is a class of bug
you can only have if you are retrieving.

## Decision

Load every corpus document into one deterministic block, place it in the system
prompt behind a single cache breakpoint, and let the model see all of it on
every request.

This makes prefix stability the governing constraint. The corpus may change on
merge and at no other time, and nothing per-request — no clock, no username, no
incident list — renders into the system prompt. `test_engine.py` asserts the
prefix is byte-identical across turns, which is what keeps the cache honest
after someone forgets this in six months.

## Consequences

- **Cost.** Cache reads are roughly a tenth of base input price. The prefix is
  written once per TTL window and read thereafter.
- **No retrieval bugs**, because there is no retrieval.
- **A ceiling.** `Corpus.is_outgrowing_prefix` flags when the rendered corpus
  passes a soft ceiling. Crossing it is the trigger to revisit this ADR — and
  the next step is keyword search with reranking, not embeddings. Embeddings are
  the third step, not the second.
- Every document is in context for every question, so a badly written entry can
  mislead an answer it was never meant to touch. Corpus review matters more here
  than it would behind a retriever.
