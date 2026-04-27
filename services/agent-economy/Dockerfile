# Build on the shared homelab base image
FROM homelab-base:latest

# Service-specific deps
COPY services/agent-economy/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Copy service source
COPY services/agent-economy/ /app/agent_economy/
COPY shared/ /app/shared/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8240

CMD ["uvicorn", "agent_economy.main:app", "--host", "0.0.0.0", "--port", "8240"]
