---
id: enforced-surfaces
title: My change disappeared / why live edits get reverted
tags: [terraform, gitops, grafana, dashboard, drift]
volatility: stable
---

Several systems continuously enforce their state from git through a CI apply
job. On those surfaces, whatever is on `main` **is** the live state, and the
apply can be triggered by a completely unrelated merge. A live-only edit
survives exactly until the next apply.

Enforced surfaces and who owns them:

| Live surface | Owning repo |
|---|---|
| Grafana Cloud dashboards | `drosera` — applies on every merge to main |
| Route 53 / `lentago.dev` DNS | `solidago` Terraform |
| GitHub repo settings, rulesets, labels, and repo existence | `.github` meta-repo |
| Central Alloy config | `drosera` — pulled every 5 minutes |
| Proxmox guests | `kalmia` (and `claytonia` for the runner pool) |

If you changed one of these through a UI or an API and the change vanished,
that is the apply job, working as designed. Recover it and put it in a pull
request rather than reapplying it live.

**If live state is ahead of the repo, treat it as urgent.** Un-codified work is
one unrelated merge away from being destroyed. Most of these systems keep a
recovery trail — Grafana dashboard version history, the Route 53 change log,
the ruleset audit log — so check there before concluding anything is lost.
