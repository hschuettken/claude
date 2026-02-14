FROM homelab-base:latest

# Install dashboard-specific dependencies
COPY services/dashboard/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/dashboard/*.py /app/

# NiceGUI web server port
EXPOSE 8085

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
