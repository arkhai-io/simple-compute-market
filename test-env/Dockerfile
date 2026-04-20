ARG FOUNDRY_VERSION=latest

FROM ghcr.io/foundry-rs/foundry:${FOUNDRY_VERSION}

USER root

#Added curl for health checks
RUN apt-get update && apt-get install -y curl

COPY ./state /state

ENTRYPOINT anvil --load-state /state/state.json