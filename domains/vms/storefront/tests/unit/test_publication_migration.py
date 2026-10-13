from __future__ import annotations

from pathlib import Path

from market_storefront.publication_migration import (
    migrate_publication_config,
)


def test_config_per_model_legacy_pricing_is_a_manual_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"[Pricing]\n"
        b"\n"
        b"[Pricing.defaults.gpu.H100]\n"
        b'min_price = "125"\n'
        b'token = "0x1111111111111111111111111111111111111111"\n'
        b"\n"
        b"[Settlement.alkahest]\n"
        b"enabled = true\n"
    )
    path.write_bytes(original)

    result = migrate_publication_config(path, check=True)

    assert result.changed is False
    assert result.conflicts == (
        "per-model legacy pricing requires manual clauses: Pricing.defaults.gpu.H100",
    )
    assert path.read_bytes() == original


def test_config_per_model_rates_and_clauses_are_not_legacy_pricing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"[Pricing]\n"
        b"\n"
        b"[Pricing.defaults.gpu.H100]\n"
        b'rates = [ { asset = "usd", rate = "2", per = "hour" } ]\n'
        b"\n"
        b"[Pricing.defaults.gpu.A100]\n"
        b"settlements = []\n"
        b"\n"
        b"[Settlement.alkahest]\n"
        b"enabled = true\n"
    )
    path.write_bytes(original)

    result = migrate_publication_config(path, check=True)

    assert result.changed is False
    assert result.conflicts == ()
    assert path.read_bytes() == original


def test_config_invalid_legacy_token_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"[Pricing]\n"
        b'default_min_price = "1"\n'
        b'default_token_address = "0xnot-a-token"\n'
        b"\n"
        b"[Settlement.alkahest]\n"
        b"enabled = true\n"
        b"\n"
        b"[Chains.anvil]\n"
        b'rpc_url = "http://localhost:8545"\n'
    )
    path.write_bytes(original)

    result = migrate_publication_config(path, check=True)

    assert result.conflicts == (
        "Alkahest token address must be a canonical 20-byte hexadecimal address",
    )
    assert path.read_bytes() == original
