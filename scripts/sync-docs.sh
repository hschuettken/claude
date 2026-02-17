#!/usr/bin/env bash
# Sync documentation from docs/ to all configured repositories.
#
# Usage:
#   ./scripts/sync-docs.sh                  # Sync all repos from SYNC_REPOS
#   ./scripts/sync-docs.sh repo-a           # Sync only a specific repo (short name)
#   ./scripts/sync-docs.sh myuser/repo-a    # Sync only a specific repo (full name)
#   SYNC_REPOS=a,b ./scripts/sync-docs.sh   # Override repos via env var
#
# Configuration (in .env or environment):
#   SYNC_REPOS          — Comma-separated list of repos (owner/repo format)
#   SYNC_DOCS_BRANCH    — Target branch in destination repos (default: main)
#   SYNC_CLONE_DIR      — Temp directory for cloning (default: /tmp/docs-sync)
#
# What it does:
#   1. Reads the list of repos from SYNC_REPOS (in .env or env var)
#   2. For each destination repo:
#      a. Clones (or pulls) the repo into SYNC_CLONE_DIR
#      b. Copies docs/ from THIS repo into the destination repo's docs/
#      c. Copies docs/ from the destination repo back into THIS repo's docs/
#      d. Commits and pushes changes in the destination repo
#   3. After all repos are synced, commits any new docs pulled into THIS repo
#
# Each repo owns its own docs/<repo-name>/ subfolder. The sync script never
# overwrites one repo's docs with another's — it merges by directory.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ─── Load .env if present ───────────────────────────────────────────────
if [ -f "$REPO_ROOT/.env" ]; then
    # Source only the variables we need (avoid polluting the env)
    SYNC_REPOS="${SYNC_REPOS:-$(grep -E '^SYNC_REPOS=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)}"
    SYNC_DOCS_BRANCH="${SYNC_DOCS_BRANCH:-$(grep -E '^SYNC_DOCS_BRANCH=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)}"
    SYNC_CLONE_DIR="${SYNC_CLONE_DIR:-$(grep -E '^SYNC_CLONE_DIR=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)}"
fi

SYNC_DOCS_BRANCH="${SYNC_DOCS_BRANCH:-main}"
SYNC_CLONE_DIR="${SYNC_CLONE_DIR:-/tmp/docs-sync}"
THIS_REPO_NAME="$(basename "$REPO_ROOT")"
FILTER_REPO="${1:-}"

# ─── Validate ────────────────────────────────────────────────────────────
if [ -z "${SYNC_REPOS:-}" ]; then
    echo "ERROR: SYNC_REPOS is not set."
    echo ""
    echo "Set it in .env or as an environment variable:"
    echo '  SYNC_REPOS=myuser/repo-a,myuser/repo-b'
    echo ""
    echo "Or pass repos via environment:"
    echo '  SYNC_REPOS=myuser/repo-a ./scripts/sync-docs.sh'
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "ERROR: git is not installed."
    exit 1
fi

# Check if gh CLI is available (used for cloning)
USE_GH=false
if command -v gh &> /dev/null; then
    USE_GH=true
fi

# ─── Parse repo list ─────────────────────────────────────────────────────
IFS=',' read -ra REPOS <<< "$SYNC_REPOS"

echo "╔══════════════════════════════════════════════════════╗"
echo "║           Documentation Sync                        ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Source repo:  $THIS_REPO_NAME"
echo "║  Docs dir:     docs/"
echo "║  Target branch: $SYNC_DOCS_BRANCH"
echo "║  Clone dir:    $SYNC_CLONE_DIR"
echo "║  Repos:        ${#REPOS[@]} configured"
if [ -n "$FILTER_REPO" ]; then
    echo "║  Filter:       $FILTER_REPO"
fi
echo "╚══════════════════════════════════════════════════════╝"
echo ""

mkdir -p "$SYNC_CLONE_DIR"

SYNCED=0
FAILED=0
SKIPPED=0
PULLED_NEW_DOCS=false

# ─── Helper: clone or pull a repo ────────────────────────────────────────
clone_or_pull() {
    local full_repo="$1"
    local repo_name="$2"
    local target_dir="$SYNC_CLONE_DIR/$repo_name"

    if [ -d "$target_dir/.git" ]; then
        echo "  Pulling latest changes..."
        cd "$target_dir"
        git fetch origin "$SYNC_DOCS_BRANCH" 2>/dev/null || true
        git checkout "$SYNC_DOCS_BRANCH" 2>/dev/null || git checkout -b "$SYNC_DOCS_BRANCH" "origin/$SYNC_DOCS_BRANCH" 2>/dev/null || true
        git pull --ff-only origin "$SYNC_DOCS_BRANCH" 2>/dev/null || {
            echo "  WARNING: Could not fast-forward pull. Resetting to origin/$SYNC_DOCS_BRANCH."
            git reset --hard "origin/$SYNC_DOCS_BRANCH"
        }
        cd "$REPO_ROOT"
    else
        echo "  Cloning $full_repo..."
        if [ "$USE_GH" = true ]; then
            gh repo clone "$full_repo" "$target_dir" -- --branch "$SYNC_DOCS_BRANCH" 2>/dev/null || \
            gh repo clone "$full_repo" "$target_dir" 2>/dev/null || {
                echo "  ERROR: Failed to clone $full_repo"
                return 1
            }
        else
            git clone "git@github.com:$full_repo.git" "$target_dir" --branch "$SYNC_DOCS_BRANCH" 2>/dev/null || \
            git clone "git@github.com:$full_repo.git" "$target_dir" 2>/dev/null || {
                echo "  ERROR: Failed to clone $full_repo"
                return 1
            }
        fi
    fi
    return 0
}

