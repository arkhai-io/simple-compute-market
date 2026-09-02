"""Ansible resource-pool configuration persistence."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from compute_provisioning import PoolConfigValidationProblem
from compute_provisioning_service.crypto import decrypt_key
from compute_provisioning_service.db.models import AnsiblePoolConfig, Relay
from vm_provisioning_adapter.requirement_delegates import (
    DEFAULT_REQUIREMENT_DELEGATE,
    registered_requirement_delegate_names,
)

# The DB # column is still NOT NULL with no migration this round.
# This is a compatibility placeholder only — nothing reads it.
_UNUSED_INVENTORY_GROUP_COMPAT_VALUE = "__unused__"


class AnsiblePoolConfigHandler:
    provider = "ansible"

    def __init__(self, settings: Any | None = None) -> None:
        # Settings carry the key that decrypts a relay's admission token. The
        # handler is constructed without them in contexts that only read or
        # write non-secret configuration; an execution read then finds no key
        # and fails loudly rather than returning a config that silently omits
        # the token.
        self._settings = settings

    _FIELDS = frozenset(
        {
            "playbook_path",
            "requirement_delegate",
            "extra_vars",
            "default_vm_ram",
            "default_vm_vcpus",
            "default_vm_disk_size",
            # A reference to a relay, never the rendezvous itself. The address,
            # window, and token belong to the relay row because every pool
            # pointing at one relay shares them; holding a window here would
            # let two pools allocate from one listening namespace under
            # disagreeing bounds.
            "relay_id",
        }
    )

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        normalized, problems = self.validate_config_problems(config)
        if problems:
            raise ValueError(problems[0].message)
        assert normalized is not None
        return normalized

    def validate_config_problems(
        self, config: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, tuple[PoolConfigValidationProblem, ...]]:
        problems: list[PoolConfigValidationProblem] = []
        for field in sorted(set(config) - self._FIELDS):
            problems.append(
                PoolConfigValidationProblem(
                    path=field,
                    code="unknown_field",
                    message=f"unknown ansible provider_config field '{field}'",
                )
            )
        playbook_path = config.get("playbook_path")
        requirement_delegate = config.get(
            "requirement_delegate", DEFAULT_REQUIREMENT_DELEGATE
        )
        extra_vars = config.get("extra_vars", {})
        if not isinstance(playbook_path, str) or not playbook_path.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="playbook_path",
                    code="required_field",
                    message="provider_config.playbook_path is required for provider='ansible'",
                )
            )
        if not isinstance(requirement_delegate, str) or not requirement_delegate.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="requirement_delegate",
                    code="required_field",
                    message="provider_config.requirement_delegate is required for provider='ansible'",
                )
            )
        elif requirement_delegate not in registered_requirement_delegate_names():
            problems.append(
                PoolConfigValidationProblem(
                    path="requirement_delegate",
                    code="unknown_value",
                    message=f"unknown Ansible requirement delegate '{requirement_delegate}'",
                )
            )
        if not isinstance(extra_vars, dict):
            problems.append(
                PoolConfigValidationProblem(
                    path="extra_vars",
                    code="invalid_type",
                    message="provider_config.extra_vars must be a mapping",
                )
            )
        normalized_defaults: dict[str, Any] = {}
        for field in ("default_vm_ram", "default_vm_vcpus"):
            if field not in config or config[field] is None:
                normalized_defaults[field] = None
                continue
            value = config[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                problems.append(
                    PoolConfigValidationProblem(
                        path=field,
                        code="invalid_type",
                        message=f"provider_config.{field} must be a positive integer",
                    )
                )
            else:
                normalized_defaults[field] = value
        disk_size = config.get("default_vm_disk_size")
        if disk_size is None:
            normalized_defaults["default_vm_disk_size"] = None
        elif not isinstance(disk_size, str) or not disk_size.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="default_vm_disk_size",
                    code="invalid_type",
                    message="provider_config.default_vm_disk_size must be a non-empty string",
                )
            )
        else:
            normalized_defaults["default_vm_disk_size"] = disk_size
        relay_id = config.get("relay_id")
        if relay_id is not None and (
            not isinstance(relay_id, str) or not relay_id.strip()
        ):
            problems.append(
                PoolConfigValidationProblem(
                    path="relay_id",
                    code="invalid_type",
                    message="provider_config.relay_id must be a non-empty string",
                )
            )
            relay_id = None
        if problems:
            return None, tuple(problems)
        return {
            "playbook_path": playbook_path,
            "requirement_delegate": requirement_delegate,
            "extra_vars": dict(extra_vars),
            "relay_id": relay_id,
            **normalized_defaults,
        }, ()

    def read_config(self, db: Session, pool_id: str) -> dict[str, Any]:
        """Configuration with no secret in it, and the relay unresolved.

        Serves the pool endpoints, the export document, the administrative
        read-modify-write, and reconciliation comparison. It returns the relay
        *reference* and never the rendezvous behind it, so no admission token
        can reach a serialized response and reconciliation cannot diverge on a
        field one side is unable to see.
        """
        row = self._row(db, pool_id)
        if row is None:
            return {}
        return {
            "playbook_path": row.playbook_path,
            "requirement_delegate": row.requirement_delegate,
            "extra_vars": row.extra_vars or {},
            "default_vm_ram": row.default_vm_ram,
            "default_vm_vcpus": row.default_vm_vcpus,
            "default_vm_disk_size": row.default_vm_disk_size,
            "relay_id": row.relay_id,
        }

    def read_config_for_execution(self, db: Session, pool_id: str) -> dict[str, Any]:
        """Configuration with the relay resolved and its token decrypted.

        Reserved for preparing provider input at dispatch. The resolved fields
        are read-only here: they are not accepted on a write, because they
        describe the relay rather than the pool.

        A missing or disabled relay resolves to no relay fields rather than to
        an error, so the single rejection point for an unusable relay stays in
        pre-dispatch validation instead of being split across two layers that
        could disagree.
        """
        config = self.read_config(db, pool_id)
        relay_id = config.get("relay_id")
        if not relay_id:
            return config
        relay = db.get(Relay, relay_id)
        if relay is None or not relay.enabled:
            return config
        config.update(
            {
                "relay_addr": relay.relay_addr,
                "relay_port": relay.relay_port,
                "vm_port_range_start": relay.vm_port_range_start,
                "vm_port_range_count": relay.vm_port_range_count,
                "relay_token": self._decrypt_token(relay),
            }
        )
        return config

    def _decrypt_token(self, relay: Relay) -> str | None:
        if not relay.relay_token_encrypted:
            return None
        return decrypt_key(relay.relay_token_encrypted, self._encryption_key())

    def _encryption_key(self) -> str:
        settings = self._settings
        if settings is None:
            return ""
        return str(getattr(settings, "ssh_decryption_key", "") or "")

    @staticmethod
    def _row(db: Session, pool_id: str) -> AnsiblePoolConfig | None:
        return (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )

    def replace_config(
        self, db: Session, pool_id: str, config: Mapping[str, Any]
    ) -> None:
        normalized = self.validate_config(config)
        row = (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )
        if row is None:
            row = AnsiblePoolConfig(pool_id=pool_id)
            db.add(row)
        row.playbook_path = normalized["playbook_path"]
        row.requirement_delegate = normalized["requirement_delegate"]
        row.inventory_group = _UNUSED_INVENTORY_GROUP_COMPAT_VALUE
        row.extra_vars = normalized["extra_vars"]
        row.default_vm_ram = normalized["default_vm_ram"]
        row.default_vm_vcpus = normalized["default_vm_vcpus"]
        row.default_vm_disk_size = normalized["default_vm_disk_size"]
        row.relay_id = normalized["relay_id"]

    def delete_config(self, db: Session, pool_id: str) -> None:
        row = (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )
        if row is not None:
            db.delete(row)
