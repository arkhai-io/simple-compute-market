from __future__ import annotations

import base64
import json
from pathlib import Path
import tomllib
from collections.abc import Mapping, Sequence
from typing import Any
import pytest
from market_identity import create_signer

from src.hosted_real_stripe.runtime import (
    ComposeStack,
    EphemeralBuyerConfig,
    EphemeralMarketplaceConfig,
    EphemeralServiceEnv,
    ProcessUnavailable,
    require_runtime_authority_identity,
)


def test_runtime_authority_identity_is_derived_from_injected_credential(
    tmp_path: Path,
) -> None:
    credential = base64.urlsafe_b64encode(bytes([17]) * 32).decode().rstrip("=")
    environment = tmp_path / "authority.env"
    environment.write_text(
        "HOSTED_SETTLEMENT_AUTHORITY_ID=hosted-stripe-test-authority\n"
        "HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME=ed25519\n"
        f"HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY={credential}\n",
        encoding="utf-8",
    )

    authority = require_runtime_authority_identity(
        environment,
        release_authority_address="0x" + ("22" * 20),
    )

    assert authority.authority_id == "hosted-stripe-test-authority"
    assert authority.scheme == "ed25519"
    assert authority.identifier == create_signer("ed25519", credential).identity.identifier


def test_runtime_authority_identity_rejects_release_key_reuse(tmp_path: Path) -> None:
    credential = "11" * 32
    release_address = create_signer("eip191", credential).identity.identifier
    environment = tmp_path / "authority.env"
    environment.write_text(
        "HOSTED_SETTLEMENT_AUTHORITY_ID=hosted-stripe-test-authority\n"
        "HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME=eip191\n"
        f"HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY={credential}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProcessUnavailable, match="must be independent"):
        require_runtime_authority_identity(
            environment,
            release_authority_address=release_address,
        )


def test_compose_stack_uses_every_declared_compose_file(tmp_path: Path) -> None:
    compose_env = tmp_path / "compose.env"
    first = tmp_path / "base.yml"
    second = tmp_path / "hosted.yml"

    stack = ComposeStack(
        compose_env=compose_env,
        compose_files=(first, second),
        executable="docker",
        cwd=tmp_path,
    )

    assert stack._base == [
        "docker",
        "compose",
        "--profile",
        "hosted-stripe-test",
        "--env-file",
        str(compose_env),
        "-f",
        str(first),
        "-f",
        str(second),
    ]


def test_compose_stack_sets_refund_servicing_interval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stack = ComposeStack(
        compose_env=tmp_path / "compose.env",
        compose_files=(tmp_path / "compose.yml",),
        executable="docker",
        cwd=tmp_path,
    )
    captured: dict[str, Any] = {}

    def capture(
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        check: bool,
        input_text: str | None = None,
    ) -> None:
        captured.update(argv=tuple(argv), env=dict(env), check=check)

    monkeypatch.setattr(stack, "_run", capture)
    stack.start(
        authority_env_path=tmp_path / "authority.env",
        marketplace_config_path=tmp_path / "storefront.toml",
        storefront_servicing_interval_seconds=7200,
    )

    assert captured["env"]["HOSTED_STOREFRONT_SERVICING_INTERVAL_SECONDS"] == "7200"


def test_compose_stack_streams_existing_account_contract_without_provider_argument(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stack = ComposeStack(
        compose_env=tmp_path / "compose.env",
        compose_files=(tmp_path / "compose.yml",),
        executable="docker",
        cwd=tmp_path,
    )
    stack._runtime_env = {"PATH": "/bin"}
    captured: dict[str, Any] = {}

    def capture(
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        check: bool,
        input_text: str | None = None,
    ) -> None:
        captured.update(
            argv=tuple(argv),
            env=dict(env),
            check=check,
            input_text=input_text,
        )

    monkeypatch.setattr(stack, "_run", capture)
    contract = json.dumps(
        {
            "provider_account_id": "acct_private",
            "admission": {"protocol": "arkhai.account-owner-admission.v1"},
        }
    )

    stack.bind_existing_account(
        account_ref="seller-account",
        binding_contract=contract,
    )

    argv = captured["argv"]
    assert "acct_private" not in argv
    assert argv[-8:] == (
        "--account-ref",
        "seller-account",
        "--binding-file",
        "-",
        "--actor",
        "protected-stripe-test",
        "--reason-code",
        "maintained-test-account",
    )
    assert captured["input_text"] == contract


def test_ephemeral_container_inputs_use_shared_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    template = Path(__file__).resolve().parents[2] / "config" / "hosted-storefront.toml"

    with EphemeralMarketplaceConfig(
        template=template,
        account_ref="account-1",
        authority_id="authority-1",
        authority_scheme="eip191",
        authority_address="0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
        authority_environment="test",
        manifest_digest="sha256:" + ("1" * 64),
        funding_profile="us_bank_transfer.v1",
        shared_directory=tmp_path,
    ) as marketplace_config:
        assert marketplace_config.parent.parent == tmp_path
        parsed = tomllib.loads(marketplace_config.read_text(encoding="utf-8"))
        assert parsed["Settlement"]["stripe"]["authority"]["principals"] == [
            {
                "scheme": "eip191",
                "identifier": "0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
            }
        ]
        assert parsed["pricing"]["settlements"][0]["mechanism_input"]["funding_profile"] == (
            "us_bank_transfer.v1"
        )
    buyer_template = Path(__file__).resolve().parents[2] / "config" / "hosted-buyer.toml"
    credential = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_CREDENTIAL", credential)
    with EphemeralBuyerConfig(
        template=buyer_template,
        authority_id="authority-1",
        authority_scheme="eip191",
        authority_address="0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
        authority_environment="test",
        manifest_digest="sha256:" + ("1" * 64),
        funding_profile="us_bank_transfer.v1",
        buyer_identity_scheme="ed25519",
        shared_directory=tmp_path,
    ) as buyer_config:
        parsed = tomllib.loads(buyer_config.read_text(encoding="utf-8"))
        stripe = parsed["Settlement"]["stripe"]
        assert stripe["expected_manifest_digest"] == "sha256:" + ("1" * 64)
        assert stripe["authority_id"] == stripe["off_session_policy"]["authority_id"]
        assert stripe["environment"] == stripe["off_session_policy"]["environment"]
        assert stripe["off_session_policy"]["funding_profile"] == "us_bank_transfer.v1"
        profile_store = Path(parsed["BuyerProfile"]["store_path"])
        assert profile_store.is_file()
        assert credential not in profile_store.read_text(encoding="utf-8")
        assert Path(stripe["authorization_journal_path"]).parent == buyer_config.parent

    with EphemeralServiceEnv(
        api_key="sk_test_example",
        webhook_secret="whsec_example",
        manifest_digest="sha256:" + ("2" * 64),
        release_authority_id="release-authority",
        release_authority_address="0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
        release_repository="arkhai-io/stripe-settlement-service",
        release_workflow_ref=".github/workflows/release.yml@refs/tags/v0.2.0",
        release_source_commit="3" * 40,
        shared_directory=tmp_path,
    ) as authority_env:
        assert authority_env.parent.parent == tmp_path
        values = dict(
            line.split("=", 1) for line in authority_env.read_text(encoding="utf-8").splitlines()
        )
        assert values["HOSTED_SETTLEMENT_MANIFEST_DIGEST"] == "sha256:" + ("2" * 64)
        assert (
            values["HOSTED_SETTLEMENT_CHECKOUT_SUCCESS_URL"]
            == "http://127.0.0.1:18081/checkout/success"
        )
        assert (
            values["HOSTED_SETTLEMENT_CHECKOUT_CANCEL_URL"]
            == "http://127.0.0.1:18081/checkout/cancel"
        )
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_PATH"]
            == "/opt/hosted-settlement/release/release-manifest.json"
        )
        assert values["HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ID"] == "release-authority"
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ADDRESS"]
            == "0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008"
        )
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_REPOSITORY"] == "arkhai-io/stripe-settlement-service"
        )
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_WORKFLOW_REF"]
            == ".github/workflows/release.yml@refs/tags/v0.2.0"
        )
        assert values["HOSTED_SETTLEMENT_RELEASE_SOURCE_COMMIT"] == "3" * 40
        assert values["HOSTED_SETTLEMENT_RESOLVER_CALLERS"] == (
            "eip191:0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008"
        )
        remote_resolvers = json.loads(values["HOSTED_SETTLEMENT_REMOTE_RESOLVERS_JSON"])
        assert remote_resolvers == [
            {
                "allow_insecure_loopback": True,
                "authority_id": "release-authority",
                "base_url": "http://127.0.0.1:8080",
                "evaluator_id": "vm-portable",
                "portable_authority_address": ("0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008"),
                "principals": [
                    {
                        "identifier": "0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
                        "scheme": "eip191",
                    }
                ],
                "resolver_id": "vm-portable",
            }
        ]

    assert tuple(tmp_path.iterdir()) == ()
