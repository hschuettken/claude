FROM homelab-base:latest

ENV PYTHONPATH="/app"

COPY services/hems/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/hems/*.py /app/

# Bundle shared libs
COPY shared/ /app/shared/

EXPOSE 8210

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
