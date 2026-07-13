"""CRUD, canonical YAML export, and authoritative reconciliation for resource pools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import yaml
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning import (
    PoolConfigHandler,
    PoolCreate,
    PoolImportDiff,
    PoolReplace,
    PoolUpdate,
    PoolValidateResponse,
    PoolValidationProblem,
)
from db.models import DEFAULT_POOL_ID, ResourcePool


class PoolNotFoundError(Exception):
    pass


class PoolAlreadyExistsError(Exception):
    pass


class PoolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PoolDefinition:
    id: str
    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any]
    provider_config: dict[str, Any]


@dataclass(frozen=True)
class DocumentValidationResult:
    definitions: tuple[PoolDefinition, ...]
    problems: tuple[PoolValidationProblem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class ReconciliationPlan:
    created: tuple[PoolDefinition, ...]
    updated: tuple[PoolDefinition, ...]
    disabled: tuple[str, ...]
    unchanged: tuple[str, ...]


class ResourcePoolService:
    _ROOT_FIELDS = frozenset({"pools"})
    _POOL_FIELDS = frozenset(
        {"id", "label", "provider", "enabled", "policy_tags", "provider_config"}
    )

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: Mapping[str, PoolConfigHandler[Session]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        if handlers is None:
            from services.ansible_pool_config_handler import AnsiblePoolConfigHandler

            handlers = {"ansible": AnsiblePoolConfigHandler()}
        self._handlers = dict(handlers)

    def _handler(self, provider: str) -> PoolConfigHandler[Session]:
        handler = self._handlers.get(provider)
        if handler is None:
            raise PoolValidationError(
                f"no pool config handler registered for provider '{provider}'"
            )
        return handler

    def _normalize_config(
        self, provider: str, config: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise PoolValidationError("provider_config must be a mapping")
        try:
            return self._handler(provider).validate_config(config)
        except ValueError as exc:
            raise PoolValidationError(str(exc)) from exc

    @staticmethod
    def _ensure_default_pool_enabled(pool_id: str, enabled: bool | None) -> None:
        if pool_id == DEFAULT_POOL_ID and enabled is False:
            raise PoolValidationError("the default pool cannot be disabled")

    def _attach_provider_config(self, db: Session, pool: ResourcePool) -> None:
        pool.provider_config = self._handler(pool.provider).read_config(db, pool.id)

    def list_pools(
        self, tag_filter: Optional[dict[str, str]] = None, enabled_only: bool = False
    ) -> list[ResourcePool]:
        with self._session_factory() as db:
            query = db.query(ResourcePool)
            if enabled_only:
                query = query.filter(ResourcePool.enabled.is_(True))
            pools = query.order_by(ResourcePool.id).all()
            if tag_filter:
                pools = [
                    p
                    for p in pools
                    if all(
                        (p.policy_tags or {}).get(k) == v for k, v in tag_filter.items()
                    )
                ]
            for pool in pools:
                self._attach_provider_config(db, pool)
                db.expunge(pool)
            return pools

    def get_pool(self, pool_id: str) -> Optional[ResourcePool]:
        with self._session_factory() as db:
            pool = (
                db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
            )
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
        self._ensure_default_pool_enabled(data.id, data.enabled)
        config = self._normalize_config(data.provider, data.provider_config)
        with self._session_factory() as db, db.begin():
            if db.query(ResourcePool).filter(ResourcePool.id == data.id).one_or_none():
                raise PoolAlreadyExistsError(f"Pool '{data.id}' already exists")
            pool = ResourcePool(
                id=data.id,
                label=data.label,
                provider=data.provider,
                enabled=data.enabled,
                policy_tags=data.policy_tags,
            )
            db.add(pool)
            db.flush()
            self._handler(data.provider).replace_config(db, data.id, config)
        return self.get_pool(data.id)  # type: ignore[return-value]

    def replace_pool(self, pool_id: str, data: PoolReplace) -> ResourcePool:
        self._ensure_default_pool_enabled(pool_id, data.enabled)
        config = self._normalize_config(data.provider, data.provider_config)
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            old_provider = pool.provider
            if old_provider != data.provider:
                self._handler(old_provider).delete_config(db, pool_id)
            pool.label = data.label
            pool.provider = data.provider
            pool.enabled = data.enabled
            pool.policy_tags = data.policy_tags
            self._handler(data.provider).replace_config(db, pool_id, config)
        return self.get_pool(pool_id)  # type: ignore[return-value]

    def update_pool(self, pool_id: str, data: PoolUpdate) -> ResourcePool:
        self._ensure_default_pool_enabled(pool_id, data.enabled)
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            provider = data.provider or pool.provider
            current_config = self._handler(pool.provider).read_config(db, pool_id)
            config = (
                data.provider_config
                if data.provider_config is not None
                else current_config
            )
            normalized = self._normalize_config(provider, config)
            if provider != pool.provider:
                self._handler(pool.provider).delete_config(db, pool_id)
            if data.label is not None:
                pool.label = data.label
            if data.provider is not None:
                pool.provider = data.provider
            if data.enabled is not None:
                pool.enabled = data.enabled
            if data.policy_tags is not None:
                pool.policy_tags = data.policy_tags
            if data.provider is not None or data.provider_config is not None:
                self._handler(provider).replace_config(db, pool_id, normalized)
        return self.get_pool(pool_id)  # type: ignore[return-value]

    def enable_pool(self, pool_id: str) -> ResourcePool:
        return self.update_pool(pool_id, PoolUpdate(enabled=True))

    def disable_pool(self, pool_id: str) -> ResourcePool:
        return self.update_pool(pool_id, PoolUpdate(enabled=False))

    def delete_pool(self, pool_id: str) -> None:
        """Defensive guard: resource pools intentionally support disable, not hard-delete.

        The DELETE route calls ``disable_pool``. This method exists so a future
        internal caller cannot accidentally introduce hard deletion without
        revisiting the pool lifecycle and referential-integrity rules.
        """
        if pool_id == DEFAULT_POOL_ID:
            raise PoolValidationError("the default pool cannot be deleted")
        raise PoolValidationError(
            "resource pools use disable semantics and cannot be hard-deleted"
        )

    def _validate_document(self, yaml_text: str) -> DocumentValidationResult:
        problems: list[PoolValidationProblem] = []
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            return DocumentValidationResult(
                (),
                (
                    PoolValidationProblem(
                        path="$",
                        code="invalid_yaml",
                        message=f"invalid YAML: {exc}",
                    ),
                ),
            )
        if not isinstance(parsed, dict):
            return DocumentValidationResult(
                (),
                (
                    PoolValidationProblem(
                        path="$",
                        code="invalid_type",
                        message="YAML root must be a mapping",
                    ),
                ),
            )
        for field in sorted(set(parsed) - self._ROOT_FIELDS):
            problems.append(
                PoolValidationProblem(
                    path=field,
                    code="unknown_field",
                    message=f"unknown top-level field '{field}'",
                )
            )
        entries = parsed.get("pools")
        if not isinstance(entries, list):
            problems.append(
                PoolValidationProblem(
                    path="pools",
                    code="invalid_type",
                    message="YAML must have a top-level 'pools' list",
                )
            )
            return DocumentValidationResult((), tuple(problems))

        definitions: list[PoolDefinition] = []
        seen: set[str] = set()
        declared_ids: set[str] = set()
        for index, entry in enumerate(entries):
            base = f"pools[{index}]"
            if not isinstance(entry, dict):
                problems.append(
                    PoolValidationProblem(
                        path=base,
                        code="invalid_type",
                        message=f"{base} must be a mapping",
                    )
                )
                continue
            for field in sorted(set(entry) - self._POOL_FIELDS):
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.{field}",
                        code="unknown_field",
                        message=f"unknown pool field '{field}'",
                    )
                )

            pool_id = entry.get("id")
            label = entry.get("label")
            provider = entry.get("provider")
            entry_valid = True
            if not isinstance(pool_id, str) or not pool_id.strip():
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.id",
                        code="required_field",
                        message="pool id is required",
                    )
                )
                entry_valid = False
                pool_id = None
            else:
                declared_ids.add(pool_id)
                if pool_id in seen:
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.id",
                            code="duplicate_id",
                            message=f"duplicate pool id '{pool_id}'",
                        )
                    )
                    entry_valid = False
                else:
                    seen.add(pool_id)
            if not isinstance(label, str) or not label.strip():
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.label",
                        code="required_field",
                        message="pool label is required",
                    )
                )
                entry_valid = False
            if not isinstance(provider, str) or not provider.strip():
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.provider",
                        code="required_field",
                        message="pool provider is required",
                    )
                )
                entry_valid = False

            enabled = entry.get("enabled", True)
            tags = entry.get("policy_tags", {})
            config = entry.get("provider_config", {})
            if not isinstance(enabled, bool):
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.enabled",
                        code="invalid_type",
                        message="enabled must be boolean",
                    )
                )
                entry_valid = False
            elif pool_id == DEFAULT_POOL_ID and enabled is False:
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.enabled",
                        code="default_pool_disabled",
                        message="the default pool must remain enabled",
                    )
                )
                entry_valid = False
            if not isinstance(tags, dict):
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.policy_tags",
                        code="invalid_type",
                        message="policy_tags must be a mapping",
                    )
                )
                entry_valid = False
            if not isinstance(config, Mapping):
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.provider_config",
                        code="invalid_type",
                        message="provider_config must be a mapping",
                    )
                )
                entry_valid = False
                normalized = None
            elif isinstance(provider, str) and provider.strip():
                handler = self._handlers.get(provider)
                if handler is None:
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.provider",
                            code="unknown_provider",
                            message=f"no pool config handler registered for provider '{provider}'",
                        )
                    )
                    entry_valid = False
                    normalized = None
                else:
                    normalized, config_problems = handler.validate_config_problems(
                        config
                    )
                    for problem in config_problems:
                        problems.append(
                            PoolValidationProblem(
                                path=f"{base}.provider_config.{problem.path}",
                                code=problem.code,
                                message=problem.message,
                            )
                        )
                    if config_problems:
                        entry_valid = False
            else:
                normalized = None

            if entry_valid:
                assert (
                    pool_id is not None
                    and isinstance(label, str)
                    and isinstance(provider, str)
                )
                assert isinstance(tags, dict) and normalized is not None
                definitions.append(
                    PoolDefinition(
                        pool_id,
                        label,
                        provider,
                        enabled,
                        dict(tags),
                        normalized,
                    )
                )

        if DEFAULT_POOL_ID not in declared_ids:
            problems.append(
                PoolValidationProblem(
                    path="pools",
                    code="missing_default_pool",
                    message=f"authoritative pool definitions must include '{DEFAULT_POOL_ID}'",
                )
            )
        return DocumentValidationResult(tuple(definitions), tuple(problems))

    def _calculate_reconciliation(
        self, db: Session, desired: tuple[PoolDefinition, ...]
    ) -> ReconciliationPlan:
        existing = {p.id: p for p in db.query(ResourcePool).all()}
        created: list[PoolDefinition] = []
        updated: list[PoolDefinition] = []
        unchanged: list[str] = []
        desired_ids = {d.id for d in desired}
        for definition in desired:
            pool = existing.get(definition.id)
            if pool is None:
                created.append(definition)
                continue
            current_config = self._handler(pool.provider).read_config(db, pool.id)
            same = (
                pool.label == definition.label
                and pool.provider == definition.provider
                and pool.enabled == definition.enabled
                and (pool.policy_tags or {}) == definition.policy_tags
                and current_config == definition.provider_config
            )
            (unchanged if same else updated).append(
                definition.id if same else definition
            )
        disabled = tuple(
            sorted(
                pid
                for pid, pool in existing.items()
                if pid not in desired_ids and pool.enabled
            )
        )
        return ReconciliationPlan(
            tuple(created), tuple(updated), disabled, tuple(sorted(unchanged))
        )

    def _apply_definition(self, db: Session, definition: PoolDefinition) -> None:
        pool = (
            db.query(ResourcePool)
            .filter(ResourcePool.id == definition.id)
            .one_or_none()
        )
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
        pool.label = definition.label
        pool.provider = definition.provider
        pool.enabled = definition.enabled
        pool.policy_tags = definition.policy_tags
        self._handler(definition.provider).replace_config(
            db, definition.id, definition.provider_config
        )

    def _apply_reconciliation(self, db: Session, plan: ReconciliationPlan) -> None:
        for definition in (*plan.created, *plan.updated):
            self._apply_definition(db, definition)
        if plan.disabled:
            db.query(ResourcePool).filter(ResourcePool.id.in_(plan.disabled)).update(
                {ResourcePool.enabled: False}, synchronize_session=False
            )

    @staticmethod
    def _diff(plan: ReconciliationPlan) -> PoolImportDiff:
        return PoolImportDiff(
            created=[p.id for p in plan.created],
            updated=[p.id for p in plan.updated],
            disabled=list(plan.disabled),
            unchanged=list(plan.unchanged),
        )

    def validate_pools(self, yaml_text: str) -> PoolValidateResponse:
        validation = self._validate_document(yaml_text)
        if not validation.valid:
            return PoolValidateResponse(
                valid=False, problems=list(validation.problems), diff=None
            )
        with self._session_factory() as db:
            diff = self._diff(
                self._calculate_reconciliation(db, validation.definitions)
            )
        return PoolValidateResponse(valid=True, problems=[], diff=diff)

    def import_pools(
        self, yaml_text: str, validate_only: bool = False
    ) -> PoolImportDiff:
        validation = self._validate_document(yaml_text)
        if not validation.valid:
            message = "; ".join(problem.message for problem in validation.problems)
            raise PoolValidationError(message)
        if validate_only:
            response = self.validate_pools(yaml_text)
            assert response.diff is not None
            return response.diff
        with self._session_factory() as db, db.begin():
            plan = self._calculate_reconciliation(db, validation.definitions)
            diff = self._diff(plan)
            self._apply_reconciliation(db, plan)
        return diff

    def export_pools_yaml(self) -> str:
        pools = self.list_pools()
        document = {
            "pools": [
                {
                    "id": p.id,
                    "label": p.label,
                    "provider": p.provider,
                    "enabled": p.enabled,
                    "policy_tags": p.policy_tags or {},
                    "provider_config": p.provider_config,
                }
                for p in pools
            ]
        }
        return yaml.safe_dump(document, sort_keys=False)
