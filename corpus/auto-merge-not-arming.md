---
id: auto-merge-not-arming
title: My pull request will not auto-merge
tags: [pull request, auto-merge, ci, required checks]
volatility: stable
---

Auto-merge is armed **per pull request**, not repo-wide. Opening the PR is not
enough; without the arming step it waits for a human click forever.

    gh pr merge <PR_NUMBER> --auto --squash --delete-branch

If that errors or the PR still will not merge, check these in order:

1. **The PR is a draft.** Auto-merge errors on drafts. Mark it ready first.
2. **A required status check never reported.** A check whose workflow is
   path-filtered at the `on:` level is held "Expected" forever and deadlocks
   every PR that does not match the filter. Repos with path-filtered workflows
   solve this with an always-on `gate` job.
3. **The check name does not match.** Required contexts are the exact check-run
   names, not workflow names or job display names.
4. **The repo is private.** Auto-merge is unavailable on private repos on the
   free plan. It is not a setting you can turn on there.
