ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY src ./src
COPY filter-spec.yaml ./
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Stage 2: Lean runtime image
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    chown appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src
COPY --from=builder --chown=appuser:appuser /app/filter-spec.yaml ./
ENV PATH="/app/.venv/bin:$PATH"
USER appuser

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

# Contract addresses injected at runtime via shared-env volume — do not hardcode
ENV RPC_URL="" IDENTITY_REGISTRY_ADDRESS="" REPUTATION_REGISTRY_ADDRESS="" VALIDATION_REGISTRY_ADDRESS=""
ENV ENABLE_HEALTH_CHECKS=false HEALTH_CHECK_INTERVAL=60 ENDPOINT_CHECK_TIMEOUT=10 HEARTBEAT_TTL_SECS=60

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
