#!/usr/bin/env bash
# Builds the shared base Docker image that all services inherit from.
#
# Usage: ./scripts/build-base.sh
#
set -euo pipefail

echo "Building homelab-base image..."
docker build -t homelab-base:latest -f base/Dockerfile base/
echo "Done. All services will use homelab-base:latest."
