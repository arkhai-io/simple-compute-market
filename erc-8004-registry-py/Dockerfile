# syntax=docker/dockerfile:1.4
ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.10.0
ARG PORT=8080

# TODO: Pin with SHA256 digest for production: FROM python:3.13-slim@sha256:...
FROM python:${PYTHON_VERSION}-slim

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /bin/

# Non-root user for security
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

WORKDIR /app
RUN chown appuser:appuser /app

USER appuser

<<<<<<< HEAD
# NOTE: Don't put secrets here - pass them via -e flag or docker-compose
# DATABASE_URL and RPC_URL should come from runtime config
ENV DATABASE_URL=""

# Blockchain settings (Base Sepolia by default)
ARG CHAIN_ID=84532
ENV CHAIN_ID=${CHAIN_ID}
=======
# Environment Variables
# SECURITY: Sensitive values (DATABASE_URL, RPC_URL) should be provided at runtime
# via docker run -e, docker-compose, or orchestration secrets (Kubernetes, etc.)
# DO NOT hardcode credentials in this file or commit them to version control

# Database configuration (provide at runtime)
ENV DATABASE_URL=""

# Blockchain configuration
ENV CHAIN_ID=84532
>>>>>>> 83613a7eb70ca6b44768c8c040b879cfca716a33
ENV RPC_URL=""
ENV IDENTITY_REGISTRY_ADDRESS=0x1f3A2B7c9D0e4F1a2b3C4d5E6f7A8b9C0d1E2f3A
ENV REPUTATION_REGISTRY_ADDRESS=0xA4b7C9dE12f3456789aBCdEf0123456789AbCdEf
ENV VALIDATION_REGISTRY_ADDRESS=""

<<<<<<< HEAD
# Server config
ENV PORT=${PORT}
ENV HOST=0.0.0.0

# Health monitoring
=======
# Server configuration
ENV PORT=8080
ENV HOST=0.0.0.0

# Health check configuration
>>>>>>> 83613a7eb70ca6b44768c8c040b879cfca716a33
ENV ENABLE_HEALTH_CHECKS=false
ENV HEALTH_CHECK_INTERVAL=60
ENV ENDPOINT_CHECK_TIMEOUT=10
ENV HEARTBEAT_TTL_SECS=60
<<<<<<< HEAD
ENV LOG_LEVEL=info

# Install Python deps (production only)
=======

# Logging
ENV LOG_LEVEL=info

>>>>>>> 83613a7eb70ca6b44768c8c040b879cfca716a33
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && \
    find /home/appuser/.cache -type f -delete 2>/dev/null || true && \
    find /usr/local/lib/python${PYTHON_VERSION:-3.13} -name "*.pyc" -delete && \
    find /usr/local/lib/python${PYTHON_VERSION:-3.13} -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

COPY --chown=appuser:appuser src ./src

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
