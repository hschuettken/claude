#!/usr/bin/env bash
# Edit encrypted secrets in-place using SOPS
# Opens .env.enc in your $EDITOR, decrypted. Saves re-encrypted on close.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="$REPO_ROOT/.sops/age-key.txt"
ENC_FILE="$REPO_ROOT/.env.enc"

if [ ! -f "$KEY_FILE" ]; then
    echo "ERROR: age key not found at $KEY_FILE"
    exit 1
fi

if [ ! -f "$ENC_FILE" ]; then
    echo "ERROR: .env.enc not found. Run secrets-encrypt.sh first."
    exit 1
fi

export SOPS_AGE_KEY_FILE="$KEY_FILE"

sops edit --input-type dotenv --output-type dotenv "$ENC_FILE"

echo "Secrets updated and re-encrypted."
