# Build on the shared base image
FROM homelab-base:latest

# Install service-specific dependencies (if any)
COPY services/example-service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/example-service/main.py /app/main.py
COPY services/example-service/healthcheck.py /app/healthcheck.py

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
