# Build on the shared homelab base image
FROM homelab-base:latest

# Service-specific deps
COPY services/self-optimizing-infra/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Copy service source
COPY services/self-optimizing-infra/ /app/self_optimizing_infra/
COPY shared/ /app/shared/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8242

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "self_optimizing_infra/healthcheck.py"]

CMD ["uvicorn", "self_optimizing_infra.main:app", "--host", "0.0.0.0", "--port", "8242"]
