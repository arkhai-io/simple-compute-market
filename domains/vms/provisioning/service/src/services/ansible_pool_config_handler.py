"""Ansible resource-pool configuration persistence."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from db.models import AnsiblePoolConfig


class AnsiblePoolConfigHandler:
    provider = "ansible"
    _FIELDS = frozenset({"playbook_path", "inventory_group", "extra_vars"})

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(config) - self._FIELDS
        if unknown:
            raise ValueError(f"unknown ansible provider_config fields: {', '.join(sorted(unknown))}")
        playbook_path = config.get("playbook_path")
        inventory_group = config.get("inventory_group")
        extra_vars = config.get("extra_vars", {})
        if not isinstance(playbook_path, str) or not playbook_path.strip():
            raise ValueError("provider_config.playbook_path is required for provider='ansible'")
        if not isinstance(inventory_group, str) or not inventory_group.strip():
            raise ValueError("provider_config.inventory_group is required for provider='ansible'")
        if not isinstance(extra_vars, dict):
            raise ValueError("provider_config.extra_vars must be a mapping")
        return {
            "playbook_path": playbook_path,
            "inventory_group": inventory_group,
            "extra_vars": dict(extra_vars),
        }

    def read_config(self, db: Session, pool_id: str) -> dict[str, Any]:
        row = db.query(AnsiblePoolConfig).filter(AnsiblePoolConfig.pool_id == pool_id).one_or_none()
        if row is None:
            return {}
        return {
            "playbook_path": row.playbook_path,
            "inventory_group": row.inventory_group,
            "extra_vars": row.extra_vars or {},
        }

    def replace_config(self, db: Session, pool_id: str, config: Mapping[str, Any]) -> None:
        normalized = self.validate_config(config)
        row = db.query(AnsiblePoolConfig).filter(AnsiblePoolConfig.pool_id == pool_id).one_or_none()
        if row is None:
            row = AnsiblePoolConfig(pool_id=pool_id)
            db.add(row)
        row.playbook_path = normalized["playbook_path"]
        row.inventory_group = normalized["inventory_group"]
        row.extra_vars = normalized["extra_vars"]

    def delete_config(self, db: Session, pool_id: str) -> None:
        row = db.query(AnsiblePoolConfig).filter(AnsiblePoolConfig.pool_id == pool_id).one_or_none()
        if row is not None:
            db.delete(row)
