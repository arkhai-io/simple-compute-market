from __future__ import annotations

import pytest


def _config(**overrides):
    from market.canary import CanaryConfig

    values = {
        "registry_url": "http://100.64.0.10:8080",
        "provisioning_url": "http://100.64.0.11:8081",
        "seller_agent_url": "http://100.64.0.50:8001",
        "buyer_agent_url": "http://100.64.0.51:8000",
        "seller_agent_id": "eip155:84532:0x1111111111111111111111111111111111111111:101",
        "buyer_agent_id": "eip155:84532:0x1111111111111111111111111111111111111111:202",
        "seller_private_key": "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "buyer_private_key": "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "ssh_private_key_path": None,
        "gpu_model": "RTX 5090",
        "region": "Nevada, US",
        "token_symbol": "USDC",
        "token_amount": 2.5,
        "quantity": 2,
        "sla": 95.0,
        "duration_hours": 1,
        "timeout": 600,
        "poll_interval": 5,
    }
    values.update(overrides)
    return CanaryConfig(**values)


def test_identity_preflight_validator_rejects_reused_actor_identity() -> None:
    from market.canary import IdentityPreflightValidator

    config = _config(
        buyer_agent_id="eip155:84532:0x1111111111111111111111111111111111111111:101",
        buyer_private_key="0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        buyer_agent_url="http://100.64.0.50:8001",
    )

    with pytest.raises(SystemExit, match="buyer and seller actors must use distinct identities"):
        IdentityPreflightValidator(config).validate()


def test_canary_coordinator_runs_expected_actor_sequence() -> None:
    from market.canary import CanaryCoordinator

    events: list[object] = []

    class FakeValidator:
        def validate(self) -> None:
            events.append("validate")

    class FakeNetworkProbe:
        def verify(self) -> None:
            events.append("network")

    class FakeSeller:
        def capture_baseline_order_ids(self) -> set[str]:
            events.append("seller:baseline")
            return {"seller-old"}

        def create_canary_order(self) -> str:
            events.append("seller:create")
            return "seller-order"

    class FakeBuyer:
        def capture_baseline_order_ids(self) -> set[str]:
            events.append("buyer:baseline")
            return {"buyer-old"}

        def create_canary_order(self) -> str:
            events.append("buyer:create")
            return "buyer-order"

    class FakeProvisioningProbe:
        def capture_baseline_job_ids(self) -> set[str]:
            events.append("provisioning:baseline")
            return {"job-old"}

        def await_succeeded_job(self, *, baseline_job_ids: set[str]) -> dict:
            events.append(("provisioning:job", baseline_job_ids))
            return {"job_id": "job-1", "status": "succeeded"}

        def fetch_credentials(self, *, job_id: str) -> list[dict]:
            events.append(("provisioning:credentials", job_id))
            return [{"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}]

        def verify_access(self, credentials: list[dict]) -> None:
            events.append(("provisioning:access", credentials))

    class FakeRegistryProbe:
        def await_orders_closed(self, *, order_ids: list[str]) -> dict[str, dict]:
            events.append(("registry:closed", order_ids))
            return {
                "seller-order": {"status": "closed"},
                "buyer-order": {"status": "closed"},
            }

    coordinator = CanaryCoordinator(
        validator=FakeValidator(),
        network_probe=FakeNetworkProbe(),
        seller=FakeSeller(),
        buyer=FakeBuyer(),
        provisioning_probe=FakeProvisioningProbe(),
        registry_probe=FakeRegistryProbe(),
    )

    result = coordinator.run()

    assert result == {
        "job": {"job_id": "job-1", "status": "succeeded"},
        "orders": {
            "seller-order": {"status": "closed"},
            "buyer-order": {"status": "closed"},
        },
    }
    assert events == [
        "validate",
        "network",
        "seller:baseline",
        "buyer:baseline",
        "provisioning:baseline",
        "seller:create",
        "buyer:create",
        ("provisioning:job", {"job-old"}),
        ("provisioning:credentials", "job-1"),
        ("provisioning:access", [{"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}]),
        ("registry:closed", ["seller-order", "buyer-order"]),
    ]


def test_canary_coordinator_requires_tenant_credentials() -> None:
    from market.canary import CanaryCoordinator

    class FakeValidator:
        def validate(self) -> None:
            return None

    class FakeNetworkProbe:
        def verify(self) -> None:
            return None

    class FakeActor:
        def capture_baseline_order_ids(self) -> set[str]:
            return set()

        def create_canary_order(self) -> str:
            return "order-id"

    class FakeProvisioningProbe:
        def capture_baseline_job_ids(self) -> set[str]:
            return set()

        def await_succeeded_job(self, *, baseline_job_ids: set[str]) -> dict:
            return {"job_id": "job-1", "status": "succeeded"}

        def fetch_credentials(self, *, job_id: str) -> list[dict]:
            return [{"role": "operator"}]

        def verify_access(self, credentials: list[dict]) -> None:
            raise AssertionError("verify_access should not be called without tenant credentials")

    class FakeRegistryProbe:
        def await_orders_closed(self, *, order_ids: list[str]) -> dict[str, dict]:
            return {}

    coordinator = CanaryCoordinator(
        validator=FakeValidator(),
        network_probe=FakeNetworkProbe(),
        seller=FakeActor(),
        buyer=FakeActor(),
        provisioning_probe=FakeProvisioningProbe(),
        registry_probe=FakeRegistryProbe(),
    )

    with pytest.raises(SystemExit, match="No tenant credentials returned for buyer agent"):
        coordinator.run()
