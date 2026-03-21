from __future__ import annotations

import pytest


def _config(**overrides):
    from market.canary import CanaryConfig

    values = {
        "registry_url": "http://100.64.0.10:8080",
        "provisioning_url": "http://100.64.0.11:8081",
        "seller_agent_url": "http://100.64.0.50:8001",
        "buyer_agent_url": "http://100.64.0.51:8000",
        "frp_dashboard_url": None,
        "frp_dashboard_password": None,
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
        "match_salt": 0,
        "chain_rpc_url": None,
        "chain_name": "base_sepolia",
        "vm_hosts": (),
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
    seller_cleanup_calls = 0
    buyer_cleanup_calls = 0

    class FakeValidator:
        def validate(self) -> None:
            events.append("validate")

    class FakeNetworkProbe:
        def verify(self) -> None:
            events.append("network")

    class FakeChainProbe:
        def verify(self) -> None:
            events.append("chain")

    class FakeSeller:
        def cleanup_open_orders(self) -> list[str]:
            nonlocal seller_cleanup_calls
            seller_cleanup_calls += 1
            events.append(f"seller:cleanup:{seller_cleanup_calls}")
            if seller_cleanup_calls == 1:
                return ["seller-stale"]
            return ["seller-order"]

        def capture_baseline_order_ids(self) -> set[str]:
            events.append("seller:baseline")
            return {"seller-old"}

        def create_canary_order(self) -> str:
            events.append("seller:create")
            return "seller-order"

    class FakeBuyer:
        def cleanup_open_orders(self) -> list[str]:
            nonlocal buyer_cleanup_calls
            buyer_cleanup_calls += 1
            events.append(f"buyer:cleanup:{buyer_cleanup_calls}")
            if buyer_cleanup_calls == 1:
                return ["buyer-stale"]
            return ["buyer-order"]

        def capture_baseline_order_ids(self) -> set[str]:
            events.append("buyer:baseline")
            return {"buyer-old"}

        def create_canary_order(self) -> str:
            events.append("buyer:create")
            return "buyer-order"

    class FakeProvisioningProbe:
        def verify_vm_hosts(self) -> None:
            events.append("provisioning:preflight")

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
        chain_probe=FakeChainProbe(),
        seller=FakeSeller(),
        buyer=FakeBuyer(),
        provisioning_probe=FakeProvisioningProbe(),
        registry_probe=FakeRegistryProbe(),
    )

    result = coordinator.run()

    assert result == {
        "status": "succeeded",
        "seller_order_id": "seller-order",
        "buyer_order_id": "buyer-order",
        "provisioning_job_id": "job-1",
        "vm_host": None,
        "vm_target": None,
        "cleanup": {
            "preexisting_closed_order_ids": {
                "seller": ["seller-stale"],
                "buyer": ["buyer-stale"],
            },
            "post_provisioning_closed_order_ids": {
                "seller": ["seller-order"],
                "buyer": ["buyer-order"],
            },
            "final_order_ids": ["seller-order", "buyer-order"],
        },
        "job": {"job_id": "job-1", "status": "succeeded"},
        "orders": {
            "seller-order": {"status": "closed"},
            "buyer-order": {"status": "closed"},
        },
    }
    assert events == [
        "validate",
        "network",
        "chain",
        "seller:cleanup:1",
        "buyer:cleanup:1",
        "seller:baseline",
        "buyer:baseline",
        "provisioning:preflight",
        "provisioning:baseline",
        "seller:create",
        "buyer:create",
        ("provisioning:job", {"job-old"}),
        ("provisioning:credentials", "job-1"),
        ("provisioning:access", [{"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}]),
        "seller:cleanup:2",
        "buyer:cleanup:2",
        ("registry:closed", ["seller-order", "buyer-order"]),
    ]


def test_registry_probe_closes_signed_active_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    from market.canary import CanaryConfig, CanaryGateway, RegistryProbe

    closed: list[tuple[str, str, str]] = []

    class FakeGateway(CanaryGateway):
        def fetch_agent_orders(self, registry_url: str, agent_id: str) -> list[dict]:
            return [
                {"order_id": "open-1", "status": "open"},
                {"order_id": "accepted-1", "status": "accepted"},
                {"order_id": "closing-1", "status": "closing"},
                {"order_id": "closed-1", "status": "closed"},
                {"order_id": "open-2", "status": "open"},
            ]

        def update_order_status(
            self,
            *,
            registry_url: str,
            order_id: str,
            status: str,
            signer_agent_id: str,
            private_key: str,
        ) -> dict:
            closed.append((order_id, status, signer_agent_id))
            return {"order_id": order_id, "status": status}

    config = _config()
    probe = RegistryProbe(config, FakeGateway())

    result = probe.close_active_orders(
        agent_id=config.seller_agent_id,
        private_key=config.seller_private_key,
    )

    assert result == ["open-1", "accepted-1", "closing-1", "open-2"]
    assert closed == [
        ("open-1", "closed", config.seller_agent_id),
        ("accepted-1", "closed", config.seller_agent_id),
        ("closing-1", "closed", config.seller_agent_id),
        ("open-2", "closed", config.seller_agent_id),
    ]


def test_canary_coordinator_requires_tenant_credentials() -> None:
    from market.canary import CanaryCoordinator

    class FakeValidator:
        def validate(self) -> None:
            return None

    class FakeNetworkProbe:
        def verify(self) -> None:
            return None

    class FakeChainProbe:
        def verify(self) -> None:
            return None

    class FakeActor:
        def cleanup_open_orders(self) -> list[str]:
            return []

        def capture_baseline_order_ids(self) -> set[str]:
            return set()

        def create_canary_order(self) -> str:
            return "order-id"

    class FakeProvisioningProbe:
        def verify_vm_hosts(self) -> None:
            return None

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
        chain_probe=FakeChainProbe(),
        seller=FakeActor(),
        buyer=FakeActor(),
        provisioning_probe=FakeProvisioningProbe(),
        registry_probe=FakeRegistryProbe(),
    )

    with pytest.raises(SystemExit, match="No tenant credentials returned for buyer agent"):
        coordinator.run()


def test_wait_for_new_succeeded_job_fails_fast_on_new_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from market import canary

    monkeypatch.setattr(
        canary,
        "_list_jobs",
        lambda provisioning_url, agent_id: [
            {
                "job_id": "job-failed",
                "status": "failed",
                "params": {"vm_action": "create"},
                "error": "Job failed (max retries exceeded): Playbook failed",
            }
        ],
    )
    times = iter([0.0, 0.0])
    monkeypatch.setattr(canary.time, "time", lambda: next(times))

    with pytest.raises(
        SystemExit,
        match=r"Provisioning job job-failed failed: Job failed \(max retries exceeded\): Playbook failed",
    ):
        canary._wait_for_new_succeeded_job(
            provisioning_url="http://100.64.0.11:8081",
            seller_agent_id="seller-agent",
            baseline_job_ids=set(),
            timeout=60,
            poll_interval=1,
        )


def test_provisioning_probe_rejects_host_without_gpu_capacity() -> None:
    from market.canary import CanaryGateway, ProvisioningProbe

    class FakeGateway(CanaryGateway):
        def __init__(self) -> None:
            self.created: list[dict] = []

        def list_jobs(self, provisioning_url: str, agent_id: str) -> list[dict]:
            return [
                {
                    "job_id": "check-job-1",
                    "status": "succeeded",
                    "params": {"vm_action": "check", "vm_host": "ww1"},
                    "result": {
                        "summary": {
                            "available": {"gpus": 0},
                            "allocated": {"gpus": 0},
                            "total": {"gpus": 0},
                        }
                    },
                }
            ]

        def submit_job(
            self,
            *,
            provisioning_url: str,
            agent_id: str,
            payload: dict,
        ) -> dict:
            self.created.append(
                {
                    "provisioning_url": provisioning_url,
                    "agent_id": agent_id,
                    "payload": payload,
                }
            )
            return {"job_id": "check-job-1", "status": "queued"}

        def wait_for_new_succeeded_job(
            self,
            *,
            provisioning_url: str,
            seller_agent_id: str,
            baseline_job_ids: set[str],
            timeout: int,
            poll_interval: int,
            expected_vm_action: str = "create",
        ) -> dict:
            assert expected_vm_action == "check"
            assert provisioning_url == config.provisioning_url
            assert seller_agent_id == config.seller_agent_id
            assert baseline_job_ids == {"check-job-1"}
            return self.list_jobs(provisioning_url, seller_agent_id)[0]

    config = _config(vm_hosts=("ww1",))
    gateway = FakeGateway()
    probe = ProvisioningProbe(config, gateway)

    with pytest.raises(SystemExit, match="ww1 does not report enough total GPUs"):
        probe.verify_vm_hosts()

    assert gateway.created == [
        {
            "provisioning_url": config.provisioning_url,
            "agent_id": config.seller_agent_id,
            "payload": {"vm_host": "ww1", "vm_action": "check"},
        }
    ]


def test_provisioning_probe_accepts_ansible_result_capacity_shape() -> None:
    from market.canary import CanaryGateway, ProvisioningProbe

    class FakeGateway(CanaryGateway):
        def list_jobs(self, provisioning_url: str, agent_id: str) -> list[dict]:
            return [{"job_id": "check-job-1"}]

        def submit_job(
            self,
            *,
            provisioning_url: str,
            agent_id: str,
            payload: dict,
        ) -> dict:
            return {"job_id": "check-job-2", "status": "queued"}

        def wait_for_new_succeeded_job(
            self,
            *,
            provisioning_url: str,
            seller_agent_id: str,
            baseline_job_ids: set[str],
            timeout: int,
            poll_interval: int,
            expected_vm_action: str = "create",
        ) -> dict:
            assert expected_vm_action == "check"
            return {
                "job_id": "check-job-2",
                "status": "succeeded",
                "result": {
                    "ansible_result": {
                        "host": "btc1",
                        "total": {"gpus": 8},
                        "available": {"gpus": 8},
                        "allocated": {"gpus": 0},
                    }
                },
            }

    probe = ProvisioningProbe(_config(vm_hosts=("btc1",)), FakeGateway())

    probe.verify_vm_hosts()


def test_provisioning_probe_verifies_ssh_with_configured_retry_budget() -> None:
    from market.canary import CanaryGateway, ProvisioningProbe

    observed: list[dict] = []

    class FakeGateway(CanaryGateway):
        def verify_ssh(
            self,
            credentials: list[dict],
            ssh_private_key_path: str | None,
            *,
            ready_timeout: int,
            retry_interval: int,
        ) -> None:
            observed.append(
                {
                    "credentials": credentials,
                    "ssh_private_key_path": ssh_private_key_path,
                    "ready_timeout": ready_timeout,
                    "retry_interval": retry_interval,
                }
            )

    config = _config(
        ssh_private_key_path="/tmp/canary-id_ed25519",
        timeout=900,
        poll_interval=9,
    )

    ProvisioningProbe(config, FakeGateway()).verify_access(
        [{"role": "tenant", "ssh_commands": {"external": "ssh tenant@example"}}]
    )

    assert observed == [
        {
            "credentials": [{"role": "tenant", "ssh_commands": {"external": "ssh tenant@example"}}],
            "ssh_private_key_path": "/tmp/canary-id_ed25519",
            "ready_timeout": 900,
            "retry_interval": 9,
        }
    ]


def test_chain_probe_wraps_missing_buyer_weth_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from market.canary import ChainProbe

    wrapped: list[tuple[str, str, int]] = []

    monkeypatch.setattr("market.canary._erc20_balance_of", lambda rpc_url, token_address, owner: 0)
    monkeypatch.setattr("market.canary._native_balance_of", lambda rpc_url, owner: 500_000_000_000_000)
    monkeypatch.setattr("market.canary._gas_price", lambda rpc_url: 1)
    monkeypatch.setattr(
        "market.canary._wrap_native_to_wrapped_token",
        lambda rpc_url, private_key, token_address, amount_wei: wrapped.append(
            (rpc_url, token_address, amount_wei)
        ),
    )

    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        match_salt=42,
        chain_rpc_url="https://rpc.example.invalid",
    )

    ChainProbe(config).verify()

    assert wrapped == [
        (
            "https://rpc.example.invalid",
            "0x4200000000000000000000000000000000000006",
            100420000000000,
        )
    ]


def test_wrap_gas_buffer_tracks_chain_gas_price() -> None:
    from market.canary import _wrap_gas_buffer_wei

    assert _wrap_gas_buffer_wei(gas_price=1) == 1_000_000_000_000
    assert _wrap_gas_buffer_wei(gas_price=6_000_000) == 1_440_000_000_000


def test_escrow_gas_buffer_tracks_chain_gas_price() -> None:
    from market.canary import _escrow_gas_buffer_wei

    assert _escrow_gas_buffer_wei(gas_price=1) == 1_000_000_000_000
    assert _escrow_gas_buffer_wei(gas_price=6_000_000) >= 7_754_945_000_000


def test_chain_probe_funds_buyer_native_balance_before_wrapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from market.canary import ChainProbe

    funded: list[tuple[str, str, int]] = []
    wrapped: list[tuple[str, str, int]] = []
    native_balances = iter(
        [
            50_000_000_000_000,
            500_000_000_000_000,
            200_000_000_000_001,
        ]
    )

    monkeypatch.setattr("market.canary._erc20_balance_of", lambda rpc_url, token_address, owner: 0)
    monkeypatch.setattr("market.canary._native_balance_of", lambda rpc_url, owner: next(native_balances))
    monkeypatch.setattr("market.canary._gas_price", lambda rpc_url: 1)
    monkeypatch.setattr(
        "market.canary._transfer_native_token",
        lambda rpc_url, private_key, recipient_address, amount_wei: funded.append(
            (rpc_url, recipient_address, amount_wei)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "market.canary._wrap_native_to_wrapped_token",
        lambda rpc_url, private_key, token_address, amount_wei: wrapped.append(
            (rpc_url, token_address, amount_wei)
        ),
    )

    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        chain_rpc_url="https://rpc.example.invalid",
    )

    ChainProbe(config).verify()

    assert len(funded) == 1
    assert funded[0][0] == "https://rpc.example.invalid"
    assert funded[0][2] == 52_000_000_000_000
    assert wrapped == [
        (
            "https://rpc.example.invalid",
            "0x4200000000000000000000000000000000000006",
            100000000000000,
        )
    ]


def test_chain_probe_can_top_up_buyer_with_modest_seller_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account
    from market.canary import ChainProbe

    funded: list[int] = []
    wrapped: list[int] = []
    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        chain_rpc_url="https://rpc.example.invalid",
    )
    seller = Account.from_key(config.seller_private_key).address
    buyer = Account.from_key(config.buyer_private_key).address

    def fake_native_balance(rpc_url: str, owner: str) -> int:
        if owner == buyer:
            return 95_440_413_999_548
        if owner == seller:
            return 79_354_245_809_042
        raise AssertionError(f"unexpected owner: {owner}")

    monkeypatch.setattr("market.canary._erc20_balance_of", lambda rpc_url, token_address, owner: 0)
    monkeypatch.setattr("market.canary._native_balance_of", fake_native_balance)
    monkeypatch.setattr("market.canary._gas_price", lambda rpc_url: 6_000_000)
    monkeypatch.setattr(
        "market.canary._transfer_native_token",
        lambda rpc_url, private_key, recipient_address, amount_wei: funded.append(amount_wei),
        raising=False,
    )
    monkeypatch.setattr(
        "market.canary._wait_for_native_balance",
        lambda rpc_url, owner_address, minimum_wei, **kwargs: minimum_wei,
    )
    monkeypatch.setattr(
        "market.canary._wrap_native_to_wrapped_token",
        lambda rpc_url, private_key, token_address, amount_wei: wrapped.append(amount_wei),
    )

    ChainProbe(config).verify()

    assert funded == [14_399_586_000_452]
    assert wrapped == [100_000_000_000_000]


