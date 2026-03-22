FROM homelab-base:latest

COPY services/marketing-agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/marketing-agent/*.py /app/
COPY services/marketing-agent/api/ /app/api/

# Keep shared libs in image as fallback
COPY shared/ /app/shared/
COPY shared/ /app/shared/shared/

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import requests; requests.get('http://localhost:8210/health').raise_for_status()"]

CMD ["python", "main.py"]
