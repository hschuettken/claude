FROM homelab-base:latest

# Install service-specific dependencies
COPY services/ev-forecast/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/ev-forecast/*.py /app/

# Bundle shared libs
COPY shared/ /app/shared/
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