def test_chain_probe_waits_for_buyer_native_balance_after_top_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from market.canary import ChainProbe

    native_calls = {"count": 0}

    def fake_native_balance(rpc_url: str, owner: str) -> int:
        native_calls["count"] += 1
        if native_calls["count"] == 1:
            return 50_000_000_000_000
        if native_calls["count"] == 2:
            return 500_000_000_000_000
        if native_calls["count"] == 3:
            return 50_000_000_000_000
        return 200_000_000_000_001

    monkeypatch.setattr("market.canary._erc20_balance_of", lambda rpc_url, token_address, owner: 0)
    monkeypatch.setattr("market.canary._native_balance_of", fake_native_balance)
    monkeypatch.setattr("market.canary._gas_price", lambda rpc_url: 1)
    monkeypatch.setattr(
        "market.canary._transfer_native_token",
        lambda rpc_url, private_key, recipient_address, amount_wei: None,
        raising=False,
    )

    def fake_wrap(rpc_url: str, private_key: str, token_address: str, amount_wei: int) -> None:
        assert native_calls["count"] >= 4

    monkeypatch.setattr("market.canary._wrap_native_to_wrapped_token", fake_wrap)

    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        chain_rpc_url="https://rpc.example.invalid",
    )

    ChainProbe(config).verify()


