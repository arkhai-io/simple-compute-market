from __future__ import annotations

import json
from pathlib import Path
import tomllib
from collections.abc import Mapping, Sequence
from typing import Any

from src.hosted_real_stripe.runtime import (
    ComposeStack,
    EphemeralMarketplaceConfig,
    EphemeralServiceEnv,
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


def test_ephemeral_container_inputs_use_shared_directory(tmp_path: Path) -> None:
    template = Path(__file__).resolve().parents[2] / "config" / "hosted-storefront.toml"

    with EphemeralMarketplaceConfig(
        template=template,
        account_ref="account-1",
        authority_id="authority-1",
        authority_scheme="eip191",
        authority_address="0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
        authority_environment="test",
        manifest_digest="sha256:" + ("1" * 64),
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

    with EphemeralServiceEnv(
        api_key="sk_test_example",
        webhook_secret="whsec_example",
        manifest_digest="sha256:" + ("2" * 64),
        release_authority_id="release-authority",
        release_authority_address="0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008",
        release_repository="arkhai/hosted-settlement-service",
        release_workflow_ref=".github/workflows/release.yml@refs/tags/v0.1.0",
        release_source_commit="3" * 40,
        shared_directory=tmp_path,
    ) as authority_env:
        assert authority_env.parent.parent == tmp_path
        values = dict(
            line.split("=", 1) for line in authority_env.read_text(encoding="utf-8").splitlines()
        )
        assert values["HOSTED_SETTLEMENT_MANIFEST_DIGEST"] == "sha256:" + ("2" * 64)
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_PATH"]
            == "/opt/hosted-settlement/release/release-manifest.json"
        )
        assert values["HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ID"] == "release-authority"
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ADDRESS"]
            == "0x1fe2aa7fbaf5720f79a22a4ada4b8b37d4e0c008"
        )
        assert values["HOSTED_SETTLEMENT_RELEASE_REPOSITORY"] == "arkhai/hosted-settlement-service"
        assert (
            values["HOSTED_SETTLEMENT_RELEASE_WORKFLOW_REF"]
            == ".github/workflows/release.yml@refs/tags/v0.1.0"
        )
        assert values["HOSTED_SETTLEMENT_RELEASE_SOURCE_COMMIT"] == "3" * 40

    assert tuple(tmp_path.iterdir()) == ()
