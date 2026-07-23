from __future__ import annotations

from dataclasses import dataclass

import pytest
from compute_provisioning import CredentialEnvelope, ResultEnvelope
from market_fulfillment import (
    FulfillmentProvider,
    FulfillmentResult,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderStatus,
)

from compute_provisioning_service import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    compose_adapter_bundles,
)
from bare_metal_provisioning_adapter.bundle import (
    build_bare_metal_adapter_bundle,
)
from vm_provisioning_adapter.bundle import build_vm_adapter_bundle


@dataclass
class FakeAdapter:
    executor_kind: str

    def validate_parameters(self, action_kind, parameters):
        return dict(parameters)

    async def submit(self, envelope, validated_parameters):
        return "job-1"

    def validate_result(self, action_kind, result):
        return ResultEnvelope(
            executor_kind=self.executor_kind,
            result_kind=action_kind,
            value=dict(result),
        )

    def validate_credentials(self, action_kind, credentials):
        return [
            CredentialEnvelope(
                executor_kind=self.executor_kind,
                credential_kind="access",
                value=dict(item),
            )
            for item in credentials
        ]


class FakeReleaseExecutor:
    async def submit_release(self, reservation):
        return f"release-{reservation['capacity_reservation_id']}"


class FakeProvider(FulfillmentProvider):
    def prepare_create(self, capacity_reservation_id, fulfillment_request, resource):
        raise NotImplementedError

    async def dispatch_create(self, prepared):
        return FulfillmentResult(provider_metadata={})

    def prepare_teardown(self, capacity_reservation_id, resource, provider_metadata):
        raise NotImplementedError

    async def dispatch_teardown(self, prepared):
        return FulfillmentResult(provider_metadata={})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)


def contribution(kind: str, *actions: str) -> ExecutorAdapterContribution:
    return ExecutorAdapterContribution(
        adapter=FakeAdapter(kind),
        action_kinds=frozenset(actions),
        release_executor=FakeReleaseExecutor(),
    )


def test_vm_bundle_scopes_ansible_provider_to_compute_gpu():
    provider = FakeProvider()
    bundle = build_vm_adapter_bundle(
        compute_adapter=FakeAdapter("vm"),
        release_executor=FakeReleaseExecutor(),
        fulfillment_provider=provider,
    )

    assert bundle.fulfillment_providers == {
        ("ansible", "compute.gpu"): provider,
    }


def test_bare_metal_bundle_scopes_ansible_provider_to_bare_metal():
    provider = FakeProvider()
    bundle = build_bare_metal_adapter_bundle(
        compute_adapter=FakeAdapter("bare_metal"),
        release_executor=FakeReleaseExecutor(),
        fulfillment_provider=provider,
    )

    assert bundle.fulfillment_providers == {
        ("ansible", "bare_metal"): provider,
    }


def test_vm_and_bare_metal_ansible_routes_coexist_without_fallback():
    vm_provider = FakeProvider()
    bare_metal_provider = FakeProvider()
    composed = compose_adapter_bundles(
        [
            build_vm_adapter_bundle(
                compute_adapter=FakeAdapter("vm"),
                release_executor=FakeReleaseExecutor(),
                fulfillment_provider=vm_provider,
            ),
            build_bare_metal_adapter_bundle(
                compute_adapter=FakeAdapter("bare_metal"),
                release_executor=FakeReleaseExecutor(),
                fulfillment_provider=bare_metal_provider,
            ),
        ]
    )

    assert composed.provider_registry.require("ansible", "compute.gpu") is vm_provider
    assert composed.provider_registry.require("ansible", "bare_metal") is bare_metal_provider
    with pytest.raises(ProviderNotFoundError):
        composed.provider_registry.require("ansible", "other")


def test_composes_executor_and_provider_namespaces_independently():
    provider = FakeProvider()
    composed = compose_adapter_bundles(
        [
            ExecutorAdapterBundle(
                name="vm",
                executors=(contribution("vm", "create"),),
                fulfillment_providers={"ansible": provider},
            ),
            ExecutorAdapterBundle(
                name="bare-metal",
                executors=(contribution("bare_metal", "grant_access"),),
            ),
        ],
        default_executor_kind="vm",
    )

    assert composed.executor_registry.get("vm").executor_kind == "vm"
    assert composed.executor_registry.get("bare_metal").executor_kind == "bare_metal"
    assert composed.provider_registry.require("ansible") is provider
    with pytest.raises(ProviderNotFoundError):
        composed.provider_registry.require("vm")


def test_duplicate_executor_identifies_both_bundles():
    with pytest.raises(ValueError, match="duplicate executor kind 'vm'.*'first'.*'second'"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="first",
                    executors=(contribution("vm", "create"),),
                ),
                ExecutorAdapterBundle(
                    name="second",
                    executors=(contribution("vm", "delete"),),
                ),
            ]
        )


def test_duplicate_provider_identifies_both_bundles_independently_of_executors():
    provider = FakeProvider()
    with pytest.raises(
        ValueError,
        match="duplicate fulfillment provider 'ansible'.*'vm'.*'bare-metal'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": provider},
                ),
                ExecutorAdapterBundle(
                    name="bare-metal",
                    executors=(contribution("bare_metal", "grant_access"),),
                    fulfillment_providers={"ansible": provider},
                ),
            ]
        )


def test_same_provider_name_may_be_scoped_to_different_resource_kinds():
    vm_provider = FakeProvider()
    bare_metal_provider = FakeProvider()
    composed = compose_adapter_bundles(
        [
            ExecutorAdapterBundle(
                name="vm",
                executors=(contribution("vm", "create"),),
                fulfillment_providers={
                    ("ansible", "compute.gpu"): vm_provider,
                },
            ),
            ExecutorAdapterBundle(
                name="bare-metal",
                executors=(contribution("bare_metal", "grant_access"),),
                fulfillment_providers={
                    ("ansible", "bare_metal"): bare_metal_provider,
                },
            ),
        ]
    )

    assert composed.provider_registry.require("ansible", "compute.gpu") is vm_provider
    assert composed.provider_registry.require("ansible", "bare_metal") is bare_metal_provider


def test_duplicate_scoped_provider_identifies_both_bundles():
    provider = FakeProvider()
    with pytest.raises(
        ValueError,
        match="duplicate fulfillment provider .*ansible.*compute.gpu.*'first'.*'second'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="first",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={("ansible", "compute.gpu"): provider},
                ),
                ExecutorAdapterBundle(
                    name="second",
                    executors=(contribution("bare_metal", "grant_access"),),
                    fulfillment_providers={("ansible", "compute.gpu"): provider},
                ),
            ]
        )


@pytest.mark.parametrize("key", [("", "compute.gpu"), ("ansible", "")])
def test_empty_scoped_provider_identity_is_rejected(key):
    with pytest.raises(ValueError, match="empty provider or resource-kind identity"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="invalid",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={key: FakeProvider()},
                )
            ]
        )


def test_incomplete_executor_contribution_is_rejected_before_startup():
    with pytest.raises(ValueError, match="declares no action kinds"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm"),),
                )
            ]
        )


def test_duplicate_readiness_check_is_rejected():
    with pytest.raises(ValueError, match="duplicate readiness check 'controller'"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    readiness_checks={"controller": lambda: True},
                ),
                ExecutorAdapterBundle(
                    name="bare-metal",
                    executors=(contribution("bare_metal", "grant_access"),),
                    readiness_checks={"controller": lambda: True},
                ),
            ]
        )
