ARG PYTHON_VERSION=3.13

# Built with the repository root as its context: make build-payments-lane-double
# in tools/.

# Stage 1: install the committed lock, unchanged, and the double itself.
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=10

# The project's pyproject and lock sit at the same depth below /repo as below the
# repository root, so the lock's relative wheelhouse path resolves to /repo/.dist.
# uv_project.py derives the internal packages from the lock and reinstalls them, so
# a cached build of a same-version wheel is never reused. The double installs
# editable from its source, which the runtime stage copies to the same path.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY tools/payments-lane-double/pyproject.toml tools/payments-lane-double/uv.lock tools/payments-lane-double/README.md /repo/tools/payments-lane-double/
COPY tools/payments-lane-double/src /repo/tools/payments-lane-double/src
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/tools/payments-lane-double -- --no-dev

# The leaf key is never committed: the repository's secret gate refuses a private
# key block. The lane CA's generator, in the controls project, derives it from a
# public seed, so this writes the same bytes on every build, matching the
# committed leaf certificate.
COPY tools/lane-double-controls/tls/generate.py /repo/tools/lane-double-controls/tls/generate.py
RUN mkdir /repo/tls && \
    /repo/tools/payments-lane-double/.venv/bin/python /repo/tools/lane-double-controls/tls/generate.py /repo/tls

# Stage 2: the runtime, as an unprivileged user.
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 appuser

COPY --from=builder /repo/tools/payments-lane-double/.venv /repo/tools/payments-lane-double/.venv
COPY --from=builder /repo/tools/payments-lane-double/src /repo/tools/payments-lane-double/src
# The committed fixtures and certificates and the generated leaf key, public
# development values, at the paths the double reads by default, so a lane runs it
# with no mounts. A deployment supplying its own server certificate mounts it over
# tls/double.pem and tls/double.key.pem.
COPY tools/payments-lane-double/fixtures/accounts.toml /opt/payments-lane-double/fixtures/
COPY tools/lane-double-controls/tls/lane-ca.pem /opt/payments-lane-double/tls/lane-ca.pem
COPY tools/lane-double-controls/tls/payments-double.pem /opt/payments-lane-double/tls/double.pem
COPY --from=builder /repo/tls/payments-double.key.pem /opt/payments-lane-double/tls/double.key.pem
ENV PATH="/repo/tools/payments-lane-double/.venv/bin:$PATH"

USER appuser
EXPOSE 8443
# The probe trusts the lane CA alone, as every caller of the double does.
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=12 \
  CMD curl --fail --silent --cacert /opt/payments-lane-double/tls/lane-ca.pem https://localhost:8443/health || exit 1
CMD ["python", "-m", "payments_lane_double"]
