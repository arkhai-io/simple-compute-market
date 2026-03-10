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

COPY packages/ ./packages/
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
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

# Copy the application code
COPY ./app ./app
COPY ./scripts ./scripts
COPY .env.sample .

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

COPY ./entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

CMD ["./entrypoint.sh"]