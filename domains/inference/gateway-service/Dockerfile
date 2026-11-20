ARG PYTHON_VERSION=3.13

# Every base is pinned to the digest its tag resolved to when written, so the
# image builds from the same inputs until a deliberate update; a change of
# PYTHON_VERSION needs new digests too.

# Stage 1: install the locked dependencies and the gateway's own wheel into a venv.
# Built from the repository root after `make dist-inference-gateway`.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

WORKDIR /app

# The project sits at the same depth below /repo as in the repository, so the
# committed lock's relative wheelhouse resolves to /repo/.dist.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/inference/gateway-service/pyproject.toml domains/inference/gateway-service/uv.lock /repo/domains/inference/gateway-service/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/inference/gateway-service -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/inference/gateway-service

# Stage 2: lean runtime. No source is copied: the gateway runs from its wheel.
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1 AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"
# Credentials are mounted, never built in: the gateway's service-role identity
# and, when the model server needs one, the upstream credential.
ENV INFERENCE_GATEWAY_IDENTITY_CREDENTIAL_FILE=/run/secrets/arkhai/gateway-identity
USER appuser

EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')" || exit 1

CMD ["uvicorn", "--factory", "inference_gateway_service.main:configured_app", "--host", "0.0.0.0", "--port", "8090"]
