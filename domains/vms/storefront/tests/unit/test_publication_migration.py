from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import tomllib
from market_config import SettlementMigrationValidationError
from market_hosted_settlement import create_stripe_registration
from market_settlement_runtime import (
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
    compile_settlement_publication_clause,
)

from market_storefront.publication_migration import (
    migrate_publication_config,
    migrate_publication_csv,
)


def _stripe_config() -> dict:
    return {
        "Settlement": {
            "stripe": {"enabled": True, "currency": "usd"},
            "alkahest": {"enabled": False},
        }
    }


def _stripe_clause_compiler(
    raw: dict,
) -> SettlementPublicationClause:
    registry = SettlementConfigurationRegistry([create_stripe_registration()])
    config = registry.resolve(
        {
            "priority": ["fiat.stripe.v1"],
            "stripe": {"enabled": True, "currency": "usd"},
        },
        role="seller",
    )
    return compile_settlement_publication_clause(
        raw,
        registry=registry,
        config=config,
        role="seller",
    )


def test_config_check_is_byte_preserving_and_reports_exact_conversion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"# preserve me\n"
        b"[Pricing]\n"
        b'default_min_price = "125" # legacy minor units\n\n'
        b"[Settlement.stripe]\n"
        b"enabled = true\n"
        b'currency = "usd"\n'
    )
    path.write_bytes(original)

    result = migrate_publication_config(path, check=True)

    assert result.changed is True
    assert result.written is False
    assert result.conflicts == ()
    assert result.actions == ("Pricing.settlements <- fiat.stripe.v1",)
    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


def test_config_write_backups_and_reruns_as_byte_identical_noop(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"[Pricing]\n"
        b'default_min_price = "125"\n\n'
        b"[Settlement.stripe]\n"
        b"enabled = true\n"
        b'currency = "usd"\n'
    )
    path.write_bytes(original)
    validator_calls: list[str] = []

    first = migrate_publication_config(
        path,
        write=True,
        backup=True,
        validator=lambda _document, role: validator_calls.append(role),
    )
    migrated = path.read_bytes()
    document = tomllib.loads(migrated.decode())
    clause = document["Pricing"]["settlements"][0]

    assert first.written is True
    assert first.backup_path is not None
    assert first.backup_path.read_bytes() == original
    assert validator_calls == ["seller"]
    assert clause == {
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rate": "1.25",
        "per": "hour",
        "mechanism_input": {
            "method": "card",
            "funds_flow": "separate_charges_transfers",
        },
    }

    second = migrate_publication_config(
        path,
        write=True,
        backup=True,
        validator=lambda *_args: pytest.fail("noop must not validate or write"),
    )
    assert second.changed is False
    assert second.written is False
    assert path.read_bytes() == migrated
    assert first.backup_path.read_bytes() == original


def test_config_dual_mechanism_conflict_never_mutates(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    original = (
        b"[Pricing]\n"
        b'default_min_price = "100"\n'
        b'default_token_address = "0x1111111111111111111111111111111111111111"\n\n'
        b"[Settlement.stripe]\n"
        b"enabled = true\n"
        b'currency = "usd"\n\n'
        b"[Settlement.alkahest]\n"
        b"enabled = true\n"
    )
    path.write_bytes(original)

    checked = migrate_publication_config(path, check=True)
    assert checked.conflicts == ("dual-mechanism publication requires manual clauses",)
    assert path.read_bytes() == original

    with pytest.raises(SettlementMigrationValidationError, match="dual-mechanism"):
        migrate_publication_config(
            path,
            write=True,
            backup=True,
            validator=lambda *_args: None,
        )
    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


def test_csv_check_write_backup_and_idempotence(tmp_path: Path) -> None:
    path = tmp_path / "resources.csv"
    original = (
        b"resource_id,resource_type,state,min_price,token\n"
        b"gpu-1,compute.gpu,available,250,\n"
    )
    path.write_bytes(original)

    checked = migrate_publication_csv(
        path,
        storefront_config=_stripe_config(),
        check=True,
        clause_compiler=_stripe_clause_compiler,
    )
    assert checked.changed is True
    assert checked.actions == ("row 2: settlements <- fiat.stripe.v1",)
    assert path.read_bytes() == original

    first = migrate_publication_csv(
        path,
        storefront_config=_stripe_config(),
        write=True,
        backup=True,
        clause_compiler=_stripe_clause_compiler,
    )
    migrated = path.read_bytes()
    assert first.backup_path is not None
    assert first.backup_path.read_bytes() == original
    with path.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert json.loads(row["settlements"]) == [
        {
            "asset": "usd",
            "mechanism": "fiat.stripe.v1",
            "mechanism_input": {
                "funds_flow": "separate_charges_transfers",
                "method": "card",
            },
            "per": "hour",
            "rate": "2.5",
        }
    ]

    second = migrate_publication_csv(
        path,
        storefront_config=_stripe_config(),
        write=True,
        backup=True,
        clause_compiler=_stripe_clause_compiler,
    )
    assert second.changed is False
    assert second.written is False
    assert path.read_bytes() == migrated


def test_csv_hidden_reserve_conflict_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "resources.csv"
    original = (
        b"resource_id,resource_type,state,min_price,token\n"
        b"gpu-1,compute.gpu,available,,0x1111111111111111111111111111111111111111\n"
    )
    path.write_bytes(original)

    result = migrate_publication_csv(
        path,
        storefront_config={
            "Settlement": {"alkahest": {"enabled": True}},
            "Chains": {"anvil": {"rpc_url": "http://localhost:8545"}},
        },
        check=True,
    )

    assert result.conflicts == ("row 2: hidden-reserve pricing has no explicit rate",)
    assert path.read_bytes() == original


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


def test_csv_accepted_escrows_without_scalar_pricing_is_a_manual_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resources.csv"
    original = (
        b'resource_id,resource_type,accepted_escrows\ngpu-1,compute.gpu,"legacy=100"\n'
    )
    path.write_bytes(original)

    result = migrate_publication_csv(
        path,
        storefront_config=_stripe_config(),
        check=True,
        clause_compiler=_stripe_clause_compiler,
    )

    assert result.conflicts == (
        "row 2: accepted_escrows requires manual settlement clauses",
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "clause",
    [
        {
            "mechanism": "missing.v1",
            "asset": "usd",
            "rate": "1",
            "per": "hour",
        },
        {
            "mechanism": "fiat.stripe.v1",
            "asset": "usd",
            "rate": "1",
            "per": "hour",
            "mechanism_input": {"method": "wire"},
        },
    ],
)
def test_csv_uninstalled_or_invalid_clause_fails_before_backup_or_write(
    tmp_path: Path,
    clause: dict,
) -> None:
    path = tmp_path / "resources.csv"
    encoded = json.dumps([clause], separators=(",", ":")).replace('"', '""')
    original = (
        "resource_id,resource_type,min_price,settlements\n"
        "gpu-1,compute.gpu,250,\n"
        f'gpu-2,compute.gpu,,"{encoded}"\n'
    ).encode()
    path.write_bytes(original)

    with pytest.raises(SettlementMigrationValidationError):
        migrate_publication_csv(
            path,
            storefront_config=_stripe_config(),
            write=True,
            backup=True,
            clause_compiler=_stripe_clause_compiler,
        )

    assert path.read_bytes() == original
    assert not path.with_name("resources.csv.bak").exists()
