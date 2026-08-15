from __future__ import annotations

from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


def _toml(path: str) -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / path).read_text(encoding="utf-8"))

def _field_paths(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return set()
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path.lower())
        paths.update(_field_paths(child, path))
    return paths


def test_fiat_compose_uses_canonical_public_config_without_evm_resources() -> None:
    config = _toml("config.stripe-fiat-ed25519.toml")
    settlement = config["Settlement"]

    assert settlement["schema_version"] == 1
    assert settlement["priority"] == ["fiat.stripe.v1"]
    assert set(settlement) == {"schema_version", "priority", "stripe"}
    stripe = settlement["stripe"]
    assert stripe["expected_api_version"] == "0.2.0"
    assert stripe["expected_schema_version"] == 5
    assert stripe["currency"] == "usd"
    assert stripe["country"] == "US"
    assert stripe["account_ref"] == "replace-with-hosted-account-ref"
    assert stripe["expected_manifest_digest"] == "sha256:" + ("0" * 64)
    assert stripe["condition_profile"] in stripe["condition_profiles"]
    resolver_id = stripe["condition_profiles"][stripe["condition_profile"]]["evaluator"][
        "resolver_id"
    ]
    assert resolver_id in stripe["resolvers"]
    clauses = config["pricing"]["settlements"]
    assert [clause["mechanism_input"]["funding_profile"] for clause in clauses] == [
        "card.v1",
        "us_bank_transfer.v1",
        "us_ach_debit.v1",
    ]
    assert all(
        clause["mechanism_input"]["interaction"] == "interactive"
        and clause["mechanism_input"]["funds_flow"] == "separate_charges_transfers"
        for clause in clauses
    )
    assert "Wallet" not in config
    assert "Chains" not in config

    fields = _field_paths(settlement)
    forbidden_fragments = (
        "provider_",
        "webhook",
        "database",
        "migration",
        "rpc_url",
        "payer_profile",
        "instrument",
        "mandate",
        "action_url",
    )
    assert not {
        path
        for path in fields
        if any(fragment in path for fragment in forbidden_fragments)
    }

    compose = (REPO_ROOT / "compose.hosted-settlement.yml").read_text(
        encoding="utf-8"
    )
    assert "VMS_BOB_STRIPE_STOREFRONT_CONFIG" in compose
    assert "set generated release-pinned storefront config" in compose
    assert "config.stripe-fiat-ed25519.toml" not in compose
    assert "VMS_BOB_HOSTED_STOREFRONT_CONFIG" not in compose
    for forbidden in (
        "checkout.stripe.com",
        "client_secret",
        "payment_method",
        "bank_instructions",
    ):
        assert forbidden not in compose

def test_protected_buyer_policy_is_disabled_bounded_and_buyer_only() -> None:
    buyer = _toml("e2e-tests/config/hosted-buyer.toml")
    policy = buyer["Settlement"]["stripe"]["off_session_policy"]
    assert policy == {
        "enabled": False,
        "mode": "saved_instrument",
        "authority_id": "local-e2e-hosted-authority",
        "environment": "local-e2e",
        "funding_profile": "card.v1",
        "currency": "usd",
        "max_purchase_minor_units": 10000,
        "max_aggregate_minor_units": 50000,
        "window_kind": "rolling",
        "window_seconds": 86400,
        "seller_principals": [],
    }
    assert buyer["Settlement"]["stripe"]["authorization_journal_path"].startswith("/")
    storefront = _toml("e2e-tests/config/hosted-storefront.toml")
    assert "off_session_policy" not in storefront["Settlement"]["stripe"]
    assert "authorization_journal_path" not in storefront["Settlement"]["stripe"]
    serialized = str(buyer).lower()
    for forbidden in (
        "payer_profile_ref",
        "instrument_ref",
        "payment_method",
        "client_secret",
        "action_url",
        "bank_instructions",
    ):
        assert forbidden not in serialized


def test_alkahest_profiles_keep_policy_outside_chains() -> None:
    for relative_path in (
        "domains/vms/storefront/storefront.bob.toml",
        "domains/vms/storefront/storefront.alice.toml",
    ):
        config = _toml(relative_path)
        settlement = config["Settlement"]
        assert settlement["schema_version"] == 1
        assert settlement["priority"] == ["alkahest.v1"]
        assert settlement["alkahest"]["enabled"] is True
        assert "address_config_path" in settlement["alkahest"]
        assert all(
            "alkahest" not in field
            for chain in config["Chains"].values()
            for field in chain
        )


def test_public_rehearsal_examples_exclude_wallet_credentials() -> None:
    for relative_path in (
        "deploy-base-sepolia/buyer.config.toml",
        "deploy-base-sepolia/storefront.toml",
    ):
        config = _toml(relative_path)
        assert "private_key" not in config["Wallet"]
        assert config["Settlement"]["priority"] == ["alkahest.v1"]

    compose = (REPO_ROOT / "deploy-base-sepolia/docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "VMS_SEPOLIA_STOREFRONT_SECRETS_FILE" in compose
    assert "/etc/arkhai/storefront.secrets.toml:ro" in compose


def test_marketplace_compose_emits_no_legacy_settlement_environment() -> None:
    marketplace_compose = "\n".join(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in ("compose.vms.yml", "compose.vms-fiat.yml", "domains/vms/compose.yml")
    )
    assert "STOREFRONT_SETTLEMENT__HOSTED" not in marketplace_compose
    assert "VMS_BOB_HOSTED_STOREFRONT_CONFIG" not in marketplace_compose

    authority_compose = (REPO_ROOT / "compose.hosted-settlement.yml").read_text(
        encoding="utf-8"
    )
    assert "HOSTED_SETTLEMENT_VERIFIED_IMAGE" in authority_compose
    assert "HOSTED_SETTLEMENT_ENV_FILE" in authority_compose
