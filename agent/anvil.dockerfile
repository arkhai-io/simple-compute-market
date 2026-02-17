# syntax=docker/dockerfile:1
# =====================================================================
# anvil.dockerfile — Anvil with pre-deployed Alkahest + ERC-8004
#
# Produces a minimal Foundry image whose chain state already contains
# all Alkahest (escrow, arbiter, mock ERC20) and ERC-8004 (Identity,
# Reputation, Validation registries) contracts.  Starts instantly.
#
# Build from repo root (context needs both agent/ and erc-8004-contracts/):
#
#   docker buildx build \
#     --platform linux/amd64 \
#     -f agent/anvil.dockerfile \
#     -t anvil-predeployed:latest .
#
# Run:
#   docker run -p 8545:8545 anvil-predeployed:latest
#
# Extract addresses baked into the image:
#   docker run --rm anvil-predeployed:latest cat /anvil-state/addresses.json
# =====================================================================

# ---------- Stage 1: Foundry binaries ----------
FROM ghcr.io/foundry-rs/foundry:latest AS foundry

# ---------- Stage 2: Build — deploy contracts & dump state ----------
FROM python:3.13-slim AS builder

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git build-essential pkg-config libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain (alkahest-py compiles from source)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Node.js 22 (Hardhat)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Foundry binaries from stage 1
COPY --from=foundry /usr/local/bin/anvil /usr/local/bin/anvil
COPY --from=foundry /usr/local/bin/cast  /usr/local/bin/cast

# uv (fast Python package manager)
RUN pip install --no-cache-dir uv

# ── Python environment with alkahest-py ───────────────────────────
WORKDIR /build/agent-env

COPY <<'EOF' pyproject.toml
[project]
name = "anvil-deployer"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "alkahest-py @ git+https://github.com/arkhai-io/alkahest@main#subdirectory=sdks/py",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.metadata]
allow-direct-references = true
EOF

RUN uv sync

# ── ERC-8004 contracts (npm install + compile) ────────────────────
WORKDIR /build/erc-8004-contracts

COPY erc-8004-contracts/package.json erc-8004-contracts/package-lock.json ./
RUN npm ci

COPY erc-8004-contracts/ ./
RUN npx hardhat compile

# ── Deploy script ─────────────────────────────────────────────────
COPY agent/scripts/deploy_and_dump.py /build/deploy_and_dump.py

# ── Run: deploy all contracts → dump chain state ──────────────────
WORKDIR /build
RUN agent-env/.venv/bin/python deploy_and_dump.py

# ---------- Stage 3: Minimal runtime ----------
FROM ghcr.io/foundry-rs/foundry:latest AS runtime

COPY --from=builder /build/anvil-state/ /anvil-state/

EXPOSE 8545

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD cast block-number --rpc-url http://localhost:8545

ENTRYPOINT ["anvil"]
CMD ["--host", "0.0.0.0", "--port", "8545", "--block-time", "2", "--load-state", "/anvil-state/state.json"]
