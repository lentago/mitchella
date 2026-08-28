---
id: lxc-static-ip
title: Pinning a new LXC or VM to a fixed IP
tags: [firewalla, dhcp, reservation, lxc, ip]
volatility: stable
---

DHCP reservations on the Firewalla must be written in **two** places or they
silently revert: the per-MAC `hosts2` file **and** the redis `ipAllocation`
policy. Setting only one looks like it worked and then drifts back.

The full recipe is in the `firewalla-dhcp-reservation` runbook. Do not
hand-edit one location and assume it held — verify the lease after a renew.

Related: LAN DNS lookups on this network hit the Firewalla's cache even when
you explicitly query an external resolver, so `dig @8.8.8.8` does not prove
what public DNS returns. Verify real DNS over DoH, and flush the local cache
with a `SIGHUP` to dnsmasq on the Firewalla.
