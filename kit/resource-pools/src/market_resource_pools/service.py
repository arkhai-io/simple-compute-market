"""CRUD, canonical YAML export, and authoritative reconciliation for resource pools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

import yaml
from sqlalchemy.orm import Session, sessionmaker

from market_resource_pools_contracts.asking_rates import (
    ASKING_RATES_POLICY_TAG,
    validate_asking_rates,
)
from market_resource_pools_contracts.hints import (
    CAPACITY_BACKING_POLICY_TAG,
    MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG,
    LISTING_SHAPES_POLICY_TAG,
    PRICING_POLICY_TAG,
    SLA_POLICY_TAG,
    PoolDeclarationProblem,
    pool_declaration_problems,
    validate_hold_preference,
    validate_listing_shapes,
    validate_pricing_rates,
    validate_sla_preference,
)
from .pool_config_handler import PoolConfigHandler
from market_resource_pools_contracts import (
    PoolCreate,
    PoolImportDiff,
    PoolReplace,
    PoolUpdate,
    PoolValidateResponse,
    PoolValidationProblem,
)
from .db import DEFAULT_POOL_ID, ResourcePool


class PoolNotFoundError(Exception):
    pass


class PoolAlreadyExistsError(Exception):
    pass


class PoolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PoolImmutabilityProblem:
    field: str
    code: str
    stored: Any
    supplied: Any
    message: str


def pool_immutability_problems(
    pool: ResourcePool, provider: str, policy_tags: Mapping[str, Any]
) -> tuple[PoolImmutabilityProblem, ...]:
    """Compare routing and admission context without accessing persistence.

    Changing either in place would reinterpret existing members or listings.
    Missing backing may be supplied to repair a stored declaration; provider
    identity always belongs to the pool's lifetime.
    """
    problems: list[PoolImmutabilityProblem] = []
    if provider != pool.provider:
        problems.append(PoolImmutabilityProblem(
            field="provider",
            code="provider_immutable",
            stored=pool.provider,
            supplied=provider,
            message=(
                f"provider of pool '{pool.id}' is fixed at creation as "
                f"'{pool.provider}' and cannot become '{provider}'; declare a "
                "second pool with the intended provider and migrate its members instead"
            ),
        ))
    stored = (pool.policy_tags or {}).get(CAPACITY_BACKING_POLICY_TAG)
    supplied = policy_tags.get(CAPACITY_BACKING_POLICY_TAG)
    if stored is not None and supplied != stored:
        problems.append(PoolImmutabilityProblem(
            field=f"policy_tags.{CAPACITY_BACKING_POLICY_TAG}",
            code="capacity_backing_immutable",
            stored=stored,
            supplied=supplied,
            message=(
                f"{CAPACITY_BACKING_POLICY_TAG} of pool '{pool.id}' is fixed at "
                f"creation as '{stored}' and cannot become '{supplied}'; "
                "declare a second pool with the intended backing instead"
            ),
        ))
    return tuple(problems)


@dataclass(frozen=True)
class PoolDefinition:
    id: str
    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any]
    provider_config: dict[str, Any]
    # Position of the entry in the submitted document, so a problem found
    # against stored state can name the entry the operator must edit.
    source_index: int | None = field(default=None, compare=False)


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
    """Provider-neutral resource-pool administration.

    ``handlers`` must be supplied by the caller — this service does not
    default to any concrete provider implementation (e.g. Ansible), keeping
    it free of any domain-specific import.

    Disabling a pool is a draining operation: it excludes the pool from new
    scheduling decisions without invalidating existing reservations,
    assignments, or active workloads.
    """

    _ROOT_FIELDS = frozenset({"pools"})
    _POOL_FIELDS = frozenset(
        {"id", "label", "provider", "enabled", "policy_tags", "provider_config"}
    )

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: Mapping[str, PoolConfigHandler[Session]],
    ) -> None:
        self._session_factory = session_factory
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

    def _attach_provider_config(self, db: Session, pool: ResourcePool) -> None:
        pool.provider_config = self._handler(pool.provider).read_config(db, pool.id)

    @staticmethod
    def _require_immutable_fields_unchanged(
        pool: ResourcePool, provider: str, policy_tags: Mapping[str, Any]
    ) -> None:
        problems = pool_immutability_problems(pool, provider, policy_tags)
        if problems:
            raise PoolValidationError(problems[0].message)

    def stored_declaration_problems(
        self, db: Session
    ) -> list[tuple[str, PoolDeclarationProblem]]:
        """Every stored pool whose declarations would be refused on write.

        Every write path validates declarations, so a problem here means a row
        was written by something that did not -- most plausibly an older
        version replacing a pool's tags without knowing these ones.
        """
        found: list[tuple[str, PoolDeclarationProblem]] = []
        for pool in db.query(ResourcePool).order_by(ResourcePool.id).all():
            found.extend(
                (pool.id, problem)
                for problem in pool_declaration_problems(pool.policy_tags or {})
            )
        return found

    def require_valid_stored_declarations(self) -> None:
        """Raise naming every stored pool whose declarations are invalid.

        Run at service start so a pool without declarations never reaches a
        projection, where a consumer could not tell it from a producer that
        predates the tags.
        """
        with self._session_factory() as db:
            problems = self.stored_declaration_problems(db)
        if problems:
            raise PoolValidationError(
                "stored resource pools carry invalid declarations: "
                + "; ".join(
                    f"pool '{pool_id}' {problem.tag}: {problem.message}"
                    for pool_id, problem in problems
                )
            )

    def stored_provider_problems(self, db: Session) -> list[tuple[str, str]]:
        """Every stored pool, enabled or not, whose provider no handler serves.

        Handlers are fixed by the composition and every write refuses an
        unknown provider, so such a row was written by a build registering
        other handlers, or from outside the service's write paths. Its records
        are still read, so a disabled pool counts.
        """
        return [
            (pool.id, pool.provider)
            for pool in db.query(ResourcePool).order_by(ResourcePool.id).all()
            if pool.provider not in self._handlers
        ]

    def require_served_stored_providers(self) -> None:
        """Raise naming every stored pool whose provider no handler serves.

        Run at service start: such a pool cannot be read, exported, or
        fulfilled, and no pool document can repair it, since a document cannot
        change a pool's provider.
        """
        with self._session_factory() as db:
            problems = self.stored_provider_problems(db)
        if problems:
            registered = ", ".join(f"'{name}'" for name in sorted(self._handlers)) or "none"
            raise PoolValidationError(
                "stored resource pools name providers no registered handler serves: "
                + "; ".join(
                    f"pool '{pool_id}' provider '{provider}'"
                    for pool_id, provider in problems
                )
                + f" (registered providers: {registered})"
            )

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

    def list_pools_in_session(
        self, db: Session, *, enabled_only: bool = True
    ) -> list[ResourcePool]:
        """Session-scoped pool enumeration for a caller composing one transaction.

        Unlike ``list_pools``, this does not attach ``provider_config``
        (which requires a per-pool handler round trip) and does not expunge
        rows from the session: a caller such as scheduling only needs
        ``id``/``provider``/``enabled`` and is already inside its own
        transaction boundary, so the rows stay attached to that session.
        """
        query = db.query(ResourcePool)
        if enabled_only:
            query = query.filter(ResourcePool.enabled.is_(True))
        return query.order_by(ResourcePool.id).all()

    def get_pool(self, pool_id: str) -> Optional[ResourcePool]:
        with self._session_factory() as db:
            pool = (
                db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
            )
            if pool:
                self._attach_provider_config(db, pool)
                db.expunge(pool)
            return pool

    def get_pool_in_session(self, db: Session, pool_id: str) -> Optional[ResourcePool]:
        """Load a pool and its redacted provider configuration.

        Redacted because most callers of a pool read serialize what they get.
        Fulfillment wants the execution variant below.
        """
        pool = db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
        if pool is not None:
            self._attach_provider_config(db, pool)
        return pool

    def get_pool_for_execution(self, db: Session, pool_id: str) -> Optional[ResourcePool]:
        """Load a pool with secrets resolved, for preparing provider input.

        The only caller is the dispatch path. The attached configuration may
        contain decrypted credentials and must not be serialized into a
        response, an export, or a persisted job snapshot.
        """
        pool = db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none()
        if pool is not None:
            pool.provider_config = self._handler(pool.provider).read_config_for_execution(
                db, pool.id
            )
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
        config = self._normalize_config(data.provider, data.provider_config)
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            self._require_immutable_fields_unchanged(pool, data.provider, data.policy_tags)
            pool.label = data.label
            pool.enabled = data.enabled
            pool.policy_tags = data.policy_tags
            self._handler(data.provider).replace_config(db, pool_id, config)
        return self.get_pool(pool_id)  # type: ignore[return-value]

    def update_pool(self, pool_id: str, data: PoolUpdate) -> ResourcePool:
        with self._session_factory() as db, db.begin():
            pool = self._require_pool(db, pool_id)
            provider = data.provider if data.provider is not None else pool.provider
            current_config = self._handler(pool.provider).read_config(db, pool_id)
            config = (
                data.provider_config
                if data.provider_config is not None
                else current_config
            )
            normalized = self._normalize_config(provider, config)
            self._require_immutable_fields_unchanged(
                pool, provider,
                data.policy_tags if data.policy_tags is not None else (pool.policy_tags or {}),
            )
            if data.label is not None:
                pool.label = data.label
            if data.enabled is not None:
                pool.enabled = data.enabled
            if data.policy_tags is not None:
                pool.policy_tags = data.policy_tags
            if data.provider_config is not None:
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
            if not isinstance(tags, dict):
                problems.append(
                    PoolValidationProblem(
                        path=f"{base}.policy_tags",
                        code="invalid_type",
                        message="policy_tags must be a mapping",
                    )
                )
                entry_valid = False
            else:
                for declaration_problem in pool_declaration_problems(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{declaration_problem.tag}",
                            code=declaration_problem.code,
                            message=declaration_problem.message,
                        )
                    )
                    entry_valid = False
                for hold_problem in validate_hold_preference(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG}",
                            code="invalid_hold_preference",
                            message=hold_problem,
                        )
                    )
                    entry_valid = False
                for sla_problem in validate_sla_preference(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{SLA_POLICY_TAG}",
                            code="invalid_sla_preference",
                            message=sla_problem,
                        )
                    )
                    entry_valid = False
                for shape_problem in validate_listing_shapes(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{LISTING_SHAPES_POLICY_TAG}",
                            code="invalid_listing_shapes",
                            message=shape_problem,
                        )
                    )
                    entry_valid = False
                for rate_problem in validate_asking_rates(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{ASKING_RATES_POLICY_TAG}",
                            code="invalid_asking_rates",
                            message=rate_problem,
                        )
                    )
                    entry_valid = False
                for pricing_problem in validate_pricing_rates(tags):
                    problems.append(
                        PoolValidationProblem(
                            path=f"{base}.policy_tags.{PRICING_POLICY_TAG}",
                            code="invalid_pricing_rates",
                            message=pricing_problem,
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
                        source_index=index,
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

    @staticmethod
    def _immutable_field_problems(
        db: Session, desired: tuple[PoolDefinition, ...]
    ) -> list[PoolValidationProblem]:
        """Adapt stored-state problems to submitted document entry paths."""
        existing = {p.id: p for p in db.query(ResourcePool).all()}
        problems: list[PoolValidationProblem] = []
        for definition in desired:
            pool = existing.get(definition.id)
            if pool is None:
                continue
            for problem in pool_immutability_problems(
                pool, definition.provider, definition.policy_tags
            ):
                problems.append(
                    PoolValidationProblem(
                        path=(
                            f"pools[{definition.source_index}].{problem.field}"
                        ),
                        code=problem.code,
                        message=problem.message,
                    )
                )
        return problems

    @staticmethod
    def _problems_error(problems: Any) -> PoolValidationError:
        # The path names the entry and tag, which is what an operator reading
        # a refused startup import needs in order to find the line to fix.
        return PoolValidationError(
            "; ".join(f"{problem.path}: {problem.message}" for problem in problems)
        )

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
        pool.label = definition.label
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
            stored_problems = self._immutable_field_problems(db, validation.definitions)
            if stored_problems:
                return PoolValidateResponse(
                    valid=False, problems=stored_problems, diff=None
                )
            diff = self._diff(
                self._calculate_reconciliation(db, validation.definitions)
            )
        return PoolValidateResponse(valid=True, problems=[], diff=diff)

    def import_pools(
        self, yaml_text: str, validate_only: bool = False
    ) -> PoolImportDiff:
        validation = self._validate_document(yaml_text)
        if not validation.valid:
            raise self._problems_error(validation.problems)
        if validate_only:
            response = self.validate_pools(yaml_text)
            if not response.valid:
                raise self._problems_error(response.problems)
            assert response.diff is not None
            return response.diff
        with self._session_factory() as db, db.begin():
            return self.import_pools_in_session(db, yaml_text)

    def import_pools_in_session(self, db: Session, yaml_text: str) -> PoolImportDiff:
        """Reconcile inside the caller's transaction, without committing.

        Exists so an import can be composed with other writes that must land
        with it or not at all — a startup importer recording which document it
        applied, most immediately. A digest committed separately from the apply
        it describes is indistinguishable, at the next startup, from one
        recorded before a crash.

        ``import_pools`` keeps its own transaction for the API path, which has
        nothing to compose with.
        """
        validation = self._validate_document(yaml_text)
        if not validation.valid:
            raise self._problems_error(validation.problems)
        stored_problems = self._immutable_field_problems(db, validation.definitions)
        if stored_problems:
            raise self._problems_error(stored_problems)
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
