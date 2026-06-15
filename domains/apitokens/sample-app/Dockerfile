ARG PYTHON_VERSION=3.13

# Stage 1: install the sample app + its middleware from the monorepo
# wheels. Built from the repo root so .dist/ is in context.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy
ENV UV_HTTP_RETRIES=10

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && chown appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser .dist/ /home/appuser/dist/
# Install the app wheel and its arkhai-apitokens-middleware dependency
# straight from .dist (no project tree needed — the wheel ships the
# console script and the middleware ships the gate).
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    uv venv /home/appuser/.venv && \
    uv pip install --python /home/appuser/.venv/bin/python \
        --find-links /home/appuser/dist \
        arkhai-apitokens-sample-app arkhai-apitokens-middleware

# Stage 2: lean runtime.
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /home/appuser
COPY --from=builder --chown=appuser:appuser /home/appuser/.venv ./.venv
ENV PATH="/home/appuser/.venv/bin:$PATH"
USER appuser

ARG PORT=8085
ENV APITOKENS_SAMPLE_APP_PORT=${PORT}
EXPOSE ${PORT}

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8085/health')" || exit 1

CMD ["apitokens-sample-app"]
