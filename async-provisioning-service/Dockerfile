FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

RUN useradd --create-home appuser

WORKDIR /app
RUN chown appuser:appuser /app

USER appuser

COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser start.sh ./

ENV PYTHONPATH=/app/src

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]

CMD ["sh", "start.sh"]
