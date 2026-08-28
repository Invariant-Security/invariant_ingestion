# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium

EXPOSE 8000
CMD ["uvicorn", "invariant_ingestion.api:app", "--host", "0.0.0.0", "--port", "8000"]
