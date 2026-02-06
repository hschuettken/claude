#!/usr/bin/env bash
# Install git hooks for this repository
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$REPO_ROOT/.git/hooks"

mkdir -p "$HOOK_DIR"

cat > "$HOOK_DIR/pre-commit" << 'HOOK'
#!/usr/bin/env bash
# Prevent committing plain-text .env file
if git diff --cached --name-only | grep -qE '(^|/)\.env$'; then
    echo "ERROR: Refusing to commit plain-text .env file!"
    echo ""
    echo "  Your .env contains unencrypted secrets."
    echo "  Use the encrypted version instead:"
    echo ""
    echo "    ./scripts/secrets-encrypt.sh   # encrypt .env → .env.enc"
    echo "    git add .env.enc               # stage the encrypted file"
    echo ""
    exit 1
fi

# Warn if .sops/ directory contents are staged
if git diff --cached --name-only | grep -qE '(^|/)\.sops/'; then
    echo "ERROR: Refusing to commit .sops/ directory (contains private key)!"
    echo ""
    echo "  Your age private key must never be committed to git."
    echo "  Store it in a password manager instead."
    echo ""
    exit 1
fi
HOOK

chmod +x "$HOOK_DIR/pre-commit"
echo "Git hooks installed successfully."
