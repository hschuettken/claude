#!/usr/bin/env bash
# setup_influxdb_bucket.sh
# Creates the 'hems' bucket in InfluxDB for energy telemetry.
#
# Usage:
#   INFLUXDB_URL=http://192.168.0.80:8086 \
#   INFLUXDB_TOKEN=<admin-token> \
#   INFLUXDB_ORG=homelab \
#   bash scripts/setup_influxdb_bucket.sh

set -euo pipefail

INFLUXDB_URL="${INFLUXDB_URL:-http://192.168.0.80:8086}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:?INFLUXDB_TOKEN must be set}"
INFLUXDB_ORG="${INFLUXDB_ORG:-homelab}"
BUCKET_NAME="hems"
RETENTION_DAYS="${RETENTION_DAYS:-365}"   # 0 = infinite

echo "→ Creating InfluxDB bucket '${BUCKET_NAME}' in org '${INFLUXDB_ORG}'..."

# Check if bucket already exists
existing=$(curl -sf \
  -H "Authorization: Token ${INFLUXDB_TOKEN}" \
  "${INFLUXDB_URL}/api/v2/buckets?name=${BUCKET_NAME}&org=${INFLUXDB_ORG}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('buckets', [])))")

if [ "${existing}" -gt "0" ]; then
  echo "✓ Bucket '${BUCKET_NAME}' already exists — skipping creation."
  exit 0
fi

# Get org ID
ORG_ID=$(curl -sf \
  -H "Authorization: Token ${INFLUXDB_TOKEN}" \
  "${INFLUXDB_URL}/api/v2/orgs?org=${INFLUXDB_ORG}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['orgs'][0]['id'])")

RETENTION_SECONDS=$(( RETENTION_DAYS * 86400 ))
if [ "${RETENTION_DAYS}" -eq "0" ]; then
  RETENTION_SECONDS=0
fi

# Create bucket
curl -sf -X POST \
  -H "Authorization: Token ${INFLUXDB_TOKEN}" \
  -H "Content-Type: application/json" \
  "${INFLUXDB_URL}/api/v2/buckets" \
  -d "{
    \"orgID\": \"${ORG_ID}\",
    \"name\": \"${BUCKET_NAME}\",
    \"retentionRules\": [
      {
        \"type\": \"expire\",
        \"everySeconds\": ${RETENTION_SECONDS}
      }
    ],
    \"description\": \"HEMS energy telemetry — power draw, EV charging, PV integration\"
  }"

echo ""
echo "✓ Bucket '${BUCKET_NAME}' created successfully."
echo ""
echo "Suggested measurements:"
echo "  - hems_power          (device, power_kw, energy_kwh)"
echo "  - hems_schedule_exec  (device, scheduled_kw, actual_kw, status)"
echo "  - hems_mode_changes   (old_mode, new_mode, actor)"
