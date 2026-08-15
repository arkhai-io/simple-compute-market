FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=10

COPY .dist/ /.dist/
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python --find-links /.dist \
      arkhai-bare-metal-storefront==0.2.0

FROM --platform=linux/amd64 python:3.12-slim-bookworm AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 appuser && \
    mkdir -p /var/lib/arkhai && \
    chown appuser:appuser /var/lib/arkhai

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    BARE_METAL_STOREFRONT_DB_PATH=/var/lib/arkhai/bare-metal-storefront.db

USER appuser
WORKDIR /var/lib/arkhai
EXPOSE 8000
VOLUME ["/var/lib/arkhai"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD curl --fail --silent http://127.0.0.1:8000/health || exit 1
ENTRYPOINT ["bare-metal-storefront"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
