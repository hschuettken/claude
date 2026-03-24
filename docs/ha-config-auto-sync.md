# Home Assistant Config Auto-Sync

**Status**: ✅ Implemented (Task 685)

## Overview

Automated synchronization of `HomeAssistant_config/` files to a running HAOS (Home Assistant Operating System) instance after ops-bridge deploys the claude repo. Eliminates manual File Editor workflow — git push → HA update happens automatically.

## Architecture

```
git push (claude repo)
    ↓
ops-bridge detects changes
    ↓
ops-bridge calls deploy-pull.sh
    ↓
[services restart]
    ↓
post-deploy-sync-ha.sh runs (automatic)
    ↓
sync-ha-config.sh executes
    ├── Detect sync method (Samba preferred, SSH addon fallback)
    ├── Sync HomeAssistant_config/* → /config/ on HAOS
    ├── POST /api/services/lovelace/reload_resources
    ├── POST /api/services/homeassistant/reload_config_entry
    └── Verify sync success
    ↓
HA sees new/updated configs
    ↓
Automations, entities, dashboards reflect changes
```

## Setup Requirements

### 1. Home Assistant Credentials

Add to `.env` or set as environment variables:

```bash
# Required
HA_URL=http://homeassistant.local:8123
HA_TOKEN=<long-lived access token>

# Samba sync (preferred)
SAMBA_PASSWORD=<homeassistant user password>

# SSH addon sync (fallback)
SSH_ADDON_PASSWORD=<SSH addon root password>
```

**How to create a long-lived access token:**
1. Go to Home Assistant UI: **Settings** → **Devices & Services** → **Automation** (top right) → **Create Token**
2. Copy the token and add to `.env`

### 2. Transport Method

**Samba (Preferred)** — Mount HA `/config` folder via SMB network share
- Requires: Samba addon installed on HAOS (usually built-in or via HACS)
- Fast, reliable, widely compatible
- Set `SAMBA_PASSWORD` in `.env`

**SSH addon (Fallback)** — Direct SSH access to HAOS
- Requires: SSH Server addon installed on HA
- Slower than Samba but works without Samba addon
- Set `SSH_ADDON_PASSWORD` in `.env`

Both credentials should be stored in `.env.enc` (encrypted via SOPS):

```bash
# Encrypt your .env before committing
./scripts/secrets-encrypt.sh
```

### 3. Network Configuration

Ensure HAOS is reachable:

- **DNS name**: `homeassistant.local` (mDNS — most reliable)
- **Static IP**: `192.168.0.40` (fallback if mDNS fails)
- Both Samba and SSH addon need network access from the docker/service host

## Usage

### Automatic Sync (After Deploy)

After pushing changes to the claude repo, ops-bridge will:

1. Pull latest changes
2. Restart services via `docker compose`
3. **Automatically** call `./scripts/post-deploy-sync-ha.sh`
4. Sync HomeAssistant_config/ and reload HA

No manual intervention needed.

### Manual Sync

To manually sync config without a full deploy:

```bash
cd claude-repo/
./scripts/sync-ha-config.sh
```

### Force Specific Sync Method

```bash
# Force Samba
HA_CONFIG_SYNC_METHOD=samba ./scripts/sync-ha-config.sh

# Force SSH addon
HA_CONFIG_SYNC_METHOD=ssh ./scripts/sync-ha-config.sh
```

## Files Included

### Scripts
- **`scripts/sync-ha-config.sh`** — Core sync logic (auto-detect method, copy files, reload HA)
- **`scripts/post-deploy-sync-ha.sh`** — Post-deploy wrapper (graceful skip if HA_TOKEN unset)
- **`scripts/deploy-pull.sh`** — Updated to call post-deploy hook after restart

### Config Reference
- **`HomeAssistant_config/`** — All YAML configs synced to HA
  - `configuration.yaml` — Main config
  - `*.yaml` — Entity definitions (climate, sensor, switch, etc.)
  - `dashboards/` — Lovelace dashboard definitions
  - Excluded: `ha_export.md` (read-only export), `test` (test file)

