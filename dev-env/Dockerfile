ARG FOUNDRY_VERSION=latest

FROM ghcr.io/foundry-rs/foundry:${FOUNDRY_VERSION}

USER root

# Health checks probe Anvil with the image's own `cast`, so the build installs
# no packages and needs no package mirror.

COPY ./state /state

ENTRYPOINT anvil --load-state /state/state.json
