# Stage 1: Dependency Downloading and building the wheel
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

#gcc * g++ are unfortunately required to build pufferlib.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

#This installs the dependencies to a cache layer so they don't need to be redownloaded every docker build
#The output is a cache of the .venv folder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY packages/ ./packages/
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Stage 2: Lean runtime image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Copy the cached venv from builder
COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application code
COPY ./app .
COPY .env.sample .

EXPOSE 8080

# This needs to be patched to a valid cmd. I was digging through the makefile for targets but it isn't clear what I should run.
# The contents of make serve-a2a are too complicated for a cmd.
# I could convert it to a shell script and run that but the functionality of the target appears to me like it should be part of the Python code.
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]