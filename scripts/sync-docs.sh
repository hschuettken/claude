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
#      b. If docs/<repo-name>/ was deleted by a previous broken sync,
#         recovers it from git history automatically
#      c. Pulls the destination's own docs/<repo-name>/ back into THIS repo
#      d. Collects any "loose" docs (files/folders in docs/ not named after a
#         synced repo) and organizes them into docs/<repo-name>/ in both repos
#      e. Copies docs/ from THIS repo into the destination repo's docs/,
#         EXCLUDING the destination's own docs/<repo-name>/ folder
#      f. Commits and pushes changes in the destination repo
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

# Build list of all known repo folder names (used to distinguish synced folders
# from a destination's own loose docs)
ALL_REPO_NAMES=("$THIS_REPO_NAME")
for _r in "${REPOS[@]}"; do
    _r="$(echo "$_r" | xargs)"
    [ -z "$_r" ] && continue
    ALL_REPO_NAMES+=("${_r##*/}")
done

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

    # Step 1b: Recover docs/<repo_name>/ if a previous (broken) sync deleted them.
    # The old script used rsync --delete without --exclude, which wiped the
    # destination's own docs. Try to restore from git history.
    if [ ! -d "$target_dir/docs/$repo_name" ]; then
        cd "$target_dir"
        last_ref="$(git log --all --format=%H -1 -- "docs/$repo_name/" 2>/dev/null || true)"
        if [ -n "$last_ref" ]; then
            echo "  docs/$repo_name/ missing — recovering from git history..."
            if git checkout "$last_ref" -- "docs/$repo_name/" 2>/dev/null; then
                echo "  Recovered docs/$repo_name/ from commit ${last_ref:0:7}."
            elif git checkout "${last_ref}~1" -- "docs/$repo_name/" 2>/dev/null; then
                echo "  Recovered docs/$repo_name/ from commit before ${last_ref:0:7}."
            else
                echo "  WARNING: Could not recover docs/$repo_name/ from git history."
            fi
        fi
        cd "$REPO_ROOT"
    fi

    # Step 2: Pull the destination repo's own docs back into THIS repo FIRST
    # (before we overwrite anything — the destination is authoritative for its
    #  own docs/<repo_name>/ folder)
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

    # Step 2b: Collect "loose" docs — files or folders in the destination's docs/
    # that aren't named after any synced repo. These are the destination's own
    # docs that haven't been organized into docs/<repo_name>/ yet.
    # We copy them into docs/<repo_name>/ in this repo AND move them in the
    # destination so they survive the rsync --delete in Step 3.
    if [ -d "$target_dir/docs" ]; then
        for entry in "$target_dir/docs/"*; do
            [ -e "$entry" ] || continue
            entry_name="$(basename "$entry")"
            # Skip entries named after known repos (these are synced folders)
            is_repo_folder=false
            for kr in "${ALL_REPO_NAMES[@]}"; do
                if [ "$entry_name" = "$kr" ]; then
                    is_repo_folder=true
                    break
                fi
            done
            if [ "$is_repo_folder" = false ]; then
                echo "  Collecting loose doc '$entry_name' from $repo_name..."
                mkdir -p "$REPO_ROOT/docs/$repo_name"
                cp -r "$entry" "$REPO_ROOT/docs/$repo_name/$entry_name"
                # Move into destination's docs/<repo_name>/ so it survives --delete
                mkdir -p "$target_dir/docs/$repo_name"
                mv "$entry" "$target_dir/docs/$repo_name/$entry_name"
                PULLED_NEW_DOCS=true
            fi
        done
    fi

    # Step 3: Copy docs FROM this repo TO the destination repo
    # IMPORTANT: Exclude the destination's own docs/<repo_name>/ folder — the
    # destination repo is the authority for its own docs and we must not
    # overwrite or delete them.
    echo "  Pushing docs to $repo_name..."
    mkdir -p "$target_dir/docs"

    if [ -d "$REPO_ROOT/docs" ]; then
        if command -v rsync &> /dev/null; then
            rsync -a --delete --exclude="$repo_name/" "$REPO_ROOT/docs/" "$target_dir/docs/"
        else
            # Fallback: save the destination's own docs, replace everything,
            # then restore them
            tmp_backup=""
            if [ -d "$target_dir/docs/$repo_name" ]; then
                tmp_backup="$(mktemp -d)"
                cp -r "$target_dir/docs/$repo_name" "$tmp_backup/$repo_name"
            fi
            rm -rf "$target_dir/docs"
            cp -r "$REPO_ROOT/docs" "$target_dir/docs"
            if [ -n "$tmp_backup" ]; then
                rm -rf "$target_dir/docs/$repo_name"
                cp -r "$tmp_backup/$repo_name" "$target_dir/docs/$repo_name"
                rm -rf "$tmp_backup"
            fi
        fi
    fi

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

    echo "[$repo_name] Done."
    echo ""
done

# ─── Step 5: Commit any docs pulled from other repos ─────────────────────
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
