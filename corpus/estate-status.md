---
id: estate-status
title: Is something down right now?
tags: [status, outage, incident, grafana, availability]
volatility: live
---

Current state is **never** answered from this corpus. Check the live sources:

- **The estate status page** — site availability against the 99.9% / 30-day
  SLO with error budget remaining, plus the latest `main`-branch CI conclusion
  per repo. Rebuilt on a schedule from Grafana Cloud Mimir and the GitHub API.
- **The public incident register** — `fleet-reports/incidents.md` in the
  `.github` repo.
- **Grafana Cloud** for the live dashboards behind both.

The status page degrades honestly: if a query fails or a series is missing, the
affected item renders an explicit "no data" rather than a green one. A missing
signal means unknown, never healthy — and the same rule applies to any answer
given here.
