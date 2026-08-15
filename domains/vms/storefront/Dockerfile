# --platform=linux/amd64 is intentional: production targets Linux x86_64.
# Keep this pin in all FROM lines.

# Stage 1: Install Python dependencies using uv
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# No UV_COMPILE_BYTECODE here: this image builds under x86 emulation
# and uv's post-install bytecode-compile python workers deadlock under
# Rosetta sporadically — a wedged build, not a slow one. Cold starts
# pay a small first-import cost instead.
ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
# PyPI intermittently serves 5xx even for index lookups that should
# 404 (internal package names resolved from /dist); back off through
# the flap instead of failing the build after the default 3 tries.
ENV UV_HTTP_RETRIES=10

RUN apt-get update && apt-get install -y --no-install-recommends git g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG DIST_FINGERPRINT=unknown
LABEL org.arkhai.builder-dist-fingerprint="${DIST_FINGERPRINT}"

# Copy the pre-built wheels from the monorepo .dist/ directory.
# These are built on the host by `make dist` before `docker build`.
COPY .dist/ /.dist/

COPY domains/vms/storefront/pyproject.toml domains/vms/storefront/uv.lock domains/vms/storefront/entrypoint.sh ./
# The lock records the internal-wheel find-links dir relative to the repo
# (../../../.dist), which cannot normalize from /app. Point it at the
# in-image wheel dir instead. (uv re-canonicalizes the path on every
# relock, so this is normalized here rather than in the committed lock.)
RUN sed -E -i 's|registry = "[^"]*\.dist"|registry = "/.dist"|' uv.lock

# Pass the GCP service account JSON key from GitHub Actions secrets to authenticate
# against GCP Artifact Registry for the alkahest-py private Python package.
ARG GAR_STG_READER_KEY=""
ARG INSTALL_RL_DEPS=false

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    if [ "${INSTALL_RL_DEPS}" = "true" ]; then \
        uv sync --no-sources --no-dev --no-install-project --extra rl --find-links /.dist \
            --refresh-package arkhai-core \
            --refresh-package arkhai-core-storefront \
            --refresh-package arkhai-kit-capacity-publication \
            --refresh-package arkhai-core-registry-client \
            --refresh-package arkhai-core-storefront-client \
            --refresh-package arkhai-kit-policy \
            --refresh-package arkhai-kit-settlement-runtime \
            --refresh-package arkhai-kit-storefront \
            --refresh-package arkhai-kit-negotiation-runtime \
            --refresh-package arkhai-kit-alkahest \
            --refresh-package arkhai-kit-identity \
            --refresh-package arkhai-hosted-settlement-client \
            --refresh-package arkhai-kit-hosted-settlement \
            --refresh-package arkhai-kit-config \
            --refresh-package arkhai-kit-site-client \
            --refresh-package arkhai-kit-site \
            --refresh-package arkhai-kit-resource-pools \
            --refresh-package arkhai-kit-fulfillment \
            --refresh-package arkhai-vms \
            --refresh-package arkhai-bare-metal \
            --refresh-package arkhai-bare-metal-storefront \
            --refresh-package arkhai-vms-storefront \
            --refresh-package arkhai-compute-provisioning; \
    else \
        uv sync --no-sources --no-dev --no-install-project --find-links /.dist \
            --refresh-package arkhai-core \
            --refresh-package arkhai-core-storefront \
            --refresh-package arkhai-kit-capacity-publication \
            --refresh-package arkhai-core-registry-client \
            --refresh-package arkhai-core-storefront-client \
            --refresh-package arkhai-kit-policy \
            --refresh-package arkhai-kit-settlement-runtime \
            --refresh-package arkhai-kit-storefront \
            --refresh-package arkhai-kit-negotiation-runtime \
            --refresh-package arkhai-kit-alkahest \
            --refresh-package arkhai-kit-identity \
            --refresh-package arkhai-hosted-settlement-client \
            --refresh-package arkhai-kit-hosted-settlement \
            --refresh-package arkhai-kit-config \
            --refresh-package arkhai-kit-site-client \
            --refresh-package arkhai-kit-site \
            --refresh-package arkhai-kit-resource-pools \
            --refresh-package arkhai-kit-fulfillment \
            --refresh-package arkhai-vms \
            --refresh-package arkhai-bare-metal \
            --refresh-package arkhai-bare-metal-storefront \
            --refresh-package arkhai-vms-storefront \
            --refresh-package arkhai-compute-provisioning; \
    fi

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime


# ENV does not cross FROM; retain the raised retry policy for runtime wheel
# installation (see the builder-stage rationale above).
ENV UV_HTTP_RETRIES=10

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg iproute2 kmod sudo git && \
    curl -s https://install.zerotier.com | bash && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/lib/zerotier-one && \
    printf '{\n  "settings": {\n    "allowManagementFrom": [ "127.0.0.1", "::1" ]\n  }\n}\n' \
      > /var/lib/zerotier-one/local.conf && \
    rm -f /var/lib/zerotier-one/identity.public /var/lib/zerotier-one/identity.secret && \
    useradd -m -s /bin/sh appuser && \
    echo 'appuser ALL=(root) NOPASSWD: /usr/sbin/zerotier-one, /usr/sbin/zerotier-cli' \
      > /etc/sudoers.d/appuser && \
    chmod 0440 /etc/sudoers.d/appuser && \
    mkdir -p /app && \
    chown appuser /app

USER appuser
WORKDIR /app

EXPOSE 9993/udp

# Bind cross-stage application layers to the exact internal wheel set.
ARG DIST_FINGERPRINT=unknown
LABEL org.arkhai.dist-fingerprint="${DIST_FINGERPRINT}"

COPY --chown=appuser:appuser --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV XDG_CONFIG_HOME="/etc"
# The runtime contains only installed artifacts.  Contribution packages and the
# common shell are resolved from the staged wheelhouse; repository source trees
# are never copied into the image.
COPY .dist/ /.dist/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv/bin/python --no-deps --no-index \
        --find-links /.dist \
        arkhai-vms-storefront==0.3.0 \
        arkhai-bare-metal-storefront==0.2.0

# Fail the image build if the immutable hosted client regains a seller command
# or any repository dependency was installed as an editable sibling source.
RUN python -c 'import importlib.metadata as m, json; import domains.vms.listings, domains.vms.negotiation, domains.vms.settlement, market_storefront.cli; assert all(ep.name != "hosted-settlement-seller" for ep in m.entry_points(group="console_scripts")); assert all(not (json.loads(text).get("dir_info") or {}).get("editable", False) for dist in m.distributions() if (text := dist.read_text("direct_url.json")))'

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

COPY --chown=appuser:appuser domains/vms/storefront/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

CMD ["./entrypoint.sh"]
