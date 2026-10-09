ARG PYTHON_VERSION=3.13

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=10 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/bare_metal/storefront/pyproject.toml domains/bare_metal/storefront/uv.lock /repo/domains/bare_metal/storefront/
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/bare_metal/storefront -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/bare_metal/storefront

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

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
