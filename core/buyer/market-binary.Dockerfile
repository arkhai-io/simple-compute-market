# The release's `market` binary: the buyer CLI frozen with every declared buyer
# domain, installed from the wheelhouse. Built from the repository root by
# `make build-market-binary`, which derives every build argument below from
# manifests/release-components.json (scripts/buyer_domain_wheels.py) and
# exports the binary to .dist/bin/market.
#
# The build image is pinned by digest so the binary's Linux floor does not move
# between builds. PyInstaller output is not byte-for-byte repeatable, so the
# binary is identified by its file's SHA-256, not by this pin.
ARG PYTHON_VERSION=3.13

FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS build

# The digest, not the tag, selects the image, so a Python version bump that
# leaves the digest behind would still build with the old Python.
ARG PYTHON_VERSION
RUN python3 -c "import sys; have = '%d.%d' % sys.version_info[:2]; sys.exit(None if have == '${PYTHON_VERSION}' else f'the pinned build image runs Python {have}; .python-version declares ${PYTHON_VERSION}: pin the image for it')"

# PyInstaller reads each bundled shared library's dependencies with binutils.
RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*

ARG CLI_WHEEL
ARG DOMAIN_WHEELS
ARG CONSTRAINTS
ARG ENTRY_POINT
ARG PYINSTALLER_OPTIONS
RUN test -n "$CLI_WHEEL" && test -n "$DOMAIN_WHEELS" && test -n "$CONSTRAINTS" \
    && test -n "$ENTRY_POINT" && test -n "$PYINSTALLER_OPTIONS" \
    || { echo "build with make build-market-binary, which derives the build arguments from the declaration" >&2; exit 1; }

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_RETRIES=10

COPY .dist/ /dist/

# PyPI also serves the internal distributions, some at the versions the
# wheelhouse holds, and the binary must bundle the wheelhouse's bytes, which a
# release candidate's load stores beside it. The resolve takes third-party
# packages from PyPI with every declared distribution held at its declared
# version; every declared distribution it installed is then reinstalled from
# the wheelhouse alone, whichever source the resolver chose.
RUN set -eu; \
    printf '%s\n' $CONSTRAINTS > /tmp/constraints.txt; \
    python3 -m venv /opt/market; \
    wheels="/dist/$CLI_WHEEL"; \
    for wheel in $DOMAIN_WHEELS; do wheels="$wheels /dist/$wheel"; done; \
    /opt/market/bin/pip install --find-links /dist --constraint /tmp/constraints.txt \
        $wheels pyinstaller==6.22.3; \
    installed=""; \
    for pin in $CONSTRAINTS; do \
        if /opt/market/bin/pip show --quiet "${pin%%==*}" >/dev/null 2>&1; then installed="$installed $pin"; fi; \
    done; \
    /opt/market/bin/pip install --no-index --no-deps --force-reinstall --find-links /dist $installed

WORKDIR /build
RUN set -eu; \
    module="${ENTRY_POINT%%:*}"; function="${ENTRY_POINT##*:}"; \
    printf 'from %s import %s\n\n%s()\n' "$module" "$function" "$function" > market.py; \
    /opt/market/bin/pyinstaller --onefile --name market $PYINSTALLER_OPTIONS market.py

# No validation suite runs the binary, so this is what exercises it: the frozen
# binary lists exactly the domains the installed CLI discovers, one per
# registered buyer-domain entry point. Discovery skips a domain that fails to
# load, saying so on stderr, so neither run may report a skipped domain.
RUN set -eu; \
    /opt/market/bin/market plugins > expected 2> expected.err; \
    ./dist/market plugins > frozen 2> frozen.err; \
    cat frozen; \
    if grep -h "skipping buyer domain" expected.err frozen.err >&2; then exit 1; fi; \
    count=$(/opt/market/bin/python -c "from importlib.metadata import entry_points; print(len(entry_points(group='market.buyer_domains')))"); \
    test "$(wc -l < expected)" -eq "$count" \
        || { echo "the installed CLI lists these, not one line per buyer-domain entry point ($count):" >&2; cat expected >&2; exit 1; }; \
    diff expected frozen \
        || { echo "the frozen binary lists other domains than the installed CLI" >&2; exit 1; }

FROM scratch AS binary
COPY --from=build /build/dist/market /market
