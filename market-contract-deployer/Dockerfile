FROM node:22-alpine

# ERC_8004_CONTRACTS_SHA pins the upstream tree — update deliberately when contracts change.
# Using a tarball download (no git history, fast) rather than git clone.
ARG ERC_8004_CONTRACTS_SHA=c7ce292f405b692374f8c5ff3febfaececec3a8b

RUN apk add --no-cache bash curl python3

# Download the pinned tree from GitHub as a tarball — much faster than git clone
RUN mkdir -p /app \
    && curl -fsSL https://github.com/erc-8004/erc-8004-contracts/archive/${ERC_8004_CONTRACTS_SHA}.tar.gz \
       | tar xz --strip-components=1 -C /app

WORKDIR /app

# Install npm deps with BuildKit cache mount for fast subsequent builds
RUN --mount=type=cache,target=/root/.npm \
    npm ci --legacy-peer-deps

# Replace the official hardhat config before compile so solc is downloaded and
# cached in this layer — avoids the slow WASM fallback at container runtime.
COPY hardhat.config.ts .
RUN npx hardhat compile

# Overlay remaining deploy tooling
# custom-chains.ts adds an "anvil" entry so deploy-vanity.ts --network anvil
# connects directly to Anvil via viem (bypasses Hardhat's in-process EVM).
COPY custom-chains.ts scripts/custom-chains.ts
COPY scripts/upgrade-local.ts scripts/upgrade-local.ts
COPY deploy-local.sh deploy_alkahest.py seed_agent.py alkahest-transactions.json ./
RUN chmod +x deploy-local.sh

ENV RPC_URL=http://anvil:8545
ENV CHAIN_ID=31337

CMD ["sh", "-c", "./deploy-local.sh"]
