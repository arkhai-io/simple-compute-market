"""Local assembly stands in for the broker without weakening anything."""

from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "assemble-hosted-credentials.py"
_SPEC = importlib.util.spec_from_file_location("assemble_hosted_credentials", _MODULE_PATH)
assembler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(assembler)

#: Every key the workflow reads out of a brokered response.
_BROKER_KEYS = {
    "expires_at_unix",
    "stripe_restricted_key",
    "connected_account_id",
    "account_ref",
    "authority_environment",
    "registry_read_token",
    "buyer_identity_credential",
    "buyer_identity_scheme",
    "storefront_identity_credential",
    "admin_identity_credential",
    "evidence_signer_credential",
    "evidence_signer_scheme",
    "evidence_signer_identifier",
    "registry_a_identity_credential",
    "registry_b_identity_credential",
    "provisioning_identity_credential",
    "registry_admin_api_key",
    "registry_bootstrap_api_key",
    "authority_env",
}


def _provider_file(
    tmp_path: Path,
    secret: str = "sk_test_" + "a" * 32,
    name: str = "provider.env",
) -> Path:
    path = tmp_path / name
    path.write_text(
        f"STRIPE_SECRET_KEY={secret}\nSTRIPE_CONNECTED_ACCOUNT_ID=acct_1TestAccount\n",
        encoding="utf-8",
    )
    return path


def _payload(tmp_path: Path, **overrides):
    arguments = {
        "provider_path": _provider_file(tmp_path),
        "now_unix": 1_700_000_000,
        "authority_env": {"HOSTED_SETTLEMENT_DATABASE_URL": "sqlite:///authority.db"},
    }
    arguments.update(overrides)
    payload, _ = assembler.assemble_payload(**arguments)
    return payload


def test_the_payload_has_exactly_the_shape_the_workflow_consumes(tmp_path) -> None:
    payload = _payload(tmp_path)

    assert set(payload) == _BROKER_KEYS
    assert payload["expires_at_unix"] == 1_700_000_000 + 3600
    assert payload["buyer_identity_scheme"] in {"eip191", "ed25519"}
    # It round-trips as the JSON a broker would serve.
    assert json.loads(json.dumps(payload)) == payload


def test_generated_identities_are_usable_and_distinct(tmp_path) -> None:
    from market_identity import create_signer

    payload = _payload(tmp_path)
    credentials = [
        payload[name]
        for name in (
            "buyer_identity_credential",
            "storefront_identity_credential",
            "admin_identity_credential",
            "evidence_signer_credential",
            "registry_a_identity_credential",
            "registry_b_identity_credential",
            "provisioning_identity_credential",
        )
    ]

    assert len(set(credentials)) == len(credentials)
    for credential in credentials:
        create_signer(payload["buyer_identity_scheme"], credential)
    # The identifier is derived, so the payload never carries both halves of a
    # key pair inconsistently.
    signer = create_signer(
        payload["evidence_signer_scheme"], payload["evidence_signer_credential"]
    )
    assert signer.identity.identifier == payload["evidence_signer_identifier"]


def test_ed25519_credentials_are_accepted_too(tmp_path) -> None:
    from market_identity import create_signer

    payload = _payload(tmp_path, scheme="ed25519")

    assert payload["buyer_identity_scheme"] == "ed25519"
    create_signer("ed25519", payload["buyer_identity_credential"])


def test_live_and_malformed_provider_credentials_are_refused(tmp_path) -> None:
    with pytest.raises(assembler.CredentialAssemblyError, match="live"):
        _payload(tmp_path, provider_path=_provider_file(tmp_path, "sk_live_" + "a" * 32, name="live.env"))
    with pytest.raises(assembler.CredentialAssemblyError, match="test-mode"):
        _payload(tmp_path, provider_path=_provider_file(tmp_path, "pk_test_nope", name="wrong.env"))

    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(assembler.CredentialAssemblyError, match="must define"):
        _payload(tmp_path, provider_path=empty)

    missing_account = tmp_path / "partial.env"
    missing_account.write_text("STRIPE_SECRET_KEY=sk_test_x\n", encoding="utf-8")
    with pytest.raises(assembler.CredentialAssemblyError):
        _payload(tmp_path, provider_path=missing_account)


def test_the_authority_can_sign_as_itself(tmp_path) -> None:
    """The harness refuses an authority with no independent identity."""

    from market_identity import create_signer

    payload = _payload(tmp_path, authority_env=None)
    authority = payload["authority_env"]

    assert authority["HOSTED_SETTLEMENT_AUTHORITY_ID"]
    assert authority["HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME"] in {
        "eip191",
        "ed25519",
    }
    create_signer(
        authority["HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME"],
        authority["HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY"],
    )
    # Independent of every other role it is issued alongside.
    assert authority["HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY"] not in {
        payload["evidence_signer_credential"],
        payload["buyer_identity_credential"],
        payload["storefront_identity_credential"],
    }


