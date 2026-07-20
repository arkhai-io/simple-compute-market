"""Domain adapter contributions and startup-time composition validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from compute_provisioning import ExecutorAdapter, ExecutorAdapterRegistry
from compute_provisioning.app import ComputeProvisioningRouterMount
from compute_provisioning.release import ExecutorReleaseDispatcher, ExecutorReleasePort
from market_resource_pools import FulfillmentProvider, ProviderRegistry


@dataclass(frozen=True)
class ExecutorAdapterContribution:
    """One domain's executor adapter plus its declared lifecycle hooks."""

    adapter: ExecutorAdapter
    action_kinds: frozenset[str]
    release_executor: ExecutorReleasePort


@dataclass(frozen=True)
class ExecutorAdapterBundle:
    """Everything one compute domain contributes to service composition.

    Provider identities intentionally live beside, rather than inside, executor
    contributions: a provider is an infrastructure mechanism and never selects
    or claims an executor kind.
    """

    name: str
    executors: tuple[ExecutorAdapterContribution, ...]
    fulfillment_providers: Mapping[str, FulfillmentProvider] = field(default_factory=dict)
    router_mounts: tuple[ComputeProvisioningRouterMount, ...] = ()
    readiness_checks: Mapping[str, Callable[[], Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposedComputeAdapters:
    executor_registry: ExecutorAdapterRegistry
    release_dispatcher: ExecutorReleaseDispatcher
    provider_registry: ProviderRegistry
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


def compose_adapter_bundles(
    bundles: tuple[ExecutorAdapterBundle, ...] | list[ExecutorAdapterBundle],
    *,
    default_executor_kind: str | None = None,
) -> ComposedComputeAdapters:
    """Compose bundles and reject ambiguous registrations before startup."""

    executor_owners: dict[str, str] = {}
    action_owners: dict[tuple[str, str], str] = {}
    provider_owners: dict[str, str] = {}
    readiness_owners: dict[str, str] = {}
    adapters: list[ExecutorAdapter] = []
    release_executors: dict[str, ExecutorReleasePort] = {}
    providers: dict[str, FulfillmentProvider] = {}
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
            provider_name = provider_name.strip()
            if not provider_name:
                raise ValueError(f"adapter bundle {bundle_name!r} has an empty provider identity")
            previous = provider_owners.get(provider_name)
            if previous is not None:
                raise ValueError(
                    f"duplicate fulfillment provider {provider_name!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            provider_owners[provider_name] = bundle_name
            providers[provider_name] = provider

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
        release_dispatcher=ExecutorReleaseDispatcher(
            release_executors,
            default_executor_kind=default_executor_kind,
        ),
        provider_registry=ProviderRegistry(providers),
        router_mounts=tuple(routers),
        readiness_checks=readiness_checks,
    )
