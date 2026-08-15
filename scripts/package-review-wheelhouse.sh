#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTFILE="${1:-${ROOT_DIR}/.snapshot/review-wheelhouse.tar.gz}"
PROJECTS="${REVIEW_PROJECTS:-}"
REVIEW_PYTHON="${REVIEW_PYTHON:-3.13}"
MARKETPLACE_SOURCE_COMMIT="${REVIEW_SOURCE_COMMIT:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
IDENTITY_WHEEL="arkhai_kit_identity-0.3.0-py3-none-any.whl"
HOSTED_CLIENT_WHEEL="arkhai_hosted_settlement_client-0.2.1-py3-none-any.whl"
HOSTED_MANIFEST="release-manifest.json"
HOSTED_TRUST="${ROOT_DIR}/manifests/hosted-settlement-v0.2.1-trust.json"
HOSTED_RELEASE_ARTIFACTS=(
  "${HOSTED_MANIFEST}"
  "${HOSTED_CLIENT_WHEEL}"
  "openapi-v0.2.1.json"
  "conformance-v0.2.1.json"
  "migrations-v5.json"
  "sbom.spdx.json"
  "provenance.intoto.json"
)

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
for forbidden in \
  "${ROOT_DIR}/.dist"/arkhai_hosted_settlement_e2e-*.whl \
  "${ROOT_DIR}/.dist"/arkhai_hosted_settlement_service-*.whl \
  "${ROOT_DIR}/.dist"/stripe-*.whl; do
  if [[ -e "${forbidden}" ]]; then
    echo "marketplace wheelhouse cannot contain hosted service/provider distribution: $(basename "${forbidden}")" >&2
    exit 2
  fi
done
cp -a "${ROOT_DIR}/.dist" "${BUNDLE_DIR}/wheelhouse"
for required in "${IDENTITY_WHEEL}" "${HOSTED_RELEASE_ARTIFACTS[@]}"; do
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
for artifact in "${HOSTED_RELEASE_ARTIFACTS[@]}"; do
  cp "${BUNDLE_DIR}/wheelhouse/${artifact}" "${BUNDLE_DIR}/release/"
done
uv run --no-project --with 'eth-account>=0.13,<0.14' \
  python "${ROOT_DIR}/scripts/verify-hosted-release.py" \
  --trust "${HOSTED_TRUST}" \
  --manifest "${BUNDLE_DIR}/release/${HOSTED_MANIFEST}" \
  --wheel "${BUNDLE_DIR}/release/${HOSTED_CLIENT_WHEEL}" \
  > "${BUNDLE_DIR}/release/verified-release.json"
uv run --no-project --python "${REVIEW_PYTHON}" python - \
  "${BUNDLE_DIR}" "${IDENTITY_WHEEL}" "${HOSTED_CLIENT_WHEEL}" \
  "${MARKETPLACE_SOURCE_COMMIT}" <<'PY'
import ast
import hashlib
import json
import re
from pathlib import Path
import sys
import zipfile

bundle = Path(sys.argv[1])
wheelhouse = bundle / "wheelhouse"
trust = json.loads((bundle / "release" / "hosted-settlement-trust.json").read_text())
manifest = json.loads((bundle / "release" / "release-manifest.json").read_text())
verified_release = json.loads(
    (bundle / "release" / "verified-release.json").read_text()
)
client_wheel_path = wheelhouse / sys.argv[3]
try:
    with zipfile.ZipFile(client_wheel_path) as archive:
        client_members = tuple(archive.namelist())
        entry_point_files = [
            name
            for name in client_members
            if name.endswith(".dist-info/entry_points.txt")
        ]
except zipfile.BadZipFile as exc:
    raise SystemExit(f"hosted client is not a readable wheel: {exc}") from exc
if entry_point_files:
    raise SystemExit("hosted client wheel must not contain seller entry-point metadata")
for member in client_members:
    normalized = member.lower()
    if normalized.startswith("hosted_settlement_service/") or normalized.startswith("stripe/"):
        raise SystemExit("hosted client wheel contains service/provider implementation")
    if normalized.startswith("hosted_settlement_client/") and any(
        part in {
            "authority",
            "database",
            "migrations",
            "providers",
            "recovery",
            "storage",
            "webhook",
            "webhooks",
        }
        for part in (Path(component).stem for component in Path(normalized).parts)
    ):
        raise SystemExit("hosted client wheel contains service/provider implementation")

expected_capabilities = [
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
    "conditional-escrow.v2",
    "stripe-connect-separate-charges-transfers.v2",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    "payer-profile.v1",
    "funding-authorization.v1",
    "funding-profile.card.v1",
    "funding-profile.us_bank_transfer.v1",
    "funding-profile.us_ach_debit.v1",
    "normalized-funding-reversal.v1",
    "operator-recovery-redaction.v1",
]
expected_identity = {
    "request_signature_protocol": "arkhai.hosted-request-signature.v2",
    "response_signature_protocol": "arkhai.hosted-response-signature.v2",
    "supported_identity_schemes": ["eip191", "ed25519"],
    "capabilities": expected_capabilities,
    "account_owner_admission_protocol": "arkhai.account-owner-admission.v1",
    "account_owner_rotation_protocol": "arkhai.account-owner-rotation.v1",
    "client_signer_api": "hosted_settlement_client.Signer",
    "seller_onboarding_api": "hosted_settlement_client.SellerOnboarding",
    "payer_profile_protocol": "arkhai.payer-profile.v1",
    "funding_authorization_protocol": "arkhai.funding-authorization.v1",
    "funding_profiles": ["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"],
}
if trust["contract_version"] != "arkhai.hosted-settlement-release.v2":
    raise SystemExit("hosted release trust does not pin identity-capable contract v2")
