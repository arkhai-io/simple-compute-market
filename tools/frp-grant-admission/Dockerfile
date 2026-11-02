ARG PYTHON_VERSION=3.13

# The build context is this directory: the plugin depends on no package of the
# repository around it, so its image builds from what it ships alone.

# Stage 1: install the committed lock, unchanged, and the plugin into /app/.venv.
# --platform=linux/amd64 is intentional: production targets Linux x86_64.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
# --locked refuses a lock that does not match the project rather than rewriting it.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Stage 2: the runtime, as an unprivileged user.
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

# The plugin's own version, as pyproject.toml declares it, passed by whoever builds
# the image (`--build-arg VERSION=<version>`), so it is written in one place only.
ARG VERSION
LABEL org.opencontainers.image.title="frp-grant-admission" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin plugin

# The environment installs the plugin editable from /app/src, so both keep their paths.
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src
COPY examples/config.toml ./examples/config.toml
ENV PATH="/app/.venv/bin:$PATH"
USER plugin

# The configuration's directory is mounted read-only at /etc/frp-grant-admission: a
# mount of the file alone keeps the file it first saw, so a reload after the file is
# replaced would read the old one. The exec form makes the plugin PID 1, so SIGHUP sent
# to the container (`docker kill -s HUP`) reloads it. PID 1 ignores a signal it has no
# handler for, so the stop signal is SIGINT, which the plugin handles by closing its
# socket and exiting.
STOPSIGNAL SIGINT
ENTRYPOINT ["frp-grant-admission"]
CMD ["serve", "--config", "/etc/frp-grant-admission/config.toml"]
