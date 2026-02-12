#!/usr/bin/env bash
# Pull latest changes from git, rebuild all services, and start them.
#
# Usage: ./scripts/deploy-pull.sh
#
# Steps:
#   1. Pull latest changes from current branch
#   2. Decrypt .env.enc → .env (if age key is present)
#   3. Rebuild the shared base image
#   4. Rebuild and start all services via docker compose
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# --- Step 1: Pull latest changes ---
echo "==> Pulling latest changes from origin/$BRANCH ..."

MAX_RETRIES=4
DELAY=2
PULLED=false
for i in $(seq 1 $MAX_RETRIES); do
    PULL_OUTPUT=$(git pull --ff-only origin "$BRANCH" 2>&1) && {
        echo "$PULL_OUTPUT"
        PULLED=true
        break
    }
    echo "$PULL_OUTPUT"
    # Only retry on network/transient errors — not on divergent branches
    if echo "$PULL_OUTPUT" | grep -qiE "fatal: not possible to fast-forward|cannot fast-forward|divergent"; then
        echo ""
        echo "ERROR: Local branch has diverged from origin/$BRANCH."
        echo "This deploy script only supports fast-forward pulls."
        echo "Resolve manually: git rebase origin/$BRANCH  OR  git reset --hard origin/$BRANCH"
        exit 1
    fi
    if [ "$i" -lt "$MAX_RETRIES" ]; then
        echo "Pull failed (likely network error), retrying in ${DELAY}s ... (attempt $((i+1))/$MAX_RETRIES)"
        sleep "$DELAY"
        DELAY=$((DELAY * 2))
    fi
done

if [ "$PULLED" = false ]; then
    echo "ERROR: Pull failed after $MAX_RETRIES attempts."
    exit 1
fi
echo ""

# --- Step 2: Decrypt secrets ---
if [ -f "$REPO_ROOT/.sops/age-key.txt" ] && [ -f "$REPO_ROOT/.env.enc" ]; then
    echo "==> Decrypting .env.enc → .env ..."
    export SOPS_AGE_KEY_FILE="$REPO_ROOT/.sops/age-key.txt"
    sops decrypt --input-type dotenv --output-type dotenv "$REPO_ROOT/.env.enc" > "$REPO_ROOT/.env"
    echo "Decrypted successfully."
else
    if [ ! -f "$REPO_ROOT/.env" ]; then
        echo "WARNING: No age key or .env.enc found, and no .env exists."
        echo "Services will fail without a .env file."
        echo "Run: ./scripts/secrets-decrypt.sh"
        exit 1
    fi
    echo "==> Skipping decryption (.env already exists, no age key found)."
fi
echo ""

# --- Step 3: Rebuild base image ---
echo "==> Rebuilding base image ..."
./scripts/build-base.sh
echo ""

# --- Step 4: Rebuild and start all services (except example-service) ---
echo "==> Rebuilding and starting all services ..."
SERVICES=$(docker compose config --services | grep -v '^example-service$')
docker compose up --build -d $SERVICES
echo ""

echo "Done. All services are starting."
echo "Use 'docker compose logs -f' to follow logs."
echo "Use 'docker ps' to check health status."