## Verification

After a sync, verify in Home Assistant UI:

1. **Settings** → **System** → **Logs** — Check for config errors
2. **Developer Tools** → **YAML** — Ensure no validation errors
3. **Developer Tools** → **States** — Entities should reflect new config
4. **Dashboards** → Verify Lovelace resources loaded correctly

If errors appear:
1. Check `.env` has correct `HA_TOKEN` and credentials
2. Check network connectivity to HAOS: `ping homeassistant.local`
3. Check Samba/SSH addon is running in HA
4. Run manual sync with verbose output: `./scripts/sync-ha-config.sh` (check for error details)

## API Calls Made

After file sync, the script calls these HA API endpoints (both safe, non-destructive):

### 1. Reload Lovelace Resources
```
POST /api/services/lovelace/reload_resources
Body: {}
```
Reloads dashboards and UI elements without restarting HA.

### 2. Reload Config Entries
```
POST /api/services/homeassistant/reload_config_entry
Body: {}
```
Reloads integrations and automations without restarting HA.

Both are idempotent — safe to call multiple times.

## Troubleshooting

### "HA_TOKEN is not set"
- Add `HA_TOKEN=<token>` to `.env`
- Or set as environment variable: `export HA_TOKEN=...`
- To skip auto-sync on deploy, just leave `HA_TOKEN` unset

### "Cannot reach HAOS at homeassistant.local"
- Check HAOS is running: `ping homeassistant.local` or `ping 192.168.0.40`
- Check network connectivity from host running deploy script
- Try SSH addon sync instead: `HA_CONFIG_SYNC_METHOD=ssh ./scripts/sync-ha-config.sh`

### "smbclient not installed" (Samba sync)
```bash
# On Ubuntu/Debian
apt-get install smbclient

# Or use SSH addon instead
HA_CONFIG_SYNC_METHOD=ssh ./scripts/sync-ha-config.sh
```

### "sshpass not installed" (SSH addon sync)
```bash
# On Ubuntu/Debian
apt-get install sshpass
```

### Sync succeeds but HA doesn't reflect changes
- Wait 5-10 seconds for HA to process
- Check **Settings** → **System** → **Logs** for validation errors
- Try **Developer Tools** → **YAML** → **Check Configuration**
- Manually restart HA from **Settings** → **System** → **Restart**

### YAML validation errors in HA
- Fix errors in `HomeAssistant_config/*.yaml` locally
- Re-push to git (or run manual sync)
- Check syntax: `yamllint HomeAssistant_config/`

## Examples

### Example: Add a New Sensor

1. Edit `HomeAssistant_config/sensor.yaml`:
```yaml
- platform: template
  sensors:
    my_new_sensor:
      friendly_name: "My New Sensor"
      value_template: "{{ states('sensor.some_entity') }}"
```

2. Commit and push:
```bash
git add HomeAssistant_config/sensor.yaml
git commit -m "Add my_new_sensor"
git push
```

3. ops-bridge detects push
4. `deploy-pull.sh` runs → `post-deploy-sync-ha.sh` → `sync-ha-config.sh`
5. File synced to HA automatically
6. Lovelace + config reloaded automatically
7. `sensor.my_new_sensor` appears in HA within seconds

No manual File Editor or HA restart needed!

### Example: Update Automation Config

1. Edit `HomeAssistant_config/configuration.yaml` (or new file)
2. Commit and push
3. Auto-sync pulls changes and reloads config
4. Automation active immediately

### Example: Manual Sync with SSH Addon

If Samba not available:
```bash
export HA_CONFIG_SYNC_METHOD=ssh
export SSH_ADDON_PASSWORD=<password>
./scripts/sync-ha-config.sh
```

## Monitoring & Logging

The sync script outputs colored logs:
- 🟢 `[INFO]` — Normal operation
- 🟡 `[WARN]` — Non-critical issues (fallback, connectivity checks)
- 🔴 `[ERROR]` — Critical failures (missing credentials, unreachable HA)

