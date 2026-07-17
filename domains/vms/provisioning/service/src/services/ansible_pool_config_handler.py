"""Ansible resource-pool configuration persistence."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from compute_provisioning import PoolConfigValidationProblem
from db.models import AnsiblePoolConfig

# The DB # column is still NOT NULL with no migration this round.
# This is a compatibility placeholder only — nothing reads it.
_UNUSED_INVENTORY_GROUP_COMPAT_VALUE = "__unused__"


class AnsiblePoolConfigHandler:
    provider = "ansible"
    _FIELDS = frozenset({"playbook_path", "extra_vars"})

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
        extra_vars = config.get("extra_vars", {})
        if not isinstance(playbook_path, str) or not playbook_path.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="playbook_path",
                    code="required_field",
                    message="provider_config.playbook_path is required for provider='ansible'",
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
        if problems:
            return None, tuple(problems)
        return {
            "playbook_path": playbook_path,
            "extra_vars": dict(extra_vars),
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
            "extra_vars": row.extra_vars or {},
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
        row.inventory_group = _UNUSED_INVENTORY_GROUP_COMPAT_VALUE
        row.extra_vars = normalized["extra_vars"]

    def delete_config(self, db: Session, pool_id: str) -> None:
        row = (
            db.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == pool_id)
            .one_or_none()
        )
        if row is not None:
            db.delete(row)
