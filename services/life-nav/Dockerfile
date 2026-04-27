# Build on the shared homelab base image
FROM homelab-base:latest

# Service-specific deps
COPY services/life-nav/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Copy service source
COPY services/life-nav/ /app/life_nav/
COPY shared/ /app/shared/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8243

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "life_nav/healthcheck.py"]

CMD ["uvicorn", "life_nav.main:app", "--host", "0.0.0.0", "--port", "8243"]
