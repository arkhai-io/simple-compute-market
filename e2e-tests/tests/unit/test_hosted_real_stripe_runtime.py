from __future__ import annotations

from pathlib import Path
import tomllib

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
        shared_directory=tmp_path,
    ) as authority_env:
        assert authority_env.parent.parent == tmp_path

    assert tuple(tmp_path.iterdir()) == ()
