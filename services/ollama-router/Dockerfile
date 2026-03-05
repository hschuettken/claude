FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY router/ router/
COPY config.yaml .

EXPOSE 11434

CMD ["uvicorn", "router.main:app", "--host", "0.0.0.0", "--port", "11434", "--log-level", "info"]
