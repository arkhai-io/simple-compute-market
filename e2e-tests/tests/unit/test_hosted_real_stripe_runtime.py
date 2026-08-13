from __future__ import annotations

from pathlib import Path

from src.hosted_real_stripe.runtime import ComposeStack


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
