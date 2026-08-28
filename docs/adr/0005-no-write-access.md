# ADR-0005: mitchella has no write access to anything

**Status:** accepted · **Date:** 2026-08-27

## Context

Two untrusted inputs meet in this system. Corpus documents are edited by many
people, and questions arrive from anyone who can type in a chat window. Both are
prompt-injection vectors, and injection is not fixable at the prompt layer — the
mitigation is containment, not prevention.

## Decision

mitchella has no tools. It reads a corpus, reads a status feed, and emits text.
When a question needs an action taken, its output is a **ticket draft** that a
human reads and submits.

The Slack frontend deliberately renders that draft without a submit button.
Adding one would add a write path, and that is a different system with a
different review.

## Consequences

- The blast radius of a successful injection is a wrong answer in a chat
  message. That is a one-sentence answer on a security questionnaire.
- The desk cannot resolve anything automatically, which is the accepted cost.
- Live state arrives as a `{"role": "system"}` message rather than text inside a
  user turn. Both have the same caching profile, but the system role cannot be
  forged by someone typing it into Slack.
