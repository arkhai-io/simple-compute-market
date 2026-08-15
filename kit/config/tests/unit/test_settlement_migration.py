from __future__ import annotations

import os
import stat
from pathlib import Path

import market_config.settlement_migration as migration
import pytest
import tomllib
from market_config.settlement_migration import (
    BUYER_MIGRATION_COMMAND,
    STOREFRONT_MIGRATION_COMMAND,
    SettlementMigrationConflict,
    SettlementMigrationError,
    SettlementMigrationValidationError,
    environment_renames,
    format_migration_result,
    is_legacy_settlement_path,
    migrate_settlement_config,
    reject_legacy_settlement_path,
)


def _write(path: Path, text: str, mode: int = 0o600) -> bytes:
    path.write_text(text)
    path.chmod(mode)
    return path.read_bytes()


def _accept_typed_candidate(_document: object, role: object) -> None:
    assert role in {"buyer", "seller"}


def test_buyer_migration_moves_priority_and_one_effective_address_book(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    original = _write(
        path,
        """# buyer comment
[Identity]
scheme = "ed25519"
identifier = "public-only"

[Wallet]
address = "0xabc"
private_key = "secret-wallet-value"

[Chains.anvil]
rpc_url = "http://127.0.0.1:8545"
chain_id = 31337
alkahest_address_config_path = "/run/alkahest.json" # address comment

[settlement]
mechanism_priority = ["fiat.stripe.v1", "alkahest.v1"] # order comment

[unrelated]
answer = 42
""",
    )

    checked = migrate_settlement_config(path, role="buyer", check=True)

    assert checked.changed is True
    assert checked.written is False
    assert path.read_bytes() == original
    assert not path.with_name("buyer.toml.bak").exists()

    written = migrate_settlement_config(
        path,
        role="buyer",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )
    document = tomllib.loads(path.read_text())
    assert written.written is True
    assert document["Settlement"]["priority"] == [
        "fiat.stripe.v1",
        "alkahest.v1",
    ]
    assert document["Settlement"]["stripe"]["enabled"] is True
    assert document["Settlement"]["alkahest"]["enabled"] is True
    assert (
        document["Settlement"]["alkahest"]["address_config_path"]
        == "/run/alkahest.json"
    )
    assert "alkahest_address_config_path" not in document["Chains"]["anvil"]
    assert document["Identity"]["identifier"] == "public-only"
    assert document["Wallet"]["private_key"] == "secret-wallet-value"
    assert document["unrelated"] == {"answer": 42}
    assert "buyer comment" in path.read_text()
    assert "address comment" in path.read_text()
    assert "order comment" in path.read_text()


def test_seller_migration_preserves_comments_and_maps_both_mechanisms(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    _write(
        path,
        """# file comment
oracle_gated_listings = true # policy comment
trusted_oracle_address = "0x111"
interruptible_listings = false
interruptible_oracle_address = ""

[Identity]
scheme = "ed25519"
identifier = "seller-public"

[Wallet]
address = "0xabc"
private_key = "wallet-secret"

[Chains.one]
rpc_url = "https://one.invalid"
chain_id = 1
alkahest_address_config_path = "/etc/alkahest.json"

[Chains.two]
rpc_url = "https://two.invalid"
chain_id = 2
alkahest_address_config_path = "/etc/alkahest.json"

[settlement.hosted]
enabled = true
base_url = "https://settlement.invalid" # hosted comment
authority_id = "authority"
environment = "production"
expected_manifest_digest = "sha256:public-digest"
contract_version = "0.1.0"
expected_schema_version = 4
required_capabilities = ["conditional-escrow.v1"]
timeout_seconds = 9.0
preflight_timeout_seconds = 4.0
allow_insecure_loopback = false

[settlement.hosted.authority]
principals = [{scheme = "ed25519", identifier = "authority-public"}]

[unrelated]
keep = "yes" # unrelated comment
""",
    )

    migrate_settlement_config(
        path,
        role="seller",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )

    migrated_text = path.read_text()
    document = tomllib.loads(migrated_text)
    assert document["Settlement"]["priority"] == [
        "alkahest.v1",
        "fiat.stripe.v1",
    ]
    alkahest = document["Settlement"]["alkahest"]
    assert alkahest["enabled"] is True
    assert alkahest["oracle_gated"] is True
    assert alkahest["trusted_oracle_addresses"] == ["0x111"]
    assert alkahest["interruptible"] is False
    assert alkahest["interruptible_oracle_addresses"] == []
    assert alkahest["address_config_path"] == "/etc/alkahest.json"
    stripe = document["Settlement"]["stripe"]
    assert stripe["enabled"] is True
    assert stripe["expected_api_version"] == "0.1.0"
    assert stripe["request_timeout_seconds"] == 9.0
    assert stripe["authority"]["principals"][0]["identifier"] == "authority-public"
    assert "settlement" not in document
    assert document["Identity"]["identifier"] == "seller-public"
    assert document["Wallet"]["private_key"] == "wallet-secret"
    assert document["Chains"]["one"] == {
        "rpc_url": "https://one.invalid",
        "chain_id": 1,
    }
    assert document["unrelated"] == {"keep": "yes"}
    for comment in (
        "file comment",
        "policy comment",
        "hosted comment",
        "unrelated comment",
    ):
        assert comment in migrated_text


def test_top_level_hosted_settlement_variant_maps_to_stripe(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    _write(
        path,
        """[HostedSettlement]
enabled = true
base_url = "https://settlement.invalid"
authority_id = "authority"
environment = "test"
""",
    )

    migrate_settlement_config(
        path,
        role="seller",
        write=True,
        backup=True,
        validator=_accept_typed_candidate,
    )

    document = tomllib.loads(path.read_text())
    assert "HostedSettlement" not in document
    assert document["Settlement"]["stripe"]["base_url"] == (
        "https://settlement.invalid"
    )
    assert document["Settlement"]["priority"] == ["fiat.stripe.v1"]


def test_duplicate_legacy_hosted_sections_conflict_without_side_effects(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storefront.toml"
    original = _write(
        path,
        """[hosted_settlement]
enabled = true

[settlement.hosted]
enabled = true
""",
    )

    with pytest.raises(SettlementMigrationConflict) as error:
        migrate_settlement_config(path, role="seller", write=True, backup=True)

    assert "hosted_settlement" in str(error.value)
    assert "settlement.hosted" in str(error.value)
    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


def test_conflicting_old_and_new_values_abort_before_backup(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    original = _write(
        path,
        """[hosted_settlement]
base_url = "https://old.invalid"

[Settlement.stripe]
base_url = "https://new.invalid"
""",
    )

    with pytest.raises(SettlementMigrationConflict) as error:
        migrate_settlement_config(path, role="seller", write=True, backup=True)

    message = str(error.value)
    assert "hosted_settlement.base_url" in message
    assert "Settlement.stripe.base_url" in message
    assert "old.invalid" not in message
    assert "new.invalid" not in message
    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


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


def test_provider_secret_is_rejected_and_never_rendered(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    secret = "sk_test_do_not_print"
    original = _write(
        path,
        f"""[hosted_settlement]
enabled = true
webhook_secret = "{secret}"
""",
    )

    with pytest.raises(SettlementMigrationValidationError) as error:
        migrate_settlement_config(path, role="seller", check=True)

    assert secret not in str(error.value)
    assert "value redacted" in str(error.value)
    assert path.read_bytes() == original


def test_unknown_legacy_hosted_key_fails_before_write(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    value = "unknown-value-must-not-print"
    original = _write(
        path,
        f"""[hosted_settlement]
enabled = true
future_option = "{value}"
""",
    )

    with pytest.raises(SettlementMigrationValidationError) as error:
        migrate_settlement_config(path, role="seller", write=True, backup=True)

    assert value not in str(error.value)
    assert path.read_bytes() == original
    assert not path.with_name("storefront.toml.bak").exists()


def test_malformed_toml_secret_is_not_echoed(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    secret = "malformed-secret-value"
    original = _write(
        path,
        f'[hosted_settlement]\napi_key = "{secret}\n',
    )

    with pytest.raises(SettlementMigrationValidationError) as error:
        migrate_settlement_config(path, role="seller", check=True)

    assert secret not in str(error.value)
    assert path.read_bytes() == original


def test_check_mode_is_filesystem_pure_and_report_is_redacted(tmp_path: Path) -> None:
    path = tmp_path / "storefront.toml"
    secret = "https://user:password@forbidden.invalid"
    original = _write(
        path,
        f"""[hosted_settlement]
enabled = true
base_url = "{secret}"
""",
    )
    before = path.stat()
    names_before = {item.name for item in tmp_path.iterdir()}

    result = migrate_settlement_config(path, role="seller", check=True)

    after = path.stat()
    assert path.read_bytes() == original
    assert (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_mode) == (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
        after.st_mode,
    )
    assert {item.name for item in tmp_path.iterdir()} == names_before
    assert secret not in "\n".join(format_migration_result(result))


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


def test_environment_mapping_renames_only_marketplace_consumer_aliases() -> None:
    value = "must-not-appear"
    renames = environment_renames(
        {
            "STOREFRONT_SETTLEMENT__HOSTED__BASE_URL": value,
            "STOREFRONT_SETTLEMENT__HOSTED__CONTRACT_VERSION": value,
            "STOREFRONT_TRUSTED_ORACLE_ADDRESS": value,
            "HOSTED_SETTLEMENT_STRIPE_SECRET_KEY": value,
        },
        role="seller",
    )

    assert [(item.source, item.destination) for item in renames] == [
        (
            "STOREFRONT_SETTLEMENT__HOSTED__BASE_URL",
            "STOREFRONT_SETTLEMENT__STRIPE__BASE_URL",
        ),
        (
            "STOREFRONT_SETTLEMENT__HOSTED__CONTRACT_VERSION",
            "STOREFRONT_SETTLEMENT__STRIPE__EXPECTED_API_VERSION",
        ),
        (
            "STOREFRONT_TRUSTED_ORACLE_ADDRESS",
            "STOREFRONT_SETTLEMENT__ALKAHEST__TRUSTED_ORACLE_ADDRESSES",
        ),
    ]
    assert value not in repr(renames)


def test_write_and_check_modes_are_strict() -> None:
    with pytest.raises(SettlementMigrationError, match="exactly one"):
        migrate_settlement_config("unused", role="buyer")
    with pytest.raises(SettlementMigrationError, match="requires backup"):
        migrate_settlement_config("unused", role="buyer", write=True)
    with pytest.raises(SettlementMigrationError, match="only valid"):
        migrate_settlement_config("unused", role="buyer", check=True, backup=True)


@pytest.mark.parametrize(
    "path",
    [
        "HostedSettlement.base_url",
        "hosted_settlement.enabled",
        "settlement.hosted",
        "settlement.hosted.base_url",
        "settlement.mechanism_priority",
        "oracle_gated_listings",
        "trusted_oracle_address",
        "Chains.anvil.alkahest_address_config_path",
    ],
)
def test_legacy_config_edit_paths_are_rejected_with_exact_command(path: str) -> None:
    assert is_legacy_settlement_path(path) is True
    with pytest.raises(SettlementMigrationError) as buyer_error:
        reject_legacy_settlement_path(path, command=BUYER_MIGRATION_COMMAND)
    with pytest.raises(SettlementMigrationError) as seller_error:
        reject_legacy_settlement_path(path, command=STOREFRONT_MIGRATION_COMMAND)
    assert f"`{BUYER_MIGRATION_COMMAND}`" in str(buyer_error.value)
    assert f"`{STOREFRONT_MIGRATION_COMMAND}`" in str(seller_error.value)


def test_new_settlement_paths_are_not_treated_as_legacy() -> None:
    for path in (
        "Settlement.priority",
        "Settlement.stripe.base_url",
        "Settlement.alkahest.address_config_path",
        "Identity.identifier",
        "Wallet.private_key",
        "Chains.anvil.rpc_url",
    ):
        assert is_legacy_settlement_path(path) is False
