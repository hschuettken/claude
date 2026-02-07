#!/usr/bin/env bash
# Decrypt .env.enc → .env using SOPS + age
# Run this after cloning the repo on a new machine.
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
ENC_FILE="$REPO_ROOT/.env.enc"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$KEY_FILE" ]; then
    echo "ERROR: age key not found at $KEY_FILE"
    echo ""
    echo "To set up on a new machine:"
    echo "  1. Copy your age key file to: $KEY_FILE"
    echo "  2. Run this script again"
    echo ""
    echo "Your age key was generated during initial setup."
    echo "It should be stored securely (e.g. password manager)."
    exit 1
fi

if [ ! -f "$ENC_FILE" ]; then
    echo "ERROR: .env.enc not found at $ENC_FILE"
    echo "Has the encrypted env file been committed to the repo?"
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    echo "WARNING: .env already exists. Overwrite? [y/N]"
    read -r answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi
fi

export SOPS_AGE_KEY_FILE="$KEY_FILE"

sops decrypt --input-type dotenv --output-type dotenv "$ENC_FILE" > "$ENV_FILE"

echo "Decrypted .env.enc → .env"
