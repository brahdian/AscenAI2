FROM python:3.12.9-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8002 \
    WORKERS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --ingroup app app

COPY services/ai-orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_lg --quiet \
    || true

COPY shared /app/shared
RUN pip install --no-cache-dir /app/shared

COPY --chown=app:app services/ai-orchestrator/ .

RUN mkdir -p /data/documents && chown app:app /data/documents

USER app
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WORKERS} --log-level warning --no-access-log"]