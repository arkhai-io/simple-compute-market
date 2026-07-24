#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTFILE="${1:-${ROOT_DIR}/.snapshot/review-wheelhouse.tar.gz}"
PROJECTS="${REVIEW_PROJECTS:-}"
REVIEW_PYTHON="${REVIEW_PYTHON:-3.13}"

if [[ -z "${PROJECTS// }" ]]; then
  echo "REVIEW_PROJECTS must list one or more repository-relative Python projects" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
BUNDLE_DIR="${TMP_DIR}/bundle"
CACHE_DIR="${BUNDLE_DIR}/uv-cache"
ENV_DIR="${TMP_DIR}/envs"
mkdir -p "${BUNDLE_DIR}/projects" "${CACHE_DIR}" "${ENV_DIR}" "$(dirname "${OUTFILE}")"

if [[ ! -d "${ROOT_DIR}/.dist" ]]; then
  echo ".dist is missing; invoke this script through 'make review-wheelhouse'" >&2
  exit 2
fi
cp -a "${ROOT_DIR}/.dist" "${BUNDLE_DIR}/wheelhouse"

normalize_project_copy() {
  local project_copy_dir="$1"
  local relative_wheelhouse
  relative_wheelhouse="$(uv run --no-project --python "${REVIEW_PYTHON}" python - "${project_copy_dir}" "${BUNDLE_DIR}/wheelhouse" <<'PY'
import os
import sys
print(os.path.relpath(sys.argv[2], sys.argv[1]))
PY
)"

  uv run --no-project --python "${REVIEW_PYTHON}" python - \
    "${project_copy_dir}/pyproject.toml" \
    "${project_copy_dir}/uv.lock" \
    "${relative_wheelhouse}" \
    "${BUNDLE_DIR}/wheelhouse" <<'PY'
from pathlib import Path
import re
import sys

pyproject = Path(sys.argv[1])
lockfile = Path(sys.argv[2])
relative_wheelhouse = sys.argv[3].replace("\\", "/")
wheelhouse = Path(sys.argv[4])

# The source checkout may use editable path overrides for repository packages.
# Those paths do not exist in the portable review bundle; the copied lockfile
# already pins the corresponding built wheels, so remove only the copied
# [tool.uv.sources] table and leave the source project untouched.
project_text = pyproject.read_text()
project_text = re.sub(
    r"(?ms)^\[tool\.uv\.sources\]\n.*?(?=^\[[^\n]+\]\n|\Z)",
    "",
    project_text,
)
pyproject.write_text(project_text)

text = lockfile.read_text()

# Repository-owned wheels are resolved from .dist during local development.
# Point copied registry records at the bundled wheelhouse and keep wheel paths
# relative so the archive can be extracted anywhere.
text = re.sub(
    r'source = \{ registry = "[^"]*\.dist" \}',
    f'source = {{ registry = "{relative_wheelhouse}" }}',
    text,
)
text = re.sub(
    r'\{ path = "[^"]*\.dist/([^"/]+\.whl)" \}',
    r'{ path = "\1" }',
    text,
)

# uv lockfiles preserve repository workspace and editable sources independently
# of pyproject.toml. Convert each non-root repository package to the matching
# bundled wheel so copied locks do not depend on the original checkout layout.
def normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()

def wheel_for(name: str, version: str) -> str:
    prefix = f"{normalized_distribution(name)}-{version}-"
    matches = [
        path.name
        for path in wheelhouse.glob("*.whl")
        if path.name.lower().startswith(prefix)
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one bundled wheel for {name}=={version}, found {matches}"
        )
    return matches[0]

package_pattern = re.compile(r"(?ms)^\[\[package\]\]\n.*?(?=^\[\[package\]\]\n|\Z)")

def normalize_package(match: re.Match[str]) -> str:
    block = match.group(0)
    name_match = re.search(r'^name = "([^"]+)"$', block, re.MULTILINE)
    version_match = re.search(r'^version = "([^"]+)"$', block, re.MULTILINE)
    source_match = re.search(
        r'^source = \{ (editable|directory) = "([^"]+)" \}$',
        block,
        re.MULTILINE,
    )
    if not (name_match and version_match and source_match):
        return block

    source_path = source_match.group(2)
    # Keep the selected project itself local. Offline recreation uses
    # --no-install-project; every repository dependency is wheel-backed.
    if source_path == ".":
        return block

    wheel = wheel_for(name_match.group(1), version_match.group(1))
    replacement = (
        f'source = {{ registry = "{relative_wheelhouse}" }}\n'
        f'wheels = [\n    {{ path = "{wheel}" }},\n]'
    )
    block = block[: source_match.start()] + replacement + block[source_match.end() :]
    return block

text = package_pattern.sub(normalize_package, text)

# Dependency metadata may also retain editable/directory hints. Once the package
# records above are wheel-backed these hints are non-portable and unnecessary.
text = re.sub(r', (?:editable|directory) = "[^"]+"', '', text)
lockfile.write_text(text)
PY
}

: > "${BUNDLE_DIR}/projects.txt"
for project in ${PROJECTS}; do
  project_dir="${ROOT_DIR}/${project}"
  if [[ ! -f "${project_dir}/pyproject.toml" || ! -f "${project_dir}/uv.lock" ]]; then
    echo "review project lacks pyproject.toml or uv.lock: ${project}" >&2
    exit 2
  fi

  echo "${project}" >> "${BUNDLE_DIR}/projects.txt"
  project_copy_dir="${BUNDLE_DIR}/projects/${project}"
  mkdir -p "${project_copy_dir}"
  cp "${project_dir}/pyproject.toml" "${project_dir}/uv.lock" "${project_copy_dir}/"
  normalize_project_copy "${project_copy_dir}"

  # Populate an isolated cache for one explicit interpreter ABI. Reusing an
  # existing .venv can hide missing artifacts, so each project gets a clean
  # temporary environment. This step installs dependencies but runs no tests.
  safe_project="${project//\//_}"
  (
    cd "${project_dir}"
    UV_CACHE_DIR="${CACHE_DIR}" \
    UV_PROJECT_ENVIRONMENT="${ENV_DIR}/${safe_project}" \
      uv sync \
        --python "${REVIEW_PYTHON}" \
        --frozen \
        --dev \
        --find-links "${ROOT_DIR}/.dist"
  )
done

cat > "${BUNDLE_DIR}/README.txt" <<EOF_README
This archive contains:
- wheelhouse/: clean repository-built wheels from 'make dist-clean dist'
- uv-cache/: external artifacts for CPython ${REVIEW_PYTHON}
- projects/: pyproject.toml and portable copied uv.lock files
- projects.txt: selected project paths

The source pyproject.toml and uv.lock files are not modified. Editable repository
path overrides are removed only from copied project manifests. Repository-owned
.dist references in copied lockfiles are rewritten to relative wheelhouse/ paths.
The cache is populated through clean temporary environments, and no tests are run.

To recreate a selected environment offline, use CPython ${REVIEW_PYTHON}, set
UV_CACHE_DIR to the extracted uv-cache directory and UV_OFFLINE=1, then run:

  uv sync --python ${REVIEW_PYTHON} --frozen --dev --no-install-project

from the corresponding extracted projects/<path> directory.
EOF_README

rm -f "${OUTFILE}"
tar -C "${BUNDLE_DIR}" -czf "${OUTFILE}" .

echo "Created ${OUTFILE} for CPython ${REVIEW_PYTHON}"