def test_chain_probe_funds_buyer_native_balance_even_when_weth_is_already_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account
    from market.canary import ChainProbe

    funded: list[int] = []
    wrapped: list[int] = []
    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        chain_rpc_url="https://rpc.example.invalid",
    )
    buyer = Account.from_key(config.buyer_private_key).address

    def fake_native_balance(rpc_url: str, owner: str) -> int:
        if owner == buyer:
            return 250_000_000_000
        return 10_000_000_000_000_000

    monkeypatch.setattr(
        "market.canary._erc20_balance_of",
        lambda rpc_url, token_address, owner: 100_000_000_000_000,
    )
    monkeypatch.setattr("market.canary._native_balance_of", fake_native_balance)
    monkeypatch.setattr("market.canary._gas_price", lambda rpc_url: 6_000_000)
    monkeypatch.setattr(
        "market.canary._transfer_native_token",
        lambda rpc_url, private_key, recipient_address, amount_wei: funded.append(amount_wei),
        raising=False,
    )
    monkeypatch.setattr(
        "market.canary._wait_for_native_balance",
        lambda rpc_url, owner_address, minimum_wei, **kwargs: minimum_wei,
    )
    monkeypatch.setattr(
        "market.canary._wrap_native_to_wrapped_token",
        lambda rpc_url, private_key, token_address, amount_wei: wrapped.append(amount_wei),
    )

    ChainProbe(config).verify()

    assert funded == [8_150_000_000_000]
    assert wrapped == []


