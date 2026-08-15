#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTFILE="${1:-${ROOT_DIR}/.snapshot/review-wheelhouse.tar.gz}"
PROJECTS="${REVIEW_PROJECTS:-}"
REVIEW_PYTHON="${REVIEW_PYTHON:-3.13}"
IDENTITY_WHEEL="arkhai_kit_identity-0.3.0-py3-none-any.whl"
HOSTED_CLIENT_WHEEL="arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl"
HOSTED_MANIFEST="release-manifest.json"
HOSTED_TRUST="${ROOT_DIR}/manifests/hosted-settlement-v0.1.0-trust.json"

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
for forbidden in "${ROOT_DIR}/.dist"/arkhai_hosted_settlement_e2e-*.whl; do
  if [[ -e "${forbidden}" ]]; then
    echo "hosted production wheelhouse cannot contain fixture distribution: $(basename "${forbidden}")" >&2
    exit 2
  fi
done
cp -a "${ROOT_DIR}/.dist" "${BUNDLE_DIR}/wheelhouse"
for required in "${IDENTITY_WHEEL}" "${HOSTED_CLIENT_WHEEL}" "${HOSTED_MANIFEST}"; do
  if [[ ! -f "${BUNDLE_DIR}/wheelhouse/${required}" ]]; then
    echo "required pinned release artifact is missing: ${required}" >&2
    exit 2
  fi
done
if [[ ! -f "${HOSTED_TRUST}" ]]; then
  echo "hosted release trust input is missing: ${HOSTED_TRUST}" >&2
  exit 2
fi
mkdir -p "${BUNDLE_DIR}/release"
cp "${HOSTED_TRUST}" "${BUNDLE_DIR}/release/hosted-settlement-trust.json"
cp "${BUNDLE_DIR}/wheelhouse/${HOSTED_MANIFEST}" "${BUNDLE_DIR}/release/"
uv run --no-project --python "${REVIEW_PYTHON}" python - \
  "${BUNDLE_DIR}" "${IDENTITY_WHEEL}" "${HOSTED_CLIENT_WHEEL}" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import zipfile

bundle = Path(sys.argv[1])
wheelhouse = bundle / "wheelhouse"
trust = json.loads((bundle / "release" / "hosted-settlement-trust.json").read_text())
manifest = json.loads((bundle / "release" / "release-manifest.json").read_text())
client_wheel_path = wheelhouse / sys.argv[3]
try:
    with zipfile.ZipFile(client_wheel_path) as archive:
        entry_point_files = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/entry_points.txt")
        ]
except zipfile.BadZipFile as exc:
    raise SystemExit(f"hosted client is not a readable wheel: {exc}") from exc
if entry_point_files:
    raise SystemExit("hosted client wheel must not contain seller entry-point metadata")

expected_identity = {
    "request_signature_protocol": "arkhai.hosted-request-signature.v2",
    "response_signature_protocol": "arkhai.hosted-response-signature.v2",
    "supported_identity_schemes": ["eip191", "ed25519"],
    "capabilities": [
        "scheme-tagged-identities.v1",
        "account-owner-admission.v1",
        "account-owner-rotation.v1",
        "account-owner-retirement.v1",
        "signer-injected-client.v1",
        "provider-neutral-seller-onboarding.v1",
    ],
    "account_owner_admission_protocol": "arkhai.account-owner-admission.v1",
    "account_owner_rotation_protocol": "arkhai.account-owner-rotation.v1",
    "client_signer_api": "hosted_settlement_client.Signer",
    "seller_onboarding_api": "hosted_settlement_client.SellerOnboarding",
}
if trust["contract_version"] != "arkhai.hosted-settlement-release.v2":
    raise SystemExit("hosted release trust does not pin identity-capable contract v2")
if trust["schema_version"] != 4:
    raise SystemExit("hosted release trust does not pin schema 4")
if trust.get("identity_contract") != expected_identity:
    raise SystemExit("hosted release trust does not pin the exact identity contract")
if manifest["payload"].get("identity_contract") != expected_identity:
    raise SystemExit("hosted release manifest does not provide the exact identity contract")