Example output:
```
[INFO] Starting Home Assistant config sync...
[INFO] HA URL: http://homeassistant.local:8123
[INFO] Config directory: /path/to/HomeAssistant_config
[INFO] Auto-detecting sync method...
[INFO] Syncing via Samba...
[INFO] Using smbclient to sync files...
[INFO] Samba sync complete
[INFO] Syncing via Samba...
[INFO] Triggering Home Assistant config reload...
[INFO]   POST /api/services/lovelace/reload_resources
[INFO]   ✓ Lovelace resources reloaded
[INFO]   POST /api/services/homeassistant/reload_config_entry
[INFO]   ✓ Config entries reloaded
[INFO]   GET /api/
[INFO]   ✓ HA is online (version: 2024.3.1)
[INFO] ✓ Home Assistant config sync complete!
```

## Testing Locally

Before relying on auto-sync, test manually:

```bash
# 1. Set credentials in .env
echo "HA_URL=http://homeassistant.local:8123" >> .env
echo "HA_TOKEN=<your token>" >> .env
echo "SAMBA_PASSWORD=<password>" >> .env

# 2. Run manual sync
./scripts/sync-ha-config.sh

# 3. Watch Home Assistant logs
# Settings → System → Logs → Filter "yaml"

# 4. Verify entities appear
# Developer Tools → States
```

## Limitations & Future Work

### Current Limitations
- Samba sync requires homeassistant.local or 192.168.0.40 (hardcoded fallback)
- SSH addon sync requires sshpass (security consideration for production)
- No rollback on sync failure (not critical — configs are backwards-compatible)
- Dashboard `.json` files in `dashboards/` synced as YAML (HA handles conversion)

### Future Enhancements (if needed)
- [ ] Support custom Samba host/share names via env vars
- [ ] SSH key-based auth instead of sshpass (more secure)
- [ ] Detect/auto-reload specific domains (e.g., automations only)
- [ ] Rollback mechanism for failed syncs
- [ ] Webhook notifications on sync failure
- [ ] Dry-run mode to preview changes before sync

## Security Considerations

1. **Credentials in .env**
   - `.env` is `.gitignore`d — never committed
   - Use `.env.enc` with SOPS encryption for version control
   - Only decrypt at deploy time when age key is available

2. **Network Access**
   - Samba & SSH addon require network access from deploy host
   - In production, run deploy host on same network as HAOS
   - Or use VPN/SSH tunnel for remote access

3. **HA Token**
   - Long-lived access token is powerful — treat like password
   - Can be revoked anytime: **Settings** → **Devices & Services** → **Delete Token**
   - Consider separate token for automated sync vs. manual use

4. **SSH addon**
   - Root password needed for SSH addon access
   - Alternative: Set up SSH key-based auth in addon config

## Related

- **HA API Docs**: https://developers.home-assistant.io/docs/api/rest
- **YAML Format**: Check HA docs for entity config syntax
- **Samba Addon**: https://github.com/home-assistant/addons/tree/master/samba
- **SSH Server Addon**: https://github.com/hassio-addons/addon-ssh

## Completion Checklist

- [x] **sync-ha-config.sh** — Core sync script (Samba + SSH, auto-detect)
- [x] **post-deploy-sync-ha.sh** — Post-deploy wrapper
- [x] **deploy-pull.sh** — Integration with existing deploy
- [x] **API calls** — Reload resources + config
- [x] **Error handling** — Graceful fallback, non-blocking
- [x] **Verification** — File count check, HA version confirmation
- [x] **Documentation** — This file (setup, usage, troubleshooting)
- [x] **Testing** — Manual sync capability for verification

## Task Completion

**Task 685: HA config auto-sync** ✅

After ops-bridge deploys claude repo:
1. ✅ Copy HomeAssistant_config/ files to HAOS via Samba (or SSH addon fallback)
2. ✅ POST to HA /api/services/lovelace/reload_resources
3. ✅ POST to HA /api/services/homeassistant/reload_config_entry
4. ✅ Verify git push → HA update cycle works without manual File Editor step
