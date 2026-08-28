---
id: logs-where
title: Where do logs go, and where do I look?
tags: [betula, drosera, loki, grafana, logs, observability]
volatility: stable
---

Two products, one boundary, and neither grows into the other's role.

- **betula** owns **capture and archive**: per-source collectors that ship
  full-volume logs off each device. The Firewalla client ships DNS, connection
  flow, and TLS handshake logs to Grafana Cloud Loki. The AWS client ships to
  Axiom. Destination is a per-client decision recorded in that client's ADR.
- **drosera** owns the **live pane**: the Grafana dashboards, the alerts, and
  the estate status page.

So: **searching history is betula's output in Loki; asking "is it broken right
now" is drosera.** If you are reaching for a log search to answer a
current-state question, you probably want a dashboard or the status page.

Dashboards are Terraform-managed and reapplied on every merge — see
[enforced-surfaces].
