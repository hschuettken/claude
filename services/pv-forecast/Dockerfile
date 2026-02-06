FROM homelab-base:latest

COPY services/pv-forecast/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY services/pv-forecast/*.py /app/

CMD ["python", "main.py"]
