FROM python:3.12-slim

# Common system dependencies for all services
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Shared base requirements (installed into the base image so every service gets them)
COPY requirements.txt /tmp/base-requirements.txt
RUN pip install --no-cache-dir -r /tmp/base-requirements.txt && rm /tmp/base-requirements.txt

# Shared library — baked into the image (bind mount overlays at runtime if present)
ENV PYTHONPATH="/app:/app/shared:${PYTHONPATH}"

WORKDIR /app

# Bundle shared library into base image so all services have it
COPY shared/ /app/shared/
