ARG FOUNDRY_VERSION=latest

FROM ghcr.io/foundry-rs/foundry:${FOUNDRY_VERSION}

COPY ./state /state

USER root

ENTRYPOINT anvil --load-state /state/state.json