def test_an_operator_authority_environment_wins(tmp_path) -> None:
    payload = _payload(
        tmp_path,
        authority_env={"HOSTED_SETTLEMENT_AUTHORITY_ID": "operator-authority"},
    )

    assert payload["authority_env"]["HOSTED_SETTLEMENT_AUTHORITY_ID"] == (
        "operator-authority"
    )
    assert payload["authority_env"]["HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY"]


def test_materialized_layout_matches_what_the_driver_is_handed(tmp_path) -> None:
    payload = _payload(tmp_path)
    directory = tmp_path / "run"

    environment = assembler.materialize(payload, directory)

    assert Path(environment["HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE"]).is_file()
    assert (
        Path(environment["HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE"]).read_text(
            encoding="utf-8"
        )
    ).splitlines()[0].startswith("HOSTED_SETTLEMENT_AUTHORITY_ID=")
    for name in (
        "VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE",
        "VMS_REGISTRY_B_IDENTITY_CREDENTIAL_FILE",
        "VMS_PROVISIONING_IDENTITY_ENV_FILE",
        "VMS_BOB_IDENTITY_ENV_FILE",
        "VMS_BOB_STOREFRONT_SECRETS_FILE",
    ):
        assert Path(environment[name]).is_file()
    assert environment["STRIPE_SECRET_KEY"] == payload["stripe_restricted_key"]
    assert environment["HOSTED_STRIPE_TEST_ACCOUNT_REF"] == payload["account_ref"]


def test_written_material_is_private_to_the_operator(tmp_path) -> None:
    directory = tmp_path / "run"

    environment = assembler.materialize(_payload(tmp_path), directory)

    for name in (
        "HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE",
        "VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE",
        "VMS_BOB_IDENTITY_ENV_FILE",
    ):
        mode = Path(environment[name]).stat().st_mode
        assert not mode & stat.S_IRGRP
        assert not mode & stat.S_IROTH


def test_no_provider_credential_reaches_the_repository(tmp_path) -> None:
    """The operator's file is read; nothing copies it anywhere else."""

    payload = _payload(tmp_path)
    directory = tmp_path / "run"
    assembler.materialize(payload, directory)

    written = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in directory.rglob("*")
        if path.is_file()
    )
    assert payload["stripe_restricted_key"] not in written
    assert payload["connected_account_id"] not in written


def test_the_derived_config_pins_identities_this_run_holds(tmp_path) -> None:
    """A local run owns the keys its storefront configuration names."""

    import tomllib

    from market_identity import create_signer

    template = Path("e2e-tests/config/hosted-storefront.toml").read_text(encoding="utf-8")
    template_path = tmp_path / "template.toml"
    template_path.write_text(template, encoding="utf-8")

    payload, derived = assembler.assemble_payload(
        provider_path=_provider_file(tmp_path),
        now_unix=1_700_000_000,
        storefront_config_template=template_path,
    )
    document = tomllib.loads(derived)

    storefront = create_signer(
        document["Identity"]["principal"]["scheme"],
        payload["storefront_identity_credential"],
    )
    assert storefront.identity.identifier == (
        document["Identity"]["principal"]["identifier"]
    )
    provisioning_pin = document["provisioning"]["identity"]["principals"][0]
    provisioning = create_signer(
        provisioning_pin["scheme"], payload["provisioning_identity_credential"]
    )
    assert provisioning.identity.identifier == provisioning_pin["identifier"]
    authority_pin = document["Settlement"]["stripe"]["authority"]["principals"][0]
    authority = create_signer(
        payload["authority_env"]["HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME"],
        payload["authority_env"]["HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY"],
    )
    assert authority.identity.identifier == authority_pin["identifier"]
    # Everything the operator wrote that is not an identity survives.
    assert document["agent_id"] == "bob"
    assert document["Settlement"]["priority"] == ["fiat.stripe.v1"]


def test_the_derived_config_is_written_and_pointed_at(tmp_path) -> None:
    template_path = tmp_path / "template.toml"
    template_path.write_text(
        Path("e2e-tests/config/hosted-storefront.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    payload, derived = assembler.assemble_payload(
        provider_path=_provider_file(tmp_path),
        now_unix=1_700_000_000,
        storefront_config_template=template_path,
    )

    environment = assembler.materialize(payload, tmp_path / "run", derived)

    written = Path(environment["HOSTED_STRIPE_TEST_STOREFRONT_CONFIG"])
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == derived
