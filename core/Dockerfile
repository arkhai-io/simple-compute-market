# --platform=linux/amd64 is intentional: production targets Linux x86_64.
# Keep this pin in all FROM lines.

# Stage 1: Install Python dependencies using uv
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends git g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY core/pyproject.toml core/uv.lock ./
COPY core/agent/packages/ ./agent/packages/
COPY service/ ../service/
COPY cli/ ../cli/

# Pass the GCP service account JSON key from GitHub Actions secrets to authenticate
# against GCP Artifact Registry for the alkahest-py private Python package.
ARG GAR_STG_READER_KEY=""
ARG INSTALL_RL_DEPS=false

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    if [ "${INSTALL_RL_DEPS}" = "true" ]; then \
        uv sync --frozen --no-dev --no-install-project --extra rl; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Copy the cached venv from builder
COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install ZeroTier
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg iproute2 kmod sudo && \
    curl -s https://install.zerotier.com | bash && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/lib/zerotier-one && \
    printf '{\n  "settings": {\n    "allowManagementFrom": [ "127.0.0.1", "::1" ]\n  }\n}\n' \
      > /var/lib/zerotier-one/local.conf && \
    # Remove any identity generated during install so each container gets a unique node ID
    rm -f /var/lib/zerotier-one/identity.public /var/lib/zerotier-one/identity.secret

EXPOSE 9993/udp

# Copy the application code preserving the import path (from core.agent.app.*)
COPY core/agent/app ./core/agent/app
COPY core/agent/scripts ./core/agent/scripts
COPY core/agent/.env.sample .
COPY core/schemas.py ./core/schemas.py
COPY domain/ ./domain/
COPY service/ ../service/

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

COPY core/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

CMD ["./entrypoint.sh"]