def test_chain_probe_rejects_weth_canary_without_rpc_url() -> None:
    from market.canary import ChainProbe

    config = _config(
        token_symbol="WETH",
        token_amount=0.0001,
        match_salt=42,
        chain_rpc_url=None,
    )

    with pytest.raises(SystemExit, match="chain-rpc-url"):
        ChainProbe(config).verify()


def test_network_probe_rejects_missing_matching_seller_inventory() -> None:
    from market.canary import CanaryGateway, NetworkProbe

    class FakeGateway(CanaryGateway):
        def check_health(self, label: str, url: str) -> dict:
            return {"ok": True}

        def fetch_agent_card(self, agent_url: str) -> dict:
            return {"name": "agent"}

        def fetch_registration_document(self, agent_url: str) -> dict:
            agent_id = 101 if "50" in agent_url else 202
            return {
                "registrations": [
                    {
                        "agentId": agent_id,
                        "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                    }
                ]
            }

        def fetch_resource_portfolio(self, agent_url: str) -> dict:
            return {
                "resources": [
                    {
                        "resource_id": "compute-h100-east-001",
                        "resource_type": "compute.gpu",
                        "gpu_model": "H100",
                        "quantity": 1,
                        "sla": 90.0,
                        "region": "Virginia, US",
                    }
                ]
            }

    config = _config(gpu_model="H200", quantity=1, region="California, US")

    with pytest.raises(SystemExit, match="seller has no available compute resource matching"):
        NetworkProbe(config, FakeGateway()).verify()


def test_network_probe_accepts_agent_portfolio_shape_without_resource_type() -> None:
    from market.canary import CanaryGateway, NetworkProbe

    class FakeGateway(CanaryGateway):
        def check_health(self, label: str, url: str) -> dict:
            return {"ok": True}

        def fetch_agent_card(self, agent_url: str) -> dict:
            return {"name": "agent"}

        def fetch_registration_document(self, agent_url: str) -> dict:
            agent_id = 101 if "50" in agent_url else 202
            return {
                "registrations": [
                    {
                        "agentId": agent_id,
                        "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                    }
                ]
            }

        def fetch_resource_portfolio(self, agent_url: str) -> dict:
            return {
                "resources": [
                    {
                        "resource_id": "compute-h200-canary-003",
                        "gpu_model": "H200",
                        "quantity": 1,
                        "sla": 90.0,
                        "region": "California, US",
                        "vm_host": "btc1",
                    }
                ]
            }

    NetworkProbe(
        _config(gpu_model="H200", quantity=1, region="California, US", sla=90.0),
        FakeGateway(),
    ).verify()


def test_network_probe_checks_frp_dashboard_when_configured() -> None:
    from market.canary import CanaryGateway, NetworkProbe

    events: list[tuple[str, str]] = []

    class FakeGateway(CanaryGateway):
        def check_health(self, label: str, url: str) -> dict:
            return {"ok": True}

        def check_frp_dashboard(self, url: str, password: str) -> dict:
            events.append((url, password))
            return {"proxies": []}

        def fetch_agent_card(self, agent_url: str) -> dict:
            return {"name": "agent"}

        def fetch_registration_document(self, agent_url: str) -> dict:
            agent_id = 101 if "50" in agent_url else 202
            return {
                "registrations": [
                    {
                        "agentId": agent_id,
                        "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                    }
                ]
            }

        def fetch_resource_portfolio(self, agent_url: str) -> dict:
            return {
                "resources": [
                    {
                        "resource_id": "compute-h200-canary-003",
                        "gpu_model": "H200",
                        "quantity": 1,
                        "sla": 90.0,
                        "region": "California, US",
                        "vm_host": "btc1",
                    }
                ]
            }

    NetworkProbe(
        _config(
            gpu_model="H200",
            quantity=1,
            region="California, US",
            sla=90.0,
            frp_dashboard_url="https://frp-admin.example.test",
            frp_dashboard_password="top-secret",
        ),
        FakeGateway(),
    ).verify()

    assert events == [("https://frp-admin.example.test", "top-secret")]


def test_network_probe_rejects_agent_id_mismatch_with_registration_document() -> None:
    from market.canary import CanaryGateway, NetworkProbe

    class FakeGateway(CanaryGateway):
        def check_health(self, label: str, url: str) -> dict:
            return {"ok": True}

        def fetch_agent_card(self, agent_url: str) -> dict:
            return {"name": "agent"}

        def fetch_registration_document(self, agent_url: str) -> dict:
            if "50" in agent_url:
                return {
                    "registrations": [
                        {
                            "agentId": 999,
                            "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                        }
                    ]
                }
            return {
                "registrations": [
                    {
                        "agentId": 202,
                        "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                    }
                ]
            }

        def fetch_resource_portfolio(self, agent_url: str) -> dict:
            return {
                "resources": [
                    {
                        "resource_id": "compute-h200-canary-003",
                        "gpu_model": "H200",
                        "quantity": 1,
                        "sla": 90.0,
                        "region": "California, US",
                        "vm_host": "btc1",
                    }
                ]
            }

    config = _config(gpu_model="H200", quantity=1, region="California, US", sla=90.0)

    with pytest.raises(SystemExit, match="seller agent registration does not include configured agent id"):
        NetworkProbe(config, FakeGateway()).verify()
