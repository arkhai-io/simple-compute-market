"""Assemble the hosted protected-run credential payload locally.

The harness consumes one payload from a credential broker. No broker exists in
this repository, and a development run needs no OIDC and no self-hosted runner
to obtain one -- provider credentials come from the operator's own file, and the
identity credentials are ephemeral keys generated here.

The output is the documented broker response shape
(``docs/development/HOSTED_CREDENTIAL_PAYLOAD.md``), so a broker written later
substitutes for this without the harness changing.

Nothing here writes a provider credential anywhere but the private run
directory it is told to use.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent


class CredentialAssemblyError(RuntimeError):
    """The operator's inputs cannot produce a usable payload."""


def _provider_values(path: Path) -> dict[str, str]:
    """Read the operator's own provider file; never copy it anywhere."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CredentialAssemblyError(f"provider credential file is unreadable: {path}") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    secret = values.get("STRIPE_SECRET_KEY", "")
    account = values.get("STRIPE_CONNECTED_ACCOUNT_ID", "")
    if not secret or not account:
        raise CredentialAssemblyError(
            "provider file must define STRIPE_SECRET_KEY and STRIPE_CONNECTED_ACCOUNT_ID"
        )
    if secret.startswith(("sk_live_", "rk_live_")):
        raise CredentialAssemblyError("live provider credentials are prohibited")
    if not secret.startswith(("sk_test_", "rk_test_")):
        raise CredentialAssemblyError("a test-mode provider credential is required")
    if not account.startswith("acct_"):
        raise CredentialAssemblyError("connected account identity has an invalid form")
    return {"stripe_restricted_key": secret, "connected_account_id": account}


def _credential(scheme: str) -> str:
    """One ephemeral private key, encoded the way its scheme expects."""

    raw = secrets.token_bytes(32)
    if scheme == "eip191":
        return "0x" + raw.hex()
    if scheme == "ed25519":
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    raise CredentialAssemblyError(f"unsupported identity scheme {scheme!r}")


def _identifier(scheme: str, credential: str) -> str:
    """Derive the public identity, so the payload never carries both halves."""

    from market_identity import create_signer

    return create_signer(scheme, credential).identity.identifier


def assemble_payload(
    *,
    provider_path: Path,
    scheme: str = "eip191",
    account_ref: str = "hosted-stripe-test-local",
    authority_environment: str = "hosted-stripe-test-local",
    expires_in_seconds: int = 3600,
    now_unix: int,
    authority_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the documented payload from local inputs alone."""

    provider = _provider_values(provider_path)
    evidence_credential = _credential(scheme)
    payload: dict[str, Any] = {
        "expires_at_unix": now_unix + expires_in_seconds,
        **provider,
        "account_ref": account_ref,
        "authority_environment": authority_environment,
        # A development run pulls the released image with the operator's own
        # docker login rather than a brokered token.
        "registry_read_token": "",
        "buyer_identity_credential": _credential(scheme),
        "buyer_identity_scheme": scheme,
        "storefront_identity_credential": _credential(scheme),
        "admin_identity_credential": _credential(scheme),
        "evidence_signer_credential": evidence_credential,
        "evidence_signer_scheme": scheme,
        "evidence_signer_identifier": _identifier(scheme, evidence_credential),
        "registry_a_identity_credential": _credential(scheme),
        "registry_b_identity_credential": _credential(scheme),
        "provisioning_identity_credential": _credential(scheme),
        "registry_admin_api_key": secrets.token_urlsafe(32),
        "registry_bootstrap_api_key": secrets.token_urlsafe(32),
        "authority_env": dict(authority_env or {}),
    }
    return payload


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def materialize(payload: dict[str, Any], directory: Path) -> dict[str, str]:
    """Write the files and return the environment the harness expects.

    Same layout the workflow builds from a brokered payload, so the driver
    cannot tell the difference.
    """

    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(stat.S_IRWXU)
    authority_env = payload["authority_env"]
    _write_private(
        directory / "authority.env",
        "".join(f"{key}={value}\n" for key, value in sorted(authority_env.items())),
    )
    _write_private(directory / "registry-a", payload["registry_a_identity_credential"])
    _write_private(directory / "registry-b", payload["registry_b_identity_credential"])
    _write_private(
        directory / "provisioning.env",
        f"ARKHAI_IDENTITY_CREDENTIAL={payload['provisioning_identity_credential']}\n",
    )
    _write_private(
        directory / "storefront.env",
        f"ARKHAI_IDENTITY_CREDENTIAL={payload['storefront_identity_credential']}\n",
    )
    _write_private(directory / "storefront.secrets.toml", "")
    return {
        "STRIPE_SECRET_KEY": payload["stripe_restricted_key"],
        "STRIPE_CONNECTED_ACCOUNT_ID": payload["connected_account_id"],
        "HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_CREDENTIAL": payload[
            "buyer_identity_credential"
        ],
        "HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_SCHEME": payload["buyer_identity_scheme"],
        "HOSTED_SETTLEMENT_E2E_STOREFRONT_IDENTITY_CREDENTIAL": payload[
            "storefront_identity_credential"
        ],
        "HOSTED_SETTLEMENT_E2E_ADMIN_IDENTITY_CREDENTIAL": payload[
            "admin_identity_credential"
        ],
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_CREDENTIAL": payload[
            "evidence_signer_credential"
        ],
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_SCHEME": payload["evidence_signer_scheme"],
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_IDENTIFIER": payload[
            "evidence_signer_identifier"
        ],
        "VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE": str(directory / "registry-a"),
        "VMS_REGISTRY_B_IDENTITY_CREDENTIAL_FILE": str(directory / "registry-b"),
        "VMS_PROVISIONING_IDENTITY_ENV_FILE": str(directory / "provisioning.env"),
        "VMS_BOB_IDENTITY_ENV_FILE": str(directory / "storefront.env"),
        "VMS_BOB_STOREFRONT_SECRETS_FILE": str(directory / "storefront.secrets.toml"),
        "VMS_REGISTRY_ADMIN_API_KEY": payload["registry_admin_api_key"],
        "VMS_REGISTRY_BOOTSTRAP_API_KEY": payload["registry_bootstrap_api_key"],
        "HOSTED_STRIPE_TEST_ACCOUNT_REF": payload["account_ref"],
        "HOSTED_STRIPE_TEST_AUTHORITY_ENVIRONMENT": payload["authority_environment"],
        "HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE": str(directory / "authority.env"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-file", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--scheme", choices=("eip191", "ed25519"), default="eip191")
    parser.add_argument("--account-ref", default="hosted-stripe-test-local")
    parser.add_argument("--authority-environment", default="hosted-stripe-test-local")
    parser.add_argument(
        "--authority-env",
        type=Path,
        help="Optional base environment for the hosted authority.",
    )
    parser.add_argument(
        "--print",
        dest="print_env",
        action="store_true",
        help="Print the assembled environment as shell exports.",
    )
    args = parser.parse_args()
    authority_env: dict[str, str] = {}
    if args.authority_env is not None:
        for line in args.authority_env.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, value = stripped.partition("=")
                authority_env[key.strip()] = value.strip()
    try:
        payload = assemble_payload(
            provider_path=args.provider_file,
            scheme=args.scheme,
            account_ref=args.account_ref,
            authority_environment=args.authority_environment,
            now_unix=int(os.environ.get("HOSTED_CREDENTIAL_NOW_UNIX") or _now()),
            authority_env=authority_env,
        )
        environment = materialize(payload, args.directory)
    except CredentialAssemblyError as exc:
        parser.error(str(exc))
    if args.print_env:
        for key, value in environment.items():
            print(f"export {key}={_quote(value)}")
    return 0


def _now() -> int:
    import time

    return int(time.time())


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO_ROOT))
    raise SystemExit(main())
