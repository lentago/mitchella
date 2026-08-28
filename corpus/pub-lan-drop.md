---
id: pub-lan-drop
title: Sharing a file on the LAN (pub.lan)
tags: [pub.lan, sharing, caddy, nas]
volatility: stable
---

Anything that should open in a browser goes in the LAN web drop folder and
serves immediately — there is no deploy step.

- **Write to** `/mnt/lentago/web/<thing>/index.html` from this workstation.
  Fleet and PVE hosts see the same folder at `/mnt/neptune-lentago/web/`.
- **It serves at** `http://pub.lan/<thing>/`.

Give each artifact its own subfolder so the directory index stays readable.

`pub.lan` is LXC 114 on pve4, running Caddy with directory browsing over the
NAS share. It is LAN-readable with an open index, so never drop credentials,
keys, or private financial or medical data there. Throwaway files that nobody
needs to open belong in a scratch directory instead.
