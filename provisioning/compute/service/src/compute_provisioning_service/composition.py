"""Domain adapter contributions and startup-time composition validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from compute_provisioning import ExecutorAdapter, ExecutorAdapterRegistry
from compute_provisioning.app import ComputeProvisioningRouterMount
from compute_provisioning.release import ExecutorReleaseDispatcher, ExecutorReleasePort
from market_fulfillment import FulfillmentProvider, ProviderRegistry


@dataclass(frozen=True)
class ExecutorAdapterContribution:
    """One domain's executor adapter plus its declared lifecycle hooks."""

    adapter: ExecutorAdapter
    action_kinds: frozenset[str]
    release_executor: ExecutorReleasePort


@dataclass(frozen=True)
class ExecutorAdapterBundle:
    """Everything one compute domain contributes to service composition."""

    name: str
    executors: tuple[ExecutorAdapterContribution, ...]
    fulfillment_providers: Mapping[str, FulfillmentProvider] = field(default_factory=dict)
    pool_config_handlers: Mapping[str, Any] = field(default_factory=dict)
    router_mounts: tuple[ComputeProvisioningRouterMount, ...] = ()
    readiness_checks: Mapping[str, Callable[[], Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposedComputeAdapters:
    executor_registry: ExecutorAdapterRegistry
    release_dispatcher: ExecutorReleaseDispatcher
    provider_registry: ProviderRegistry
    pool_config_handlers: Mapping[str, Any]
    router_mounts: tuple[ComputeProvisioningRouterMount, ...]
    readiness_checks: Mapping[str, Callable[[], Any]]


def _validate_executor(bundle_name: str, contribution: ExecutorAdapterContribution) -> str:
    adapter = contribution.adapter
    executor_kind = str(getattr(adapter, "executor_kind", "") or "").strip()
    if not executor_kind:
        raise ValueError(f"adapter bundle {bundle_name!r} has an executor without executor_kind")
    if not contribution.action_kinds:
        raise ValueError(
            f"adapter bundle {bundle_name!r} executor {executor_kind!r} declares no action kinds"
        )
    for hook in (
        "validate_parameters",
        "submit",
        "validate_result",
        "validate_credentials",
    ):
        if not callable(getattr(adapter, hook, None)):
            raise ValueError(
                f"adapter bundle {bundle_name!r} executor {executor_kind!r} "
                f"is missing required hook {hook!r}"
            )
    if not callable(getattr(contribution.release_executor, "submit_release", None)):
        raise ValueError(
            f"adapter bundle {bundle_name!r} executor {executor_kind!r} "
            "is missing required release hook 'submit_release'"
        )
    return executor_kind


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


def compose_adapter_bundles(
    bundles: tuple[ExecutorAdapterBundle, ...] | list[ExecutorAdapterBundle],
) -> ComposedComputeAdapters:
    """Compose bundles and reject ambiguous registrations before startup."""

    executor_owners: dict[str, str] = {}
    action_owners: dict[tuple[str, str], str] = {}
    provider_owners: dict[str, str] = {}
    handler_owners: dict[str, str] = {}
    readiness_owners: dict[str, str] = {}
    adapters: list[ExecutorAdapter] = []
    release_executors: dict[str, ExecutorReleasePort] = {}
    providers: dict[str, FulfillmentProvider] = {}
    pool_config_handlers: dict[str, Any] = {}
    routers: list[ComputeProvisioningRouterMount] = []
    readiness_checks: dict[str, Callable[[], Any]] = {}

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
            executor_kind = _validate_executor(bundle_name, contribution)
            previous = executor_owners.get(executor_kind)
            if previous is not None:
                raise ValueError(
                    f"duplicate executor kind {executor_kind!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            executor_owners[executor_kind] = bundle_name
            for action_kind in contribution.action_kinds:
                key = (executor_kind, action_kind)
                previous = action_owners.get(key)
                if previous is not None:
                    raise ValueError(
                        f"duplicate executor/action {executor_kind!r}/{action_kind!r}: "
                        f"bundles {previous!r} and {bundle_name!r}"
                    )
                action_owners[key] = bundle_name
            adapters.append(contribution.adapter)
            release_executors[executor_kind] = contribution.release_executor

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

        for check_name, check in bundle.readiness_checks.items():
            if not callable(check):
                raise ValueError(
                    f"adapter bundle {bundle_name!r} readiness check {check_name!r} "
                    "is not callable"
                )
            previous = readiness_owners.get(check_name)
            if previous is not None:
                raise ValueError(
                    f"duplicate readiness check {check_name!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            readiness_owners[check_name] = bundle_name
            readiness_checks[check_name] = check

        routers.extend(bundle.router_mounts)

    return ComposedComputeAdapters(
        executor_registry=ExecutorAdapterRegistry(adapters),
        release_dispatcher=ExecutorReleaseDispatcher(release_executors),
        provider_registry=ProviderRegistry(providers),
        pool_config_handlers=pool_config_handlers,
        router_mounts=tuple(routers),
        readiness_checks=readiness_checks,
    )
