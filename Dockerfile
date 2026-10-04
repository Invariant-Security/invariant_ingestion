# syntax=docker/dockerfile:1
# python:3.12.14-slim fixado por digest do índice -- atualizar
# conscientemente (README, "Locked dependencies").
ARG BASE=python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
FROM ${BASE}

WORKDIR /app

# Dependências antes do código: mudar README/src não reinstala nada.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock
# Build do chromium fixado pela versão travada do playwright; os pacotes
# apt que --with-deps puxa NÃO são fixados.
RUN playwright install --with-deps chromium

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps . && pip check

ENV INVARIANT_INGESTION_RAW_DIR=/app/data/raw

EXPOSE 8000
CMD ["uvicorn", "invariant_ingestion.api:app", "--host", "0.0.0.0", "--port", "8000"]
