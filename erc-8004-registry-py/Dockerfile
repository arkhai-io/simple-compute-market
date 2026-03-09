# Use Docker's BuildKit syntax for advanced features
# syntax=docker/dockerfile:1.4
# Define build arguments for Python and uv versions, and the app port
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.10.0
ARG PORT=8080

# Stage 1: Download uv package manager from Astral's container registry
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Stage 2: Main image, use official slim Python image for smaller size
# (For production, pin with SHA256 digest for security)
FROM python:${PYTHON_VERSION}-slim

# Copy uv and uvx binaries from the previous stage to /bin for package management
COPY --from=uv /uv /uvx /bin/

# Create a non-root user (appuser) for better container security
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

# Set working directory to /app and ensure appuser owns it
WORKDIR /app
RUN chown appuser:appuser /app

# Switch to non-root user for all subsequent instructions
USER appuser


# Environment variables for service configuration and registry addresses
# RPC endpoint for blockchain interaction
ENV RPC_URL=""
# Identity registry contract address
ENV IDENTITY_REGISTRY_ADDRESS=0x1f3A2B7c9D0e4F1a2b3C4d5E6f7A8b9C0d1E2f3A
# Reputation registry contract address
ENV REPUTATION_REGISTRY_ADDRESS=0xA4b7C9dE12f3456789aBCdEf0123456789AbCdEf
# Validation registry contract address (optional)
ENV VALIDATION_REGISTRY_ADDRESS=""

# Health check and monitoring configuration
# Enable/disable health checks
ENV ENABLE_HEALTH_CHECKS=false
# Interval (seconds) between health checks
ENV HEALTH_CHECK_INTERVAL=60
# Timeout (seconds) for endpoint checks
ENV ENDPOINT_CHECK_TIMEOUT=10
# Time-to-live for heartbeat signals
ENV HEARTBEAT_TTL_SECS=60
# Copy Python dependency files and install dependencies with uv (no dev packages)
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && \
  find /home/appuser/.cache -type f -delete 2>/dev/null || true && \
  find /usr/local/lib/python${PYTHON_VERSION:-3.12} -name "*.pyc" -delete && \
  find /usr/local/lib/python${PYTHON_VERSION:-3.12} -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Copy application source code into the image
COPY --chown=appuser:appuser src ./src

# Expose the application port (default: 8080)
EXPOSE 8080

# Define a health check to verify the app is running and healthy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

# Start the FastAPI application using uvicorn via uv
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
