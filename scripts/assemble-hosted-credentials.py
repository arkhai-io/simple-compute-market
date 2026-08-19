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


#: Identities the storefront configuration pins that a local run must own. Each
#: is generated in the scheme the template declares for it, and the template is
#: rewritten to the generated public identity -- the broker's equivalent is
#: holding the private keys that match a committed configuration.
_CONFIG_ROLES = (
    ("storefront_identity_credential", ("Identity", "principal")),
    ("provisioning_identity_credential", ("provisioning", "identity")),
    ("registry_a_identity_credential", ("registry", "authorities", 0)),
    ("registry_b_identity_credential", ("registry", "authorities", 1)),
)


def _template_principal(document: dict, path: tuple) -> tuple[str, str]:
    """Read one pinned (scheme, identifier) out of the storefront template."""

    if path == ("Identity", "principal"):
        node = document["Identity"]["principal"]
        return str(node["scheme"]), str(node["identifier"])
    if path == ("provisioning", "identity"):
        node = document["provisioning"]["identity"]["principals"][0]
        return str(node["scheme"]), str(node["identifier"])
    authorities = document["registry"]["authorities"]
    urls = list(document["registry"]["urls"])
    node = authorities[urls[path[2]]]["principals"][0]
    return str(node["scheme"]), str(node["identifier"])


def derive_storefront_config(
    template_text: str,
    *,
    authority_scheme: str,
    authority_credential: str,
) -> tuple[str, dict[str, str]]:
    """Rewrite the pinned identities to keys this run actually holds.

    Returns the rewritten configuration and the credentials generated for it.
    Replacement is by exact identifier string, so everything else in the
    operator's template survives untouched.
    """

    import tomllib

    document = tomllib.loads(template_text)
    credentials: dict[str, str] = {}
    replacements: list[tuple[str, str]] = []
    for role, path in _CONFIG_ROLES:
        scheme, existing = _template_principal(document, path)
        credential = _credential(scheme)
        credentials[role] = credential
        replacements.append((existing, _identifier(scheme, credential)))
    # The storefront trusts the authority whose responses it verifies, which is
    # the runtime authority this run generates rather than a released one.
    settlement_authority = document["Settlement"]["stripe"]["authority"]["principals"][0]
    replacements.append(
        (
            str(settlement_authority["identifier"]),
            _identifier(authority_scheme, authority_credential),
        )
    )
    rewritten = template_text
    for existing, generated in replacements:
        if existing not in rewritten:
            raise CredentialAssemblyError(
                "storefront template does not contain a pinned identity it declares"
            )
        rewritten = rewritten.replace(existing, generated)
    return rewritten, credentials


def assemble_payload(
    *,
    provider_path: Path,
    scheme: str = "eip191",
    account_ref: str = "hosted-stripe-test-local",
    authority_environment: str = "hosted-stripe-test-local",
    expires_in_seconds: int = 3600,
    now_unix: int,
    authority_env: dict[str, str] | None = None,
    storefront_config_template: Path | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Build the documented payload, and the configuration it is consistent with.

    Returns the payload and, when a storefront template is supplied, the
    rewritten configuration whose pinned identities this run holds the keys for.
    """

    provider = _provider_values(provider_path)
    evidence_credential = _credential(scheme)
    # The hosted authority signs with its own key, which the harness requires to
    # be independent of the release authority. Generated here so a development
    # run needs nothing beyond the operator's provider file.
    authority_credential = _credential(scheme)
    base_authority_env = {
        "HOSTED_SETTLEMENT_AUTHORITY_ID": authority_environment,
        "HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME": scheme,
        "HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY": authority_credential,
    }
    derived_config: str | None = None
    config_credentials: dict[str, str] = {}
    if storefront_config_template is not None:
        derived_config, config_credentials = derive_storefront_config(
            storefront_config_template.read_text(encoding="utf-8"),
            authority_scheme=scheme,
            authority_credential=authority_credential,
        )
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
        "storefront_identity_credential": config_credentials.get("storefront_identity_credential") or _credential(scheme),
        "admin_identity_credential": _credential(scheme),
        "evidence_signer_credential": evidence_credential,
        "evidence_signer_scheme": scheme,
        "evidence_signer_identifier": _identifier(scheme, evidence_credential),
        "registry_a_identity_credential": config_credentials.get("registry_a_identity_credential") or _credential(scheme),
        "registry_b_identity_credential": config_credentials.get("registry_b_identity_credential") or _credential(scheme),
        "provisioning_identity_credential": config_credentials.get("provisioning_identity_credential") or _credential(scheme),
        "registry_admin_api_key": secrets.token_urlsafe(32),
        "registry_bootstrap_api_key": secrets.token_urlsafe(32),
        # Operator-supplied entries win, so a real authority environment can
        # replace the generated identity wholesale.
        "authority_env": {**base_authority_env, **dict(authority_env or {})},
    }
    return payload, derived_config


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def materialize(
    payload: dict[str, Any],
    directory: Path,
    derived_config: str | None = None,
) -> dict[str, str]:
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
    storefront_config: dict[str, str] = {}
    if derived_config is not None:
        config_path = directory / "storefront.toml"
        _write_private(config_path, derived_config)
        storefront_config["HOSTED_STRIPE_TEST_STOREFRONT_CONFIG"] = str(config_path)
    return {
        **storefront_config,
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
        "--storefront-config-template",
        type=Path,
        help="Storefront configuration whose pinned identities this run adopts.",
    )
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
        payload, derived_config = assemble_payload(
            storefront_config_template=args.storefront_config_template,
            provider_path=args.provider_file,
            scheme=args.scheme,
            account_ref=args.account_ref,
            authority_environment=args.authority_environment,
            now_unix=int(os.environ.get("HOSTED_CREDENTIAL_NOW_UNIX") or _now()),
            authority_env=authority_env,
        )
        environment = materialize(payload, args.directory, derived_config)
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
