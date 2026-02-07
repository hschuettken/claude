#!/usr/bin/env bash
# Encrypt .env → .env.enc using SOPS + age
# The encrypted file is safe to commit to git.
set -euo pipefail

# Check dependencies
for cmd in sops age; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is not installed."
        echo ""
        echo "Install both tools:"
        echo "  # age"
        echo "  sudo apt install age          # Debian/Ubuntu"
        echo "  brew install age               # macOS"
        echo ""
        echo "  # sops"
        echo "  sudo apt install sops          # Debian/Ubuntu (24.04+)"
        echo "  brew install sops              # macOS"
        echo "  # Or download from: https://github.com/getsops/sops/releases"
        exit 1
    fi
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="$REPO_ROOT/.sops/age-key.txt"
ENV_FILE="$REPO_ROOT/.env"
ENC_FILE="$REPO_ROOT/.env.enc"

if [ ! -f "$KEY_FILE" ]; then
    echo "ERROR: age key not found at $KEY_FILE"
    echo "Run: age-keygen -o $KEY_FILE"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "Copy .env.example to .env and fill in your values first."
    exit 1
fi

export SOPS_AGE_KEY_FILE="$KEY_FILE"

sops encrypt --input-type dotenv --output-type dotenv "$ENV_FILE" > "$ENC_FILE"

echo "Encrypted .env → .env.enc"
echo "You can now commit .env.enc to git."
