#!/usr/bin/env bash
# Encrypt secrets, commit all changes, and push to git.
#
# Usage: ./scripts/deploy-push.sh [commit message]
#        ./scripts/deploy-push.sh -y [commit message]   # skip confirmation
#
# Steps:
#   1. Encrypt .env → .env.enc (via secrets-encrypt.sh)
#   2. Stage tracked file changes + .env.enc (does NOT add unknown new files)
#   3. Show what will be committed and ask for confirmation
#   4. Commit with the provided message (or a default)
#   5. Push to the current branch
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Parse flags
AUTO_CONFIRM=false
if [ "${1:-}" = "-y" ]; then
    AUTO_CONFIRM=true
    shift
fi

# --- Step 1: Encrypt secrets ---
echo "==> Encrypting .env → .env.enc ..."
./scripts/secrets-encrypt.sh
echo ""

# --- Step 2: Stage changes ---
# Stage only already-tracked files (updates + deletes) — safe, never picks up
# random new files like credentials/ or nested git repos.
echo "==> Staging changes ..."
git add -u
# Always include the encrypted secrets file
git add .env.enc

# Show untracked files the user might want to add
UNTRACKED="$(git ls-files --others --exclude-standard)"
if [ -n "$UNTRACKED" ]; then
    echo ""
    echo "Untracked files (not staged — use 'git add' manually if needed):"
    echo "$UNTRACKED" | sed 's/^/  /'
    echo ""
fi

# Check if there is anything to commit
if git diff --cached --quiet; then
    echo "Nothing to commit — working tree is clean."
    exit 0
fi

echo "Staged changes:"
git --no-pager diff --cached --stat
echo ""

# --- Step 3: Confirm ---
if [ "$AUTO_CONFIRM" = false ]; then
    read -r -p "Commit and push these changes? [y/N] " answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        echo "Aborted. Changes are still staged."
        exit 0
    fi
fi

# --- Step 4: Commit ---
COMMIT_MSG="${1:-Deploy: update config and encrypted secrets}"
echo "==> Committing: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"
echo ""

# --- Step 5: Push ---
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
