#!/usr/bin/env bash
# Encrypt secrets, commit all changes, and push to git.
#
# Usage: ./scripts/deploy-push.sh [commit message]
#
# Steps:
#   1. Encrypt .env → .env.enc (via secrets-encrypt.sh)
#   2. Stage all tracked changes (modified + untracked, respecting .gitignore)
#   3. Commit with the provided message (or a default)
#   4. Push to the current branch
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# --- Step 1: Encrypt secrets ---
echo "==> Encrypting .env → .env.enc ..."
./scripts/secrets-encrypt.sh
echo ""

# --- Step 2: Stage all changes ---
echo "==> Staging all changes ..."
git add -A

# Check if there is anything to commit
if git diff --cached --quiet; then
    echo "Nothing to commit — working tree is clean."
    exit 0
fi

echo "Staged changes:"
git --no-pager diff --cached --stat
echo ""

# --- Step 3: Commit ---
COMMIT_MSG="${1:-Deploy: update config and encrypted secrets}"
echo "==> Committing: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"
echo ""

# --- Step 4: Push ---
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Pushing to origin/$BRANCH ..."

MAX_RETRIES=4
DELAY=2
for i in $(seq 1 $MAX_RETRIES); do
    if git push -u origin "$BRANCH"; then
        echo ""
        echo "Done. All changes pushed to origin/$BRANCH."
        exit 0
    fi
    if [ "$i" -lt "$MAX_RETRIES" ]; then
        echo "Push failed, retrying in ${DELAY}s ... (attempt $((i+1))/$MAX_RETRIES)"
        sleep "$DELAY"
        DELAY=$((DELAY * 2))
    fi
done

echo "ERROR: Push failed after $MAX_RETRIES attempts."
exit 1
