from __future__ import annotations

from dataclasses import dataclass

import pytest
from compute_provisioning import CredentialEnvelope, ResultEnvelope
from market_fulfillment import (
    FulfillmentProvider,
    FulfillmentResult,
    VersionedEnvelope,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderStatus,
)

from compute_provisioning_service import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    compose_adapter_bundles,
)


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
    def prepare_create(self, *, capacity_reservation_id, request, resource, pool_config):
        return VersionedEnvelope(kind="fake.create", schema_version=1, payload={})

    async def dispatch_create(self, prepared):
        return FulfillmentResult(provider_metadata={})

    def prepare_teardown(self, settlement_result, pool_config):
        return VersionedEnvelope(kind="fake.teardown", schema_version=1, payload={})

    async def dispatch_teardown(self, prepared):
        return FulfillmentResult(provider_metadata={})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)

    def resolve_provisioned_resources(self, provider_metadata):
        return ()

    async def fetch_credentials(self, provider_metadata, provisioned_resources):
        return VersionedEnvelope(kind="vm.fulfillment.result.v1", schema_version=1, payload={"credentials": []})


class FakePoolConfigHandler:
    def __init__(self, provider: str) -> None:
        self.provider = provider

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, unit_of_work, pool_id):
        return {}

    def replace_config(self, unit_of_work, pool_id, config):
        return None

    def delete_config(self, unit_of_work, pool_id):
        return None


def contribution(kind: str, *actions: str) -> ExecutorAdapterContribution:
    return ExecutorAdapterContribution(
        adapter=FakeAdapter(kind),
        action_kinds=frozenset(actions),
        release_executor=FakeReleaseExecutor(),
    )


def test_composes_executor_and_provider_namespaces_independently():
    provider = FakeProvider()
    handler = FakePoolConfigHandler("ansible")
    composed = compose_adapter_bundles([
        ExecutorAdapterBundle(
            name="vm",
            executors=(contribution("vm", "create"),),
            fulfillment_providers={"ansible": provider},
            pool_config_handlers={"ansible": handler},
        ),
        ExecutorAdapterBundle(
            name="bare-metal",
            executors=(contribution("bare_metal", "grant_access"),),
        ),
    ])

    assert composed.executor_registry.get("vm").executor_kind == "vm"
    assert composed.executor_registry.get("bare_metal").executor_kind == "bare_metal"
    assert composed.provider_registry.require("ansible") is provider
    assert composed.pool_config_handlers["ansible"] is handler
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
    handler = FakePoolConfigHandler("ansible")
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
                    pool_config_handlers={"ansible": handler},
                ),
                ExecutorAdapterBundle(
                    name="bare-metal",
                    executors=(contribution("bare_metal", "grant_access"),),
                    fulfillment_providers={"ansible": provider},
                    pool_config_handlers={"ansible": handler},
                ),
            ]
        )


def test_provider_without_pool_config_handler_is_rejected_before_startup():
    with pytest.raises(
        ValueError,
        match="missing pool config handler.*'ansible'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": FakeProvider()},
                )
            ]
        )


def test_handler_identity_must_match_provider_identity():
    with pytest.raises(
        ValueError,
        match="declares provider 'other'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": FakeProvider()},
                    pool_config_handlers={
                        "ansible": FakePoolConfigHandler("other"),
                    },
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
