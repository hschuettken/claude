# Build on the shared homelab base image
FROM homelab-base:latest

# Service-specific deps
COPY services/digital-twin/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Copy service source
COPY services/digital-twin/ /app/digital_twin/
COPY shared/ /app/shared/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8238

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "digital_twin/healthcheck.py"]

CMD ["uvicorn", "digital_twin.main:app", "--host", "0.0.0.0", "--port", "8238"]