pins = {
    "schema_version": 1,
    "settlement_config_schema_version": 1,
    "identity_wheel": {
        "filename": sys.argv[2],
        "sha256": hashlib.sha256((wheelhouse / sys.argv[2]).read_bytes()).hexdigest(),
    },
    "hosted_client_wheel": {
        "filename": sys.argv[3],
        "sha256": hashlib.sha256(client_wheel_path.read_bytes()).hexdigest(),
        "entry_point_metadata": False,
    },
    "hosted_release_manifest": {
        "filename": "release-manifest.json",
        "sha256": hashlib.sha256(
            (bundle / "release" / "release-manifest.json").read_bytes()
        ).hexdigest(),
    },
}
(bundle / "release" / "artifact-pins.json").write_text(
    json.dumps(pins, indent=2, sort_keys=True) + "\n"
)
PY

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
    if not matches:
        # A non-root editable/directory record without a bundled release is
        # repository leakage, not a missing external dependency. Report it
        # before attempting to normalize the record into a wheel source.
        raise SystemExit("portable review lock retains repository source paths")
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

source_leaks = [
    path
    for path in re.findall(
        r'^source = \{ (?:editable|directory) = "([^"]+)" \}$',
        text,
        re.MULTILINE,
    )
    if path != "."
]
if source_leaks:
    raise SystemExit("portable review lock retains repository source paths")

project_text = pyproject.read_text()
project_name_match = re.search(r'(?m)^name = "([^"]+)"$', project_text)
project_name = project_name_match.group(1) if project_name_match else None
for name, version in (
    ("arkhai-kit-identity", "0.3.0"),
    ("arkhai-hosted-settlement-client", "0.1.0"),
):
    mentions = re.findall(rf'(?m)^\s*"{re.escape(name)}([^"]*)"', project_text)
    if mentions and any(value != f"=={version}" for value in mentions):
        raise SystemExit(f"{name} must be pinned exactly to {version}")

for required_name, required_version in (
    ("arkhai-kit-identity", "0.3.0"),
    ("arkhai-hosted-settlement-client", "0.1.0"),
):
    if required_name == project_name:
        continue
    for match in package_pattern.finditer(text):
        block = match.group(0)
        name_match = re.search(r'^name = "([^"]+)"$', block, re.MULTILINE)
        if name_match is None or name_match.group(1) != required_name:
            continue
        if f'version = "{required_version}"' not in block:
            raise SystemExit(f"lock does not pin {required_name}=={required_version}")
        if "editable =" in block or "directory =" in block:
            raise SystemExit(f"lock resolves {required_name} from repository source")

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

  # Populate from the portable copy, not the source project. Installing only
  # dependencies proves the rewritten lock is self-contained and cannot fall
  # back to editable repository sources.
  safe_project="${project//\//_}"
  (
    cd "${project_copy_dir}"
    UV_CACHE_DIR="${CACHE_DIR}" \
    UV_PROJECT_ENVIRONMENT="${ENV_DIR}/${safe_project}" \
      uv sync \
        --python "${REVIEW_PYTHON}" \
        --frozen \
        --dev \
        --no-install-project \
        --find-links "${BUNDLE_DIR}/wheelhouse"
  )
  "${ENV_DIR}/${safe_project}/bin/python" - "${project_copy_dir}/pyproject.toml" <<'PY'
import importlib
import importlib.metadata
from pathlib import Path
import sys
import tomllib

project = tomllib.loads(Path(sys.argv[1]).read_text())
requirements = tuple(project.get("project", {}).get("dependencies", ()))
for distribution, version, module in (
    ("arkhai-kit-identity", "0.3.0", "market_identity"),
    ("arkhai-hosted-settlement-client", "0.1.0", "hosted_settlement_client"),
):
    if not any(value.startswith(distribution) for value in requirements):
        continue
    installed = importlib.metadata.version(distribution)
    if installed != version:
        raise SystemExit(f"{distribution} installed {installed}, expected {version}")
    importlib.import_module(module)
PY
done

cat > "${BUNDLE_DIR}/README.txt" <<EOF_README
This archive contains:
- wheelhouse/: clean repository-built wheels, including the exact identity kit
  and manifest-pinned hosted client
- release/: hosted trust/manifest plus SHA-256 pins for release inputs
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
