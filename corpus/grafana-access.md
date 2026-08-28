---
id: grafana-access
title: I cannot reach Grafana / the dashboards
tags: [grafana, access, dashboards, login]
volatility: live
---

The stack is at `lentago.grafana.net`. The older `pitzilabs.grafana.net`
hostname is dead and returns a 530 — if a bookmark, script, or secret still
points there, that is the fault.

Before troubleshooting access, confirm whether Grafana Cloud itself is
reporting a problem: a login failure during a provider incident looks exactly
like a credential problem and is not one.

Dashboards are Terraform-managed from `drosera` and reapplied on every merge to
main. If a dashboard is missing rather than unreachable, see
[enforced-surfaces] before assuming it was deleted.
