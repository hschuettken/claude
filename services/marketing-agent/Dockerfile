FROM homelab-base:latest

COPY services/marketing-agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/marketing-agent/*.py /app/
COPY services/marketing-agent/api/ /app/api/
COPY services/marketing-agent/app/ /app/app/

# Keep shared libs in image as fallback
COPY shared/ /app/shared/
COPY shared/ /app/shared/shared/

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('MARKETING_PORT', '8211') + '/health')"]

CMD ["python", "main.py"]