# ─── Helper: push with retry ─────────────────────────────────────────────
push_with_retry() {
    local branch="$1"
    local max_retries=4
    local delay=2

    for i in $(seq 1 $max_retries); do
        if git push -u origin "$branch" 2>/dev/null; then
            return 0
        fi
        if [ "$i" -lt "$max_retries" ]; then
            echo "    Push failed, retrying in ${delay}s... (attempt $((i+1))/$max_retries)"
            sleep "$delay"
            delay=$((delay * 2))
        fi
    done
    echo "    ERROR: Push failed after $max_retries attempts."
    return 1
}

# ─── Main loop: sync each repo ───────────────────────────────────────────
for full_repo in "${REPOS[@]}"; do
    # Trim whitespace
    full_repo="$(echo "$full_repo" | xargs)"
    [ -z "$full_repo" ] && continue

    # Extract repo name (last component of owner/repo)
    repo_name="${full_repo##*/}"

    # Apply filter if specified
    if [ -n "$FILTER_REPO" ]; then
        if [ "$repo_name" != "$FILTER_REPO" ] && [ "$full_repo" != "$FILTER_REPO" ]; then
            continue
        fi
    fi

    # Skip self
    if [ "$repo_name" = "$THIS_REPO_NAME" ]; then
        echo "[$repo_name] Skipping (this is the source repo)"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    echo "[$repo_name] Syncing..."

    # Step 1: Clone or pull the destination repo
    if ! clone_or_pull "$full_repo" "$repo_name"; then
        FAILED=$((FAILED + 1))
        echo "[$repo_name] FAILED (clone error)"
        echo ""
        continue
    fi

    target_dir="$SYNC_CLONE_DIR/$repo_name"

    # Step 2: Copy docs FROM this repo TO the destination repo
    echo "  Pushing docs to $repo_name..."
    mkdir -p "$target_dir/docs"

    # Copy all doc folders from this repo to the destination
    # This includes docs/claude/ (this repo's docs) and any other repo docs
    # that were previously pulled in
    if [ -d "$REPO_ROOT/docs" ]; then
        # Use rsync if available (preserves structure, handles deletions)
        if command -v rsync &> /dev/null; then
            rsync -a --delete "$REPO_ROOT/docs/" "$target_dir/docs/"
        else
            # Fallback: remove old docs and copy fresh
            rm -rf "$target_dir/docs"
            cp -r "$REPO_ROOT/docs" "$target_dir/docs"
        fi
    fi

    # Step 3: Check if the destination repo has its own docs/<repo_name>/ that we
    #         should pull back into this repo. We do this BEFORE committing/pushing
    #         the destination, so we don't lose any docs the destination repo created.
    #         (The destination's own docs are already in our copy — this handles the
    #          case where someone edited docs directly in the destination repo.)

    # Step 4: Commit and push changes in the destination repo
    cd "$target_dir"

    # Stage docs changes
    git add docs/ 2>/dev/null || true

    if git diff --cached --quiet 2>/dev/null; then
        echo "  No changes to push."
        SKIPPED=$((SKIPPED + 1))
    else
        echo "  Changes detected, committing..."
        git commit -m "docs: sync documentation from $THIS_REPO_NAME

Automated sync via scripts/sync-docs.sh" 2>/dev/null

        echo "  Pushing to origin/$SYNC_DOCS_BRANCH..."
        if push_with_retry "$SYNC_DOCS_BRANCH"; then
            echo "  Pushed successfully."
            SYNCED=$((SYNCED + 1))
        else
            FAILED=$((FAILED + 1))
            echo "[$repo_name] FAILED (push error)"
        fi
    fi

    cd "$REPO_ROOT"

    # Step 5: Pull the destination repo's own docs back into THIS repo
    # (in case they created docs/<repo_name>/ in their repo)
    dest_docs_dir="$target_dir/docs/$repo_name"
    if [ -d "$dest_docs_dir" ] && [ "$(ls -A "$dest_docs_dir" 2>/dev/null)" ]; then
        local_dest="$REPO_ROOT/docs/$repo_name"
        if [ -d "$local_dest" ]; then
            # Check if there are actual differences
            if ! diff -rq "$dest_docs_dir" "$local_dest" &>/dev/null; then
                echo "  Pulling $repo_name's docs back into this repo..."
                if command -v rsync &> /dev/null; then
                    rsync -a "$dest_docs_dir/" "$local_dest/"
                else
                    rm -rf "$local_dest"
                    cp -r "$dest_docs_dir" "$local_dest"
                fi
                PULLED_NEW_DOCS=true
            fi
        else
            echo "  Pulling new docs from $repo_name into this repo..."
            cp -r "$dest_docs_dir" "$local_dest"
            PULLED_NEW_DOCS=true
        fi
    fi

    echo "[$repo_name] Done."
    echo ""
done

# ─── Step 6: Commit any docs pulled from other repos ─────────────────────
if [ "$PULLED_NEW_DOCS" = true ]; then
    echo "==> Committing docs pulled from other repos..."
    cd "$REPO_ROOT"
    git add docs/ 2>/dev/null || true
    if ! git diff --cached --quiet 2>/dev/null; then
        git commit -m "docs: pull documentation from synced repos

Automated sync via scripts/sync-docs.sh"
        echo "  Committed new docs from other repos."
        echo "  NOTE: Remember to push this repo if you want these changes upstream."
    else
        echo "  No new docs to commit."
    fi
fi

# ─── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  Sync complete"
echo "  Pushed:  $SYNCED repos"
echo "  Skipped: $SKIPPED repos (no changes or self)"
echo "  Failed:  $FAILED repos"
echo "════════════════════════════════════════"

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
