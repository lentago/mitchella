---
id: bullpen-dispatch
title: Dispatching a job to the agent fleet
tags: [claytonia, bullpen, jobs, queue]
volatility: stable
---

The queue is a filesystem. Dispatch by dropping a JSON spec into the inbox on
the NAS share — no SSH needed.

Write `<name>.json.partial` first, then rename it to `<name>.json`. The poller
ignores `*.partial` and `*.tmp`, so the rename is what makes the claim atomic.

    /mnt/lentago/claude-jobs/inbox/<name>.json

    {"prompt": "work issue #42: ...", "project": "solidago", "model": "sonnet"}

Every key except `prompt` is optional. The poller picks it up within 15
seconds. Workers see the same directory as `/srv/jobs`.

**Pick the model to fit the job:** `haiku` for typo, doc, and mechanical edits;
`sonnet` for most feature work (the default); `opus` for architectural or
multi-file work that needs real reasoning.

Answers land in `/mnt/lentago/claude-jobs/logs/<runid>.txt`. The worker opens a
pull request and **never merges** — merging is always a human's call.