if trust["release_version"] != "0.2.1" or trust["api_version"] != "0.2.1":
    raise SystemExit("hosted release trust does not pin client/API 0.2.1")
if trust["schema_version"] != 5:
    raise SystemExit("hosted release trust does not pin schema 5")
if trust.get("required_capabilities") != expected_capabilities:
    raise SystemExit("hosted release trust does not pin exact expanded capabilities")
if trust.get("identity_contract") != expected_identity:
    raise SystemExit("hosted release trust does not pin the exact identity contract")
if manifest["payload"].get("identity_contract") != expected_identity:
    raise SystemExit("hosted release manifest does not provide the exact identity contract")

required_exports = {
    "CreatePayerProfileRequest",
    "FundingAuthorizationRequest",
    "FundingAuthorizationResult",
    "FundingProfile",
    "FundingProfileReadiness",
    "HostedSettlementAsyncClient",
    "HostedSettlementClient",
    "InstrumentListResult",
    "PayerProfileResult",
    "PayerSetupRequest",
    "PayerSetupResult",
}
with zipfile.ZipFile(client_wheel_path) as archive:
    init_tree = ast.parse(
        archive.read("hosted_settlement_client/__init__.py").decode("utf-8")
    )
    client_exports = set()
    for node in init_tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        ):
            client_exports.update(ast.literal_eval(node.value))
if missing := sorted(required_exports - client_exports):
    raise SystemExit(
        "hosted client wheel is missing expanded public models: " + ", ".join(missing)
    )

for wheel_path in sorted(wheelhouse.glob("*.whl")):
    if wheel_path == client_wheel_path:
        continue
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        lowered_names = tuple(name.lower() for name in names)
        if any(
            "hosted_settlement_service" in name
            or name.startswith("stripe/")
            or "/stripe/" in name
            for name in lowered_names
        ):
            raise SystemExit(
                f"marketplace wheel crosses hosted service/provider boundary: {wheel_path.name}"
            )
        for name in names:
            if not name.endswith(".py"):
                continue
            source = archive.read(name).decode("utf-8")
            if re.search(
                r"(?:sk_(?:test|live)_|rk_(?:test|live)_|whsec_|"
                r"\b(?:acct|cus|pm|pi|ch|tr|evt)_[A-Za-z0-9_]+)",
                source,
                re.IGNORECASE,
            ):
                raise SystemExit(
                    f"marketplace wheel contains credential/provider canary: {wheel_path.name}"
                )
            tree = ast.parse(source, filename=f"{wheel_path.name}:{name}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".", 1)[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = {node.module.split(".", 1)[0]}
                else:
                    roots = set()
                if roots.intersection({"hosted_settlement_service", "stripe"}):
                    raise SystemExit(
                        "marketplace wheel imports hosted service/provider module: "
                        f"{wheel_path.name}"
                    )
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in {"sign_request", "verify_response"}
                    and not name.startswith("market_identity/")
                ):
                    raise SystemExit(
                        "marketplace wheel copies hosted signature behavior: "
                        f"{wheel_path.name}"
                    )

consumer_commit = sys.argv[4]
if not re.fullmatch(r"[0-9a-f]{40}", consumer_commit):
    raise SystemExit("marketplace source commit must be an exact lowercase revision")
consumer_wheels = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(wheelhouse.glob("arkhai_*.whl"))
    if path != client_wheel_path
}

pins = {
    "schema_version": 2,
    "settlement_config_schema_version": 1,
    "producer_release": {
        "repository": "arkhai-io/stripe-settlement-service",
        "release_version": "0.2.1",
        "api_version": "0.2.1",
        "schema_version": 5,
        "funding_profiles": ["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"],
        "verification": verified_release,
        "capabilities": expected_capabilities,
        "client_wheel": {
            "filename": sys.argv[3],
            "sha256": hashlib.sha256(client_wheel_path.read_bytes()).hexdigest(),
            "entry_point_metadata": False,
        },
        "manifest": {
            "filename": "release-manifest.json",
            "sha256": hashlib.sha256(
                (bundle / "release" / "release-manifest.json").read_bytes()
            ).hexdigest(),
        },
    },
    "consumer_release": {
        "repository": "arkhai-io/simple-compute-market",
        "source_commit": consumer_commit,
        "wheels": consumer_wheels,
    },
    "identity_wheel": {
        "filename": sys.argv[2],
        "sha256": hashlib.sha256((wheelhouse / sys.argv[2]).read_bytes()).hexdigest(),
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
    ("arkhai-hosted-settlement-client", "0.2.1"),
):
    mentions = re.findall(rf'(?m)^\s*"{re.escape(name)}([^"]*)"', project_text)
    if mentions and any(value != f"=={version}" for value in mentions):
        raise SystemExit(f"{name} must be pinned exactly to {version}")

for required_name, required_version in (
    ("arkhai-kit-identity", "0.3.0"),
    ("arkhai-hosted-settlement-client", "0.2.1"),
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
    ("arkhai-hosted-settlement-client", "0.2.1", "hosted_settlement_client"),
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
