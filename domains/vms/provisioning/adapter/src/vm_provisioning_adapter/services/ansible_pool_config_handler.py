"""Ansible resource-pool configuration persistence."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from compute_provisioning import PoolConfigValidationProblem
from compute_provisioning_service.db.models import AnsiblePoolConfig
from vm_provisioning_adapter.requirement_delegates import (
    DEFAULT_REQUIREMENT_DELEGATE,
    registered_requirement_delegate_names,
)

# The DB # column is still NOT NULL with no migration this round.
# This is a compatibility placeholder only — nothing reads it.
_UNUSED_INVENTORY_GROUP_COMPAT_VALUE = "__unused__"


class AnsiblePoolConfigHandler:
    provider = "ansible"
    _FIELDS = frozenset(
        {
            "playbook_path",
            "requirement_delegate",
            "extra_vars",
            "default_vm_ram",
            "default_vm_vcpus",
            "default_vm_disk_size",
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
        if problems:
            return None, tuple(problems)
        return {
            "playbook_path": playbook_path,
            "requirement_delegate": requirement_delegate,
            "extra_vars": dict(extra_vars),
            **normalized_defaults,
        }, ()

    def read_config(self, db: Session, pool_id: str) -> dict[str, Any]:
        row = (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )
        if row is None:
            return {}
        return {
            "playbook_path": row.playbook_path,
            "requirement_delegate": row.requirement_delegate,
            "extra_vars": row.extra_vars or {},
            "default_vm_ram": row.default_vm_ram,
            "default_vm_vcpus": row.default_vm_vcpus,
            "default_vm_disk_size": row.default_vm_disk_size,
        }

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

    def delete_config(self, db: Session, pool_id: str) -> None:
        row = (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )
        if row is not None:
            db.delete(row)
