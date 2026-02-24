FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

RUN useradd --create-home appuser

WORKDIR /app
RUN chown appuser:appuser /app

USER appuser

# Environment Variables
# SECURITY: Sensitive values (DATABASE_URL, RPC_URL) should be provided at runtime
# via docker run -e, docker-compose, or orchestration secrets (Kubernetes, etc.)
# DO NOT hardcode credentials in this file or commit them to version control

# Database configuration (provide at runtime)
ENV DATABASE_URL=""

# Blockchain configuration
ENV CHAIN_ID=84532
ENV RPC_URL=""
ENV IDENTITY_REGISTRY_ADDRESS=0x1f3A2B7c9D0e4F1a2b3C4d5E6f7A8b9C0d1E2f3A
ENV REPUTATION_REGISTRY_ADDRESS=0xA4b7C9dE12f3456789aBCdEf0123456789AbCdEf
ENV VALIDATION_REGISTRY_ADDRESS=""

# Server configuration
ENV PORT=8080
ENV HOST=0.0.0.0

# Health check configuration
ENV ENABLE_HEALTH_CHECKS=false
ENV HEALTH_CHECK_INTERVAL=60
ENV ENDPOINT_CHECK_TIMEOUT=10
ENV HEARTBEAT_TTL_SECS=60

# Logging
ENV LOG_LEVEL=info

COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY --chown=appuser:appuser src ./src

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
