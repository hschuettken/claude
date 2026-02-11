FROM homelab-base:latest

COPY services/orchestrator/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code (flat + subdirectories)
COPY services/orchestrator/*.py /app/
COPY services/orchestrator/llm/ /app/llm/
COPY services/orchestrator/channels/ /app/channels/

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
