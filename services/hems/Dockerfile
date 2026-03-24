FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH="/app:/app/shared"

WORKDIR /app

COPY base/requirements.txt /tmp/base-requirements.txt
RUN pip install --no-cache-dir -r /tmp/base-requirements.txt && rm /tmp/base-requirements.txt

COPY services/hems/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/hems/*.py /app/
COPY shared/ /app/shared/

EXPOSE 8210

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
