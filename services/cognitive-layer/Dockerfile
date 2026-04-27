# Build on the shared homelab base image
FROM homelab-base:latest

# Service-specific deps
COPY services/cognitive-layer/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Copy service source
COPY services/cognitive-layer/ /app/cognitive_layer/
COPY shared/ /app/shared/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8230

CMD ["uvicorn", "cognitive_layer.main:app", "--host", "0.0.0.0", "--port", "8230"]
