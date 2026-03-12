# @TODO: remove platform specific flags once puffer wheel is built
# Puffer wheel is having build issues if flag is not set

# Stage 1: Dependency Downloading and building the wheel
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

#gcc * g++ are unfortunately required to build pufferlib.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make curl gnupg \
    && curl -s https://install.zerotier.com | bash \
    && rm -rf /var/lib/apt/lists/*

#This installs the dependencies to a cache layer so they don't need to be redownloaded every docker build
#The output is a cache of the .venv folder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY core/pyproject.toml core/uv.lock ./
COPY service/ ../service/

# Pass the GCP service account JSON key from GitHub Actions secrets to authenticate
# against GCP Artifact Registry for the alkahest-py private Python package.
ARG GAR_STG_READER_KEY=""
RUN echo ">>> GAR_STG_READER_KEY length: ${#GAR_STG_READER_KEY}" && \
    echo ">>> GAR_STG_READER_KEY first char: $(echo "${GAR_STG_READER_KEY}" | cut -c1)" && \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        echo ">>> GAR_STG_READER_KEY is SET"; \
    else \
        echo ">>> GAR_STG_READER_KEY is EMPTY — uv sync will run unauthenticated"; \
    fi

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    uv sync --frozen --no-dev --no-install-project

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Copy the cached venv from builder
COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy ZeroTier binaries from builder
COPY --from=builder /usr/sbin/zerotier-one /usr/sbin/zerotier-one
COPY --from=builder /usr/sbin/zerotier-cli /usr/sbin/zerotier-cli
COPY --from=builder /usr/sbin/zerotier-idtool /usr/sbin/zerotier-idtool

RUN mkdir -p /var/lib/zerotier-one && \
    echo '{\n  "settings": {\n    "allowManagementFrom": [ "127.0.0.1", "::1" ]\n  }\n}' > /var/lib/zerotier-one/local.conf

EXPOSE 9993/udp

# Copy the application code preserving the import path (from core.agent.app.*)
COPY core/agent/app ./core/agent/app
COPY core/agent/scripts ./core/agent/scripts
COPY core/agent/.env.sample .
COPY core/schemas.py ./core/schemas.py
COPY service/ ../service/

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

COPY core/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

CMD ["./entrypoint.sh"]