from __future__ import annotations

import os
import stat
from pathlib import Path

import market_config.settlement_migration as migration
import pytest
from market_config.settlement_migration import (
    SettlementMigrationConflict,
    SettlementMigrationError,
    SettlementMigrationValidationError,
    migrate_settlement_config,
)


def _write(path: Path, text: str, mode: int = 0o600) -> bytes:
    path.write_text(text)
    path.chmod(mode)
    return path.read_bytes()


def _accept_typed_candidate(_document: object, role: object) -> None:
    assert role in {"buyer", "seller"}


def test_incompatible_per_chain_address_books_are_a_conflict(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    original = _write(
        path,
        """[Chains.one]
alkahest_address_config_path = "/one.json"

[Chains.two]
alkahest_address_config_path = "/two.json"
""",
    )

    with pytest.raises(SettlementMigrationConflict):
        migrate_settlement_config(path, role="seller", write=True, backup=True)

    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


def test_candidate_validator_failure_rolls_back_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    secret = "validator-leaked-secret"
    original = _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
    )

    def reject(_document: object, _role: object) -> None:
        raise ValueError(secret)

    with pytest.raises(SettlementMigrationValidationError) as error:
        migrate_settlement_config(
            path,
            role="buyer",
            write=True,
            backup=True,
            validator=reject,
        )

    assert secret not in str(error.value)
    assert path.read_bytes() == original
    assert not path.with_name("buyer.toml.bak").exists()


def test_write_refuses_to_skip_typed_candidate_validation(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    original = _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
    )

    with pytest.raises(
        SettlementMigrationValidationError,
        match="requires a typed settlement candidate validator",
    ):
        migrate_settlement_config(path, role="buyer", write=True, backup=True)

    assert path.read_bytes() == original
    assert not path.with_name("buyer.toml.bak").exists()


def test_atomic_replace_failure_restores_source_and_removes_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "buyer.toml"
    original = _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
    )

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(migration.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        migrate_settlement_config(
            path,
            role="buyer",
            write=True,
            backup=True,
            validator=_accept_typed_candidate,
        )

    assert path.read_bytes() == original
    assert not path.with_name("buyer.toml.bak").exists()
    assert not any(item.suffix == ".tmp" for item in tmp_path.iterdir())


def test_write_preserves_restrictive_permissions_and_uses_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "buyer.toml"
    original = _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
        mode=0o600,
    )
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def record_replace(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", record_replace)
    result = migrate_settlement_config(
        path,
        role="buyer",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )

    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600
    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert replacements[0][0].parent == path.parent
    assert replacements[0][0].name.startswith(f".{path.name}.")
    assert not replacements[0][0].exists()


def test_write_tightens_non_restrictive_source_permissions(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
        mode=0o644,
    )

    result = migrate_settlement_config(
        path,
        role="buyer",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert result.backup_path is not None
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600


def test_successful_migration_rerun_is_byte_identical_noop(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    _write(
        path,
        """[settlement]
mechanism_priority = ["alkahest.v1"]
""",
    )
    first = migrate_settlement_config(
        path,
        role="buyer",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )
    migrated = path.read_bytes()
    backup = first.backup_path
    assert backup is not None
    backup_bytes = backup.read_bytes()

    second = migrate_settlement_config(
        path,
        role="buyer",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )

    assert second.changed is False
    assert second.written is False
    assert second.backup_path is None
    assert path.read_bytes() == migrated
    assert backup.read_bytes() == backup_bytes


def test_write_and_check_modes_are_strict() -> None:
    with pytest.raises(SettlementMigrationError, match="exactly one"):
        migrate_settlement_config("unused", role="buyer")
    with pytest.raises(SettlementMigrationError, match="requires backup"):
        migrate_settlement_config("unused", role="buyer", write=True)
    with pytest.raises(SettlementMigrationError, match="only valid"):
        migrate_settlement_config("unused", role="buyer", check=True, backup=True)
