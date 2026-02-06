#!/usr/bin/env bash
# Creates scaffolding for a new service.
#
# Usage: ./scripts/new-service.sh my-service-name
#
set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: $0 <service-name>"
    echo "Example: $0 energy-monitor"
    exit 1
fi

SERVICE_NAME="$1"
SERVICE_DIR="services/${SERVICE_NAME}"

if [ -d "$SERVICE_DIR" ]; then
    echo "Error: Service directory '$SERVICE_DIR' already exists."
    exit 1
fi

echo "Creating service: $SERVICE_NAME"

mkdir -p "$SERVICE_DIR"

# Dockerfile
cat > "$SERVICE_DIR/Dockerfile" << 'DOCKERFILE'
FROM homelab-base:latest

COPY services/SERVICE_NAME/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/SERVICE_NAME/main.py /app/main.py

CMD ["python", "main.py"]
DOCKERFILE
sed -i "s/SERVICE_NAME/${SERVICE_NAME}/g" "$SERVICE_DIR/Dockerfile"

# requirements.txt
cat > "$SERVICE_DIR/requirements.txt" << 'EOF'
# Service-specific dependencies go here.
# Base dependencies are already in the base image.
EOF

# main.py
CLASS_NAME=$(echo "$SERVICE_NAME" | sed -r 's/(^|-)(\w)/\U\2/g')
cat > "$SERVICE_DIR/main.py" << PYTHON
"""${SERVICE_NAME} service."""

import asyncio

from shared.service import BaseService


class ${CLASS_NAME}Service(BaseService):
    name = "${SERVICE_NAME}"

    async def run(self) -> None:
        self.logger.info("service_started")
        self.mqtt.connect_background()

        # TODO: implement your service logic here

        await self.wait_for_shutdown()


if __name__ == "__main__":
    service = ${CLASS_NAME}Service()
    asyncio.run(service.start())
PYTHON

echo ""
echo "Created: $SERVICE_DIR/"
echo "  - Dockerfile"
echo "  - requirements.txt"
echo "  - main.py"
echo ""
echo "Next steps:"
echo "  1. Add your service to docker-compose.yml"
echo "  2. Implement your logic in $SERVICE_DIR/main.py"
echo "  3. Build & run: docker compose up --build $SERVICE_NAME"
