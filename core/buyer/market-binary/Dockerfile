# The release's `market` binary: the buyer CLI frozen with every declared buyer
# domain. Built from the repository root by `make build-market-binary`, which
# derives every build argument below from manifests/release-components.json
# (scripts/market_binary.py) and exports the binary to the directory of its
# declared path.
#
# The environment is this directory's locked project, installed as every image
# installs its lock (docs/development/BUILD_AND_PACKAGING.md, "Images"): every
# repository distribution from the wheelhouse, every other version as the lock
# records it, PyInstaller included. The build image is pinned by digest so the
# binary's Linux floor does not move between builds. PyInstaller output is not
# byte-for-byte repeatable, so the binary is identified by its file's SHA-256,
# not by these pins.
ARG PYTHON_VERSION=3.13

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS build

# The digest, not the tag, selects the image, so a Python version bump that
# leaves the digest behind would still build with the old Python.
ARG PYTHON_VERSION
RUN python3 -c "import sys; have = '%d.%d' % sys.version_info[:2]; sys.exit(None if have == '${PYTHON_VERSION}' else f'the pinned build image runs Python {have}; .python-version declares ${PYTHON_VERSION}: pin the image for it')"

# PyInstaller reads each bundled shared library's dependencies with binutils.
RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*

ARG BINARY_NAME
ARG ENTRY_POINT
ARG PYINSTALLER_OPTIONS
RUN test -n "$BINARY_NAME" && test -n "$ENTRY_POINT" && test -n "$PYINSTALLER_OPTIONS" \
    || { echo "build with make build-market-binary, which derives the build arguments from the declaration" >&2; exit 1; }

ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=10 \
    UV_PROJECT_ENVIRONMENT=/opt/market

# The project's pyproject and lock sit at the same depth below /repo as below
# the repository root, so the lock's relative wheelhouse path resolves to
# /repo/.dist. The project is virtual and builds no wheel of its own.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY core/buyer/market-binary/pyproject.toml core/buyer/market-binary/uv.lock /repo/core/buyer/market-binary/
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/core/buyer/market-binary -- --group freeze

WORKDIR /build
RUN set -eu; \
    module="${ENTRY_POINT%%:*}"; function="${ENTRY_POINT##*:}"; \
    printf 'from %s import %s\n\n%s()\n' "$module" "$function" "$function" > entry.py; \
    /opt/market/bin/pyinstaller --onefile --name "$BINARY_NAME" $PYINSTALLER_OPTIONS entry.py

# No validation suite runs the binary, so this is what exercises it: the frozen
# binary lists exactly the domains the installed CLI discovers, one per
# registered buyer-domain entry point. Discovery skips a domain that fails to
# load, saying so on stderr, so neither run may report a skipped domain.
RUN set -eu; \
    "/opt/market/bin/$BINARY_NAME" plugins > expected 2> expected.err; \
    "./dist/$BINARY_NAME" plugins > frozen 2> frozen.err; \
    cat frozen; \
    if grep -h "skipping buyer domain" expected.err frozen.err >&2; then exit 1; fi; \
    count=$(/opt/market/bin/python -c "from importlib.metadata import entry_points; print(len(entry_points(group='market.buyer_domains')))"); \
    test "$(wc -l < expected)" -eq "$count" \
        || { echo "the installed CLI lists these, not one line per buyer-domain entry point ($count):" >&2; cat expected >&2; exit 1; }; \
    diff expected frozen \
        || { echo "the frozen binary lists other domains than the installed CLI" >&2; exit 1; }

FROM scratch AS binary
ARG BINARY_NAME
COPY --from=build /build/dist/${BINARY_NAME} /${BINARY_NAME}
