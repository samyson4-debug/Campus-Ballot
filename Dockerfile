# ==============================================================================
# Campus Ballot — Dockerfile
# Production-ready multi-stage / non-root container for FastAPI + SQLite Web App
# ==============================================================================

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

# Install dependencies needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user
RUN groupadd -g 10001 ballotgroup && \
    useradd -u 10001 -g ballotgroup -s /bin/bash -m ballotuser

# Create persistent data volume directory and set ownership
RUN mkdir -p /data && chown -R ballotuser:ballotgroup /data

# Set workspace root
WORKDIR /app

# Copy dependency requirements first to leverage Docker layer caching
COPY backend/requirements.txt /app/backend/requirements.txt

# Install Python packages as non-root user or globally with clean cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend and frontend source files
COPY backend /app/backend
COPY frontend /app/frontend

# Ensure permissions are correct
RUN chown -R ballotuser:ballotgroup /app

# Switch to unprivileged non-root user
USER ballotuser

# Expose HTTP port
EXPOSE 10000

# Work directory where app module resides
WORKDIR /app/backend

# Standard health check using Python standard library (no curl required)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request, os; port = os.environ.get('PORT', 10000); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health')" || exit 1

# Start command: Single Uvicorn worker is strictly required because of:
# 1. SQLite in-process write serialization / WAL lock coordination
# 2. Thread-safe in-memory login rate limiter
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
