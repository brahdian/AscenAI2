FROM python:3.12.9-slim

WORKDIR /app

# /app           — voice-pipeline source
# /app/shared    — shared library (pii, auth, etc.)
# /app/orchestrator_src — ai-orchestrator source (for in-process Brain)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/orchestrator_src \
    PORT=8003 \
    WORKERS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip \
    && addgroup --system app && adduser --system --ingroup app app

# Install voice-pipeline deps first
COPY services/voice-pipeline/requirements.txt .
# Install ai-orchestrator deps too (shared Brain needs them)
COPY services/ai-orchestrator/requirements.txt /tmp/orchestrator_requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r /tmp/orchestrator_requirements.txt \
    && python -m spacy download en_core_web_sm --quiet

# Install shared library
COPY shared /app/shared
RUN pip install --no-cache-dir /app/shared

# Copy ai-orchestrator source as a sibling package
COPY services/ai-orchestrator/ /app/orchestrator_src/

# Copy voice-pipeline source
COPY --chown=app:app services/voice-pipeline/ .
RUN mkdir -p /tmp/audio && chown app:app /tmp/audio

USER app
EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WORKERS} --log-level warning --no-access-log"]