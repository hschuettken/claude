FROM python:3.12-slim
ENV PYTHONPATH="/app:/app/shared"

# System dependencies (mirrors homelab-base)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install base requirements inline (homelab-base:latest not available on all hosts)
COPY base/requirements.txt /tmp/base-requirements.txt
RUN pip install --no-cache-dir -r /tmp/base-requirements.txt && rm /tmp/base-requirements.txt

# Service-specific requirements (none currently, placeholder for future)
COPY services/smart-ev-charging/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/smart-ev-charging/*.py /app/

# Bundle shared libs
COPY shared/ /app/shared/

WORKDIR /app

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
