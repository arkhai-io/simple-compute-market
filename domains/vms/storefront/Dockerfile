# --platform=linux/amd64 is intentional: production targets Linux x86_64.
# Keep this pin in all FROM lines.

# Stage 1: Install Python dependencies using uv
ARG PYTHON_VERSION=3.13

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

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

# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/vms/storefront/pyproject.toml domains/vms/storefront/uv.lock /repo/domains/vms/storefront/
COPY domains/vms/storefront/entrypoint.sh ./
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Pass the GCP service account JSON key from GitHub Actions secrets to authenticate
# against GCP Artifact Registry for the alkahest-py private Python package.
ARG GAR_STG_READER_KEY=""
ARG INSTALL_RL_DEPS=false

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    extra="" && \
    if [ "${INSTALL_RL_DEPS}" = "true" ]; then extra="--extra rl"; fi && \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/vms/storefront -- --no-dev --no-install-project $extra && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/vms/storefront

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS runtime


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
# The runtime contains only the environment the builder installed; neither the
# wheelhouse nor repository source is copied into it.

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
