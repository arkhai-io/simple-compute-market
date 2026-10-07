"""Domain adapter contributions and startup-time composition validation.

Each compute domain describes what it contributes as an ``ExecutorAdapterBundle``;
the provisioning service's composition root passes every installed bundle to
``compose_adapter_bundles``, which refuses an ambiguous or incomplete
registration before anything starts. The contract types live in the family kit
so a domain adapter can build its bundle without depending on the deployed
service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .adapters import JobExecutorTable
from .definition_documents import DefinitionDocumentContribution
from .release_effects import ReleaseEffect, ReleaseEffects
from .inventory_views import InventoryViewProjection, InventoryViews, compose_inventory_views
from .jobs.executor import JobExecutor
from .startup import ComputeProvisioningBackgroundTask
from market_fulfillment import FulfillmentProvider, ProviderRegistry, provider_needs_host


@dataclass(frozen=True)
class ExecutorAdapterContribution:
    """What one offering mode contributes: its job executors.

    ``job_executors`` maps each job action of the mode to what runs it. Work
    reaches these executors only through fulfillment and the domain's own
    operations; nothing submits an action to them from outside. A mode
    contributes nothing to release: every mode's lease is released through its
    fulfillment aggregate, whose provider the pool already names.
    """

    offering_mode: str
    job_executors: Mapping[str, JobExecutor]


@dataclass(frozen=True)
class ExecutorAdapterBundle:
    """Everything one compute domain contributes to service composition.

    A domain's routes are not part of it: the service mounts them when it
    builds the app, before any bundle exists, through the router factories the
    adapter exports. Execution readiness is not either: the composition root
    reports it from the executors it composed.

    ``release_effects`` run whenever the site releases a reservation's
    capacity, in that transaction; ``definition_documents`` are imported at
    startup before the service's own documents; ``background_tasks`` start
    with the service's own workers.
    """

    name: str
    executors: tuple[ExecutorAdapterContribution, ...]
    fulfillment_providers: Mapping[str, FulfillmentProvider] = field(default_factory=dict)
    pool_config_handlers: Mapping[str, Any] = field(default_factory=dict)
    inventory_views: tuple[InventoryViewProjection, ...] = ()
    release_effects: tuple[ReleaseEffect, ...] = ()
    definition_documents: tuple[DefinitionDocumentContribution, ...] = ()
    background_tasks: tuple[ComputeProvisioningBackgroundTask, ...] = ()


@dataclass(frozen=True)
class ComposedComputeAdapters:
    provider_registry: ProviderRegistry
    pool_config_handlers: Mapping[str, Any]
    inventory_views: InventoryViews
    job_executors: JobExecutorTable
    definition_documents: tuple[DefinitionDocumentContribution, ...] = ()
    background_tasks: tuple[ComputeProvisioningBackgroundTask, ...] = ()


#: Document kinds the service imports itself; a contribution may not claim one.
SERVICE_DEFINITION_DOCUMENT_KINDS = frozenset({"pools", "capacity"})


def _validate_executor(bundle_name: str, contribution: ExecutorAdapterContribution) -> str:
    offering_mode = str(contribution.offering_mode or "").strip()
    if not offering_mode:
        raise ValueError(f"adapter bundle {bundle_name!r} has an executor without offering_mode")
    if offering_mode != contribution.offering_mode:
        raise ValueError(
            f"adapter bundle {bundle_name!r} offering mode "
            f"{contribution.offering_mode!r} is not canonical"
        )
    if not contribution.job_executors:
        raise ValueError(
            f"adapter bundle {bundle_name!r} executor {offering_mode!r} "
            "contributes no job executors"
        )
    return offering_mode


def _validate_provider_pairing(bundle: ExecutorAdapterBundle) -> None:
    provider_names = frozenset(bundle.fulfillment_providers)
    handler_names = frozenset(bundle.pool_config_handlers)
    if provider_names == handler_names:
        return

    detail = []
    missing_handlers = sorted(provider_names - handler_names)
    missing_providers = sorted(handler_names - provider_names)
    if missing_handlers:
        detail.append(
            "missing pool config handler(s) for "
            + ", ".join(repr(name) for name in missing_handlers)
        )
    if missing_providers:
        detail.append(
            "missing fulfillment provider(s) for "
            + ", ".join(repr(name) for name in missing_providers)
        )
    raise ValueError(
        f"adapter bundle {bundle.name!r} has incomplete provider contributions: "
        + "; ".join(detail)
    )


def _validate_pool_config_handler(
    *, bundle_name: str, provider_name: str, handler: Any
) -> str:
    name = provider_name.strip()
    if not name:
        raise ValueError(
            f"adapter bundle {bundle_name!r} declares an empty pool config handler"
        )
    if name != provider_name:
        raise ValueError(
            f"pool config handler key {provider_name!r} in bundle "
            f"{bundle_name!r} is not canonical"
        )
    handler_provider = getattr(handler, "provider", None)
    if handler_provider != name:
        raise ValueError(
            f"pool config handler {name!r} in bundle {bundle_name!r} "
            f"declares provider {handler_provider!r}"
        )
    required_hooks = (
        "validate_config",
        "validate_config_problems",
        "read_config",
        "replace_config",
        "delete_config",
    )
    missing_hooks = [
        hook for hook in required_hooks if not callable(getattr(handler, hook, None))
    ]
    if missing_hooks:
        raise ValueError(
            f"pool config handler {name!r} in bundle {bundle_name!r} "
            f"is missing callable hooks: {', '.join(missing_hooks)}"
        )
    return name


def _validate_host_requirement(
    providers: Mapping[str, FulfillmentProvider],
    host_requirement: Mapping[str, bool],
) -> None:
    """Refuse a host requirement that disagrees with the registered providers.

    The site ledger and the settlement scheduler are built before any provider
    instance exists, so they receive this requirement as data rather than
    reading it from the providers. Checking it against the providers actually
    registered here is what keeps that data from drifting: a provider absent
    from it would be treated as needing a host, and an entry for an
    unregistered provider would govern pools nothing can execute.
    """
    declared: dict[str, bool] = {}
    for name, provider in providers.items():
        try:
            declared[name] = provider_needs_host(provider)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
    missing = sorted(set(declared) - set(host_requirement))
    unregistered = sorted(set(host_requirement) - set(declared))
    disagreeing = sorted(
        name
        for name in set(declared) & set(host_requirement)
        if host_requirement[name] is not declared[name]
    )
    problems = []
    if missing:
        problems.append("omits registered provider(s) " + ", ".join(map(repr, missing)))
    if unregistered:
        problems.append("names unregistered provider(s) " + ", ".join(map(repr, unregistered)))
    if disagreeing:
        problems.append(
            "disagrees with the declaration of provider(s) "
            + ", ".join(map(repr, disagreeing))
        )
    if problems:
        raise ValueError("host requirement " + "; ".join(problems))


def compose_adapter_bundles(
    bundles: tuple[ExecutorAdapterBundle, ...] | list[ExecutorAdapterBundle],
    *,
    host_requirement: Mapping[str, bool],
    job_executors: JobExecutorTable,
    release_effects: ReleaseEffects | None = None,
) -> ComposedComputeAdapters:
    """Compose bundles and reject ambiguous registrations before startup.

    ``host_requirement`` is the per-provider host need already handed to the
    site ledger and scheduler; it must match the registered providers exactly.
    ``job_executors`` is the table the job service was built with; every
    bundle's job executors are registered into it, refusing a key registered
    twice, and it is frozen before composition returns. ``release_effects`` is
    the registry the site ledger runs when it releases capacity; every
    contributed effect is registered into it, and it is frozen with the table.
    A contributed effect with no registry to receive it is refused rather than
    dropped.
    """

    executor_owners: dict[str, str] = {}
    provider_owners: dict[str, str] = {}
    handler_owners: dict[str, str] = {}
    providers: dict[str, FulfillmentProvider] = {}
    pool_config_handlers: dict[str, Any] = {}
    inventory_views: list[tuple[str, InventoryViewProjection]] = []
    effects_contributed: list[tuple[str, ReleaseEffect]] = []
    document_owners: dict[str, str] = {}
    definition_documents: list[DefinitionDocumentContribution] = []
    task_owners: dict[str, str] = {}
    background_tasks: list[ComputeProvisioningBackgroundTask] = []

    bundle_names: set[str] = set()
    for bundle in bundles:
        bundle_name = bundle.name.strip()
        if not bundle_name:
            raise ValueError("adapter bundle name must not be empty")
        if bundle_name in bundle_names:
            raise ValueError(f"duplicate adapter bundle: {bundle_name!r}")
        bundle_names.add(bundle_name)
        _validate_provider_pairing(bundle)

        for contribution in bundle.executors:
            offering_mode = _validate_executor(bundle_name, contribution)
            previous = executor_owners.get(offering_mode)
            if previous is not None:
                raise ValueError(
                    f"duplicate offering mode {offering_mode!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            executor_owners[offering_mode] = bundle_name
            for action, executor in contribution.job_executors.items():
                try:
                    job_executors.register(offering_mode, action, executor)
                except ValueError as exc:
                    raise ValueError(f"adapter bundle {bundle_name!r}: {exc}") from exc

        for provider_name, provider in bundle.fulfillment_providers.items():
            name = provider_name.strip()
            if not name:
                raise ValueError(
                    f"adapter bundle {bundle_name!r} has an empty provider identity"
                )
            if name != provider_name:
                raise ValueError(
                    f"fulfillment provider key {provider_name!r} in bundle "
                    f"{bundle_name!r} is not canonical"
                )
            previous = provider_owners.get(name)
            if previous is not None:
                raise ValueError(
                    f"duplicate fulfillment provider {name!r} and pool config handler: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            provider_owners[name] = bundle_name
            providers[name] = provider

        for provider_name, handler in bundle.pool_config_handlers.items():
            name = _validate_pool_config_handler(
                bundle_name=bundle_name,
                provider_name=provider_name,
                handler=handler,
            )
            previous = handler_owners.get(name)
            if previous is not None:
                raise ValueError(
                    f"duplicate pool config handler {name!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            handler_owners[name] = bundle_name
            pool_config_handlers[name] = handler

        inventory_views.extend(
            (bundle_name, projection) for projection in bundle.inventory_views
        )
        effects_contributed.extend(
            (bundle_name, effect) for effect in bundle.release_effects
        )

        for document in bundle.definition_documents:
            if document.kind in SERVICE_DEFINITION_DOCUMENT_KINDS:
                raise ValueError(
                    f"adapter bundle {bundle_name!r} claims the service's own "
                    f"definition document kind {document.kind!r}"
                )
            previous = document_owners.get(document.kind)
            if previous is not None:
                raise ValueError(
                    f"duplicate definition document kind {document.kind!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            document_owners[document.kind] = bundle_name
            definition_documents.append(document)

        for task in bundle.background_tasks:
            previous = task_owners.get(task.name)
            if previous is not None:
                raise ValueError(
                    f"duplicate background task {task.name!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            task_owners[task.name] = bundle_name
            background_tasks.append(task)

    _validate_host_requirement(providers, host_requirement)
    composed_views = compose_inventory_views(inventory_views)
    if effects_contributed and release_effects is None:
        owners = sorted({owner for owner, _ in effects_contributed})
        raise ValueError(
            "release effects contributed by "
            + ", ".join(repr(owner) for owner in owners)
            + " but no registry was given to run them"
        )
    if release_effects is not None:
        for _owner, effect in effects_contributed:
            release_effects.register(effect)
        release_effects.freeze()
    job_executors.freeze()

    return ComposedComputeAdapters(
        provider_registry=ProviderRegistry(providers),
        pool_config_handlers=pool_config_handlers,
        inventory_views=composed_views,
        job_executors=job_executors,
        definition_documents=tuple(definition_documents),
        background_tasks=tuple(background_tasks),
    )
