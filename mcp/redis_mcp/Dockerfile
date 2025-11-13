FROM python:3.13-slim

# Install uv (ultra-fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Ensure logs are unbuffered and bytecode isn't written
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency manifest first for layer caching
COPY pyproject.toml ./

RUN uv lock
# Install dependencies into a virtual environment managed by uv
RUN uv sync --no-dev --locked

# Copy application code
COPY . .

# Expose the HTTP port; Fly.io will set PORT but EXPOSE is informational
EXPOSE 8080

# Default PORT for local runs; Fly sets PORT at runtime
ENV PORT=8080

# Run the FastMCP server
CMD ["uv", "run", "server.py"]


