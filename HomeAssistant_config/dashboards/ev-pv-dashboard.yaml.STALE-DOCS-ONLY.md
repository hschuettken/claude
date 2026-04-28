# ⚠️ This directory was a stale documentation mirror

The live HA at 192.168.0.40 does NOT load dashboards from YAML mode —
it uses storage mode (UI-edited dashboards persisted in
`/mnt/data/supervisor/homeassistant/.storage/lovelace.<id>`).

The `ev-pv-dashboard.yaml` that used to live here was never picked up by
HA. Editing it does nothing.

**To modify the live "⚡ EV & Energy" dashboard:**
1. HA UI → ⚡ EV & Energy → ⋮ → Edit dashboard, OR
2. Push via WebSocket: `lovelace/config/save url_path=ev-energy config=…`
   (see `notes/ha_dashboard_push_recipe.md` if it exists)
3. Or via Proxmox guest exec — see session 2026-04-28 part 3 handoff
   (project_ev_redesign_session_2026-04-28_part3.md)

**The actual EV-redesign cards added 2026-04-28** (S5 narration + journal +
ready-by override) live in HA storage at:
  `/mnt/data/supervisor/homeassistant/.storage/lovelace.ev_energy`

— pushed via `python3 /tmp/push_dashboard.py` reading from a backup of
that file. The new sections that landed in HA:
  - 🧠 Decision Log: narration markdown + latest journal markdown
  - 📅 Charging Plan: Ready By (Override) entities card
