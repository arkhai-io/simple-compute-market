"""CRUD, canonical YAML export, and authoritative reconciliation for resource pools."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import yaml
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning import PoolConfigHandler
from db.models import DEFAULT_POOL_ID, ResourcePool
from provisioning_client.models import PoolCreate, PoolImportDiff, PoolReplace, PoolUpdate


class PoolNotFoundError(Exception): pass
class PoolAlreadyExistsError(Exception): pass
class PoolValidationError(ValueError): pass


@dataclass(frozen=True)
class PoolDefinition:
    id: str
    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any]
    provider_config: dict[str, Any]


@dataclass(frozen=True)
class ReconciliationPlan:
    created: tuple[PoolDefinition, ...]
    updated: tuple[PoolDefinition, ...]
    disabled: tuple[str, ...]
    unchanged: tuple[str, ...]


class ResourcePoolService:
    _ROOT_FIELDS = frozenset({"pools"})
    _POOL_FIELDS = frozenset({"id", "label", "provider", "enabled", "policy_tags", "provider_config"})

    def __init__(self, session_factory: sessionmaker[Session], handlers: Mapping[str, PoolConfigHandler[Session]] | None = None) -> None:
        self._session_factory = session_factory
        if handlers is None:
            from services.ansible_pool_config_handler import AnsiblePoolConfigHandler
            handlers = {"ansible": AnsiblePoolConfigHandler()}
        self._handlers = dict(handlers)

    def _handler(self, provider: str) -> PoolConfigHandler[Session]:
        handler = self._handlers.get(provider)
        if handler is None:
            raise PoolValidationError(f"no pool config handler registered for provider '{provider}'")
        return handler

    def _normalize_config(self, provider: str, config: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise PoolValidationError("provider_config must be a mapping")
        try:
            return self._handler(provider).validate_config(config)
        except ValueError as exc:
            raise PoolValidationError(str(exc)) from exc

    def _attach_provider_config(self, db: Session, pool: ResourcePool) -> None:
        pool.provider_config = self._handler(pool.provider).read_config(db, pool.id)

    def list_pools(self, tag_filter: Optional[dict[str, str]] = None, enabled_only: bool = False) -> list[ResourcePool]:
        with self._session_factory() as db:
            query = db.query(ResourcePool)
            if enabled_only:
                query = query.filter(ResourcePool.enabled.is_(True))
            pools = query.order_by(ResourcePool.id).all()
            if tag_filter:
                pools = [p for p in pools if all((p.policy_tags or {}).get(k) == v for k, v in tag_filter.items())]
            for pool in pools:
                self._attach_provider_config(db, pool)
                db.expunge(pool)
            return pools

    def get_pool(self, pool_id: str) -> Optional[ResourcePool]:
        with self._session_factory() as db:
            pool = db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
            if pool:
                self._attach_provider_config(db, pool)
                db.expunge(pool)
            return pool

    def _require_pool(self, db: Session, pool_id: str) -> ResourcePool:
        pool = db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
        if pool is None:
            raise PoolNotFoundError(f"Pool '{pool_id}' not found")
        return pool

    def create_pool(self, data: PoolCreate) -> ResourcePool:
        config = self._normalize_config(data.provider, data.provider_config)
        with self._session_factory() as db, db.begin():
            if db.query(ResourcePool).filter(ResourcePool.id == data.id).one_or_none():
                raise PoolAlreadyExistsError(f"Pool '{data.id}' already exists")
            pool = ResourcePool(id=data.id, label=data.label, provider=data.provider, enabled=data.enabled, policy_tags=data.policy_tags)
            db.add(pool); db.flush()
            self._handler(data.provider).replace_config(db, data.id, config)
        return self.get_pool(data.id)  # type: ignore[return-value]

    def replace_pool(self, pool_id: str, data: PoolReplace) -> ResourcePool:
        config = self._normalize_config(data.provider, data.provider_config)
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            old_provider = pool.provider
            if old_provider != data.provider:
                self._handler(old_provider).delete_config(db, pool_id)
            pool.label = data.label; pool.provider = data.provider; pool.enabled = data.enabled; pool.policy_tags = data.policy_tags
            self._handler(data.provider).replace_config(db, pool_id, config)
        return self.get_pool(pool_id)  # type: ignore[return-value]

    def update_pool(self, pool_id: str, data: PoolUpdate) -> ResourcePool:
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            provider = data.provider or pool.provider
            current_config = self._handler(pool.provider).read_config(db, pool_id)
            config = data.provider_config if data.provider_config is not None else current_config
            normalized = self._normalize_config(provider, config)
            if provider != pool.provider:
                self._handler(pool.provider).delete_config(db, pool_id)
            if data.label is not None: pool.label = data.label
            if data.provider is not None: pool.provider = data.provider
            if data.enabled is not None: pool.enabled = data.enabled
            if data.policy_tags is not None: pool.policy_tags = data.policy_tags
            if data.provider is not None or data.provider_config is not None:
                self._handler(provider).replace_config(db, pool_id, normalized)
        return self.get_pool(pool_id)  # type: ignore[return-value]

    def enable_pool(self, pool_id: str) -> ResourcePool:
        return self.update_pool(pool_id, PoolUpdate(enabled=True))

    def disable_pool(self, pool_id: str) -> ResourcePool:
        return self.update_pool(pool_id, PoolUpdate(enabled=False))

    def delete_pool(self, pool_id: str) -> None:
        if pool_id == DEFAULT_POOL_ID:
            raise PoolValidationError("the default pool cannot be deleted")
        raise PoolValidationError("resource pools use disable semantics and cannot be hard-deleted")

    def _validate_document(self, yaml_text: str) -> tuple[PoolDefinition, ...]:
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise PoolValidationError(f"invalid YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PoolValidationError("YAML root must be a mapping")
        unknown_root = set(parsed) - self._ROOT_FIELDS
        if unknown_root:
            raise PoolValidationError(f"unknown top-level fields: {', '.join(sorted(unknown_root))}")
        entries = parsed.get("pools")
        if not isinstance(entries, list):
            raise PoolValidationError("YAML must have a top-level 'pools' list")
        definitions: list[PoolDefinition] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise PoolValidationError(f"pools[{index}] must be a mapping")
            unknown = set(entry) - self._POOL_FIELDS
            if unknown:
                raise PoolValidationError(f"pool entry has unknown fields: {', '.join(sorted(unknown))}")
            pool_id = entry.get("id")
            label = entry.get("label")
            provider = entry.get("provider")
            if not isinstance(pool_id, str) or not pool_id.strip(): raise PoolValidationError(f"pools[{index}].id is required")
            if pool_id in seen: raise PoolValidationError(f"duplicate pool id '{pool_id}'")
            seen.add(pool_id)
            if not isinstance(label, str) or not label.strip(): raise PoolValidationError(f"pool '{pool_id}' label is required")
            if not isinstance(provider, str) or not provider.strip(): raise PoolValidationError(f"pool '{pool_id}' provider is required")
            enabled = entry.get("enabled", True)
            tags = entry.get("policy_tags", {})
            if not isinstance(enabled, bool): raise PoolValidationError(f"pool '{pool_id}' enabled must be boolean")
            if not isinstance(tags, dict): raise PoolValidationError(f"pool '{pool_id}' policy_tags must be a mapping")
            config = self._normalize_config(provider, entry.get("provider_config", {}))
            definitions.append(PoolDefinition(pool_id, label, provider, enabled, dict(tags), config))
        if DEFAULT_POOL_ID not in seen:
            raise PoolValidationError(f"authoritative pool definitions must include '{DEFAULT_POOL_ID}'")
        return tuple(definitions)

    def _calculate_reconciliation(self, db: Session, desired: tuple[PoolDefinition, ...]) -> ReconciliationPlan:
        existing = {p.id: p for p in db.query(ResourcePool).all()}
        created: list[PoolDefinition] = []; updated: list[PoolDefinition] = []; unchanged: list[str] = []
        desired_ids = {d.id for d in desired}
        for definition in desired:
            pool = existing.get(definition.id)
            if pool is None:
                created.append(definition); continue
            current_config = self._handler(pool.provider).read_config(db, pool.id)
            same = (pool.label == definition.label and pool.provider == definition.provider and pool.enabled == definition.enabled and (pool.policy_tags or {}) == definition.policy_tags and current_config == definition.provider_config)
            (unchanged if same else updated).append(definition.id if same else definition)
        disabled = tuple(sorted(pid for pid, pool in existing.items() if pid not in desired_ids and pool.enabled))
        return ReconciliationPlan(tuple(created), tuple(updated), disabled, tuple(sorted(unchanged)))

    def _apply_definition(self, db: Session, definition: PoolDefinition) -> None:
        pool = db.query(ResourcePool).filter(ResourcePool.id == definition.id).one_or_none()
        if pool is None:
            pool = ResourcePool(
                id=definition.id,
                label=definition.label,
                provider=definition.provider,
                enabled=definition.enabled,
                policy_tags=definition.policy_tags,
            )
            db.add(pool)
            db.flush()
            old_provider = None
        else:
            old_provider = pool.provider
        if old_provider and old_provider != definition.provider:
            self._handler(old_provider).delete_config(db, definition.id)
        pool.label = definition.label; pool.provider = definition.provider; pool.enabled = definition.enabled; pool.policy_tags = definition.policy_tags
        self._handler(definition.provider).replace_config(db, definition.id, definition.provider_config)

    def _apply_reconciliation(self, db: Session, plan: ReconciliationPlan) -> None:
        for definition in (*plan.created, *plan.updated): self._apply_definition(db, definition)
        if plan.disabled:
            db.query(ResourcePool).filter(ResourcePool.id.in_(plan.disabled)).update({ResourcePool.enabled: False}, synchronize_session=False)

    @staticmethod
    def _diff(plan: ReconciliationPlan) -> PoolImportDiff:
        return PoolImportDiff(created=[p.id for p in plan.created], updated=[p.id for p in plan.updated], disabled=list(plan.disabled), unchanged=list(plan.unchanged), rejected=[])

    def import_pools(self, yaml_text: str, validate_only: bool = False) -> PoolImportDiff:
        desired = self._validate_document(yaml_text)
        with self._session_factory() as db:
            if validate_only:
                return self._diff(self._calculate_reconciliation(db, desired))
            with db.begin():
                plan = self._calculate_reconciliation(db, desired)
                diff = self._diff(plan)
                self._apply_reconciliation(db, plan)
            return diff

    def export_pools_yaml(self) -> str:
        pools = self.list_pools()
        document = {"pools": [{"id": p.id, "label": p.label, "provider": p.provider, "enabled": p.enabled, "policy_tags": p.policy_tags or {}, "provider_config": p.provider_config} for p in pools]}
        return yaml.safe_dump(document, sort_keys=False)
