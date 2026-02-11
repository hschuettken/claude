FROM homelab-base:latest

COPY services/health-monitor/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/health-monitor/*.py /app/

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
