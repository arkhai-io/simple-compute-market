#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_FILE="${1:-${ROOT_DIR}/.snapshot/$(basename "${ROOT_DIR}")-review-wheelhouse.zip}"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required to locate and package the shared dependency cache" >&2
  exit 1
fi

UV_CACHE_SOURCE="${UV_CACHE_DIR:-$(uv cache dir)}"
if [[ ! -d "${UV_CACHE_SOURCE}" ]]; then
  echo "error: uv cache directory does not exist: ${UV_CACHE_SOURCE}" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT HUP INT TERM

BUNDLE_DIR="${TMP_DIR}/review-uv-cache"
mkdir -p "${BUNDLE_DIR}/manifests"

# Discover initialized uv projects from their existing virtual environments. The
# script deliberately contains no repository project-path knowledge.
mapfile -d '' VENV_DIRS < <(
  find "${ROOT_DIR}" \
    \( -path "${ROOT_DIR}/.git" -o -path "${ROOT_DIR}/.snapshot" -o -path '*/node_modules' \) -prune -o \
    -type d -name .venv -print0 \
    | sort -z
)

if (( ${#VENV_DIRS[@]} == 0 )); then
  echo "error: no initialized .venv directories found under ${ROOT_DIR}" >&2
  echo "Run the relevant project reinit/install targets before packaging review dependencies." >&2
  exit 1
fi

PROJECTS=()
for venv_dir in "${VENV_DIRS[@]}"; do
  project_dir="$(dirname "${venv_dir}")"
  if [[ ! -f "${project_dir}/pyproject.toml" || ! -f "${project_dir}/uv.lock" ]]; then
    continue
  fi

  if [[ "${project_dir}" == "${ROOT_DIR}" ]]; then
    project="."
    bundle_name="repo-root"
  else
    project="${project_dir#"${ROOT_DIR}/"}"
    bundle_name="${project//\//--}"
  fi

  cp "${project_dir}/pyproject.toml" "${BUNDLE_DIR}/manifests/${bundle_name}-pyproject.toml"
  cp "${project_dir}/uv.lock" "${BUNDLE_DIR}/manifests/${bundle_name}-uv.lock"

  if [[ -x "${venv_dir}/bin/python" ]]; then
    "${venv_dir}/bin/python" --version > "${BUNDLE_DIR}/manifests/${bundle_name}-python-version.txt" 2>&1 || true
  elif [[ -f "${venv_dir}/pyvenv.cfg" ]]; then
    cp "${venv_dir}/pyvenv.cfg" "${BUNDLE_DIR}/manifests/${bundle_name}-pyvenv.cfg"
  fi

  PROJECTS+=("${project}")
done

if (( ${#PROJECTS[@]} == 0 )); then
  echo "error: .venv directories were found, but none were adjacent to both pyproject.toml and uv.lock" >&2
  exit 1
fi

printf 'Packing shared uv cache from %s ...\n' "${UV_CACHE_SOURCE}"
tar \
  --exclude='*.lock' \
  --exclude='CACHEDIR.TAG' \
  -C "${UV_CACHE_SOURCE}" \
  -czf "${BUNDLE_DIR}/uv-cache.tar.gz" \
  .

if [[ -d "${ROOT_DIR}/.dist" ]]; then
  echo "Packing repository-built wheels from .dist ..."
  tar -C "${ROOT_DIR}/.dist" -czf "${BUNDLE_DIR}/repository-wheels.tar.gz" .
fi

uv --version > "${BUNDLE_DIR}/uv-version.txt"
uname -a > "${BUNDLE_DIR}/source-platform.txt"
printf '%s\n' "${UV_CACHE_SOURCE}" > "${BUNDLE_DIR}/source-cache-path.txt"

{
  cat <<'EOF_README'
# Offline review dependency cache

This archive contains one snapshot of uv's shared cache, rather than copied
virtual-environment `site-packages` trees. uv deduplicates package artifacts in
this cache, and can select or build artifacts appropriate for the review
machine's Python interpreter when the required cached wheel or source archive
is available.

## Initialized projects represented
EOF_README
  for project in "${PROJECTS[@]}"; do
    printf -- '- `%s`\n' "${project}"
  done

  cat <<'EOF_README'

The project list is discovered dynamically from `.venv` directories adjacent
to both `pyproject.toml` and `uv.lock`. It is diagnostic only: the shared cache
snapshot can contain artifacts used by more than one project.

## Use on the review machine

Extract the outer zip, then extract the cache into a writable directory:

```sh
mkdir -p /tmp/simple-compute-market-uv-cache
tar -xzf review-uv-cache/uv-cache.tar.gz \
  -C /tmp/simple-compute-market-uv-cache
```

If `repository-wheels.tar.gz` is present, extract it into the checked-out
repository's `.dist` directory:

```sh
mkdir -p .dist
tar -xzf /path/to/review-uv-cache/repository-wheels.tar.gz -C .dist
```

Run repository commands with the extracted cache and network access disabled:

```sh
export UV_CACHE_DIR=/tmp/simple-compute-market-uv-cache
export UV_OFFLINE=1
make test
```

A cache hit is platform- and Python-version-dependent. Pure-Python wheels are
portable, but native dependencies require either a compatible cached wheel or
a cached source distribution and all cached build dependencies. If uv reports
that a package is unavailable in offline mode, the source cache did not contain
an artifact usable by the review machine; the script does not silently access
the network to fill that gap.

The cache may include artifacts from unrelated local uv work because uv uses a
shared cache. It must be treated as review-only input, not as a deployment
artifact or a reproducible package index.
EOF_README
} > "${BUNDLE_DIR}/README.md"

mkdir -p "$(dirname "${OUTPUT_FILE}")"
rm -f "${OUTPUT_FILE}"
(
  cd "${TMP_DIR}"
  zip -q -0 "${OUTPUT_FILE}" review-uv-cache/uv-cache.tar.gz
  if [[ -f review-uv-cache/repository-wheels.tar.gz ]]; then
    zip -q -0 "${OUTPUT_FILE}" review-uv-cache/repository-wheels.tar.gz
  fi
  zip -qr "${OUTPUT_FILE}" \
    review-uv-cache/manifests \
    review-uv-cache/README.md \
    review-uv-cache/uv-version.txt \
    review-uv-cache/source-platform.txt \
    review-uv-cache/source-cache-path.txt
)

size="$(du -sh "${OUTPUT_FILE}" | cut -f1)"
echo "Done: ${OUTPUT_FILE} (${size}; ${#PROJECTS[@]} initialized projects; shared cache packaged once)"
