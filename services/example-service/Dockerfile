# Build on the shared base image
FROM homelab-base:latest

# Install service-specific dependencies (if any)
COPY services/example-service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy service code
COPY services/example-service/main.py /app/main.py

CMD ["python", "main.py"]
