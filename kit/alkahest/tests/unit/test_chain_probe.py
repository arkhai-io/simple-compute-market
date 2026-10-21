"""The Alkahest chain probe, over a stubbed JSON-RPC transport and clock.

Every address here is a deterministic development value and must never be used
on a public network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from market_alkahest import AlkahestChainProbe, AlkahestSettlementConfig, ProbedChain
from market_alkahest.chain_probe import (
    ADDRESS_CONFIG_INVALID,
    CHAIN_ID_MISMATCH,
    CHAIN_REACHABLE,
    CHAIN_UNREACHABLE,
    CONTRACT_MISSING,
    REQUIRED_CONTRACTS,
    required_contract_addresses,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.settlement_config import alkahest_preflight

ESCROW = "0x" + "11" * 20
ARBITER = "0x" + "22" * 20
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Rpc:
    """A chain's JSON-RPC endpoint: its chain ID, its code by address, or down.

    ``code`` of ``None`` answers code at every address; ``code_down`` fails
    every ``eth_getCode`` while ``eth_chainId`` still answers.
    """

    def __init__(
        self,
        *,
        chain_id: int = 31337,
        code: dict[str, str] | None = None,
        timeout: float = 5.0,
    ):
        self.chain_id = chain_id
        self.code = code if code is not None else {ESCROW: "0x6080", ARBITER: "0x6080"}
        self.timeout = timeout
        self.down = False
        self.code_down = False
        self.calls: list[str] = []

    def __call__(self, rpc_url, method, params, timeout):
        self.calls.append(method)
        assert timeout == self.timeout
        if self.down:
            raise TimeoutError("no answer")
        if method == "eth_chainId":
            return hex(self.chain_id)
        if self.code_down:
            raise ConnectionResetError("connection reset")
        return self.code.get(params[0], "0x")


class AnyCode(Rpc):
    """A chain with code at every address."""

    def __call__(self, rpc_url, method, params, timeout):
        self.calls.append(method)
        return hex(self.chain_id) if method == "eth_chainId" else "0x6080"


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def _probe(rpc: Rpc, clock: Clock | None = None, **options) -> AlkahestChainProbe:
    return AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", chain_id=31337)],
        json_rpc=rpc,
        required_addresses=lambda _chain: {"escrow": ESCROW, "arbiter": ARBITER},
        clock=clock or Clock(),
        **options,
    )


@pytest.mark.asyncio
async def test_a_chain_answering_with_its_contracts_is_reachable() -> None:
    probe = _probe(Rpc())

    report = await probe.step()

    assert probe.result("anvil").result == CHAIN_REACHABLE
    assert report["probed"] == ["anvil"]
    assert report["chains"] == {
        "anvil": {"result": CHAIN_REACHABLE, "probed_at": START.isoformat()}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rpc", "required", "expected"),
    [
        (Rpc(chain_id=1), None, CHAIN_ID_MISMATCH),
        (Rpc(code={ESCROW: "0x6080"}), None, CONTRACT_MISSING),
        (Rpc(), "raise", ADDRESS_CONFIG_INVALID),
    ],
    ids=["other-chain", "contract-missing", "address-config"],
)
async def test_each_configuration_result(rpc, required, expected) -> None:
    def addresses(_chain):
        if required == "raise":
            raise ValueError("anvil requires an address configuration")
        return {"escrow": ESCROW, "arbiter": ARBITER}

    probe = AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", chain_id=31337)],
        json_rpc=rpc,
        required_addresses=addresses,
        clock=Clock(),
    )

    await probe.step()

    assert probe.result("anvil").result == expected


@pytest.mark.asyncio
async def test_a_chain_that_does_not_answer_is_unreachable() -> None:
    rpc = Rpc()
    rpc.down = True
    probe = _probe(rpc)

    await probe.step()

    assert probe.result("anvil").result == CHAIN_UNREACHABLE


@pytest.mark.asyncio
async def test_a_chain_that_stops_answering_after_its_identity_is_unreachable() -> None:
    rpc = Rpc()
    rpc.code_down = True
    probe = _probe(rpc)

    await probe.step()

    assert probe.result("anvil").result == CHAIN_UNREACHABLE
    assert rpc.calls == ["eth_chainId", "eth_getCode"]


@pytest.mark.asyncio
async def test_every_call_is_bounded_by_the_configured_timeout() -> None:
    rpc = Rpc(timeout=2.5)
    probe = _probe(rpc, rpc_timeout_seconds=2.5)

    await probe.step()

    assert probe.result("anvil").result == CHAIN_REACHABLE
    assert rpc.calls == ["eth_chainId", "eth_getCode", "eth_getCode"]


@pytest.mark.asyncio
async def test_the_required_contracts_are_read_from_the_chains_address_book() -> None:
    book = str(anvil_address_book_path())
    seen: list[str] = []

    class Recording(AnyCode):
        def __call__(self, rpc_url, method, params, timeout):
            if method == "eth_getCode":
                seen.append(params[0])
            return super().__call__(rpc_url, method, params, timeout)

    probe = AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", address_config_path=book)],
        json_rpc=Recording(),
        clock=Clock(),
    )

    await probe.step()

    expected = required_contract_addresses(
        ProbedChain(name="anvil", rpc_url="http://anvil.test", address_config_path=book)
    )
    assert set(expected) == {label for _path, label in REQUIRED_CONTRACTS}
    assert seen == list(expected.values())
    assert probe.result("anvil").result == CHAIN_REACHABLE


def test_an_address_book_naming_no_required_contract_cannot_be_probed(tmp_path) -> None:
    book = tmp_path / "addresses.json"
    book.write_text("{}", encoding="utf-8")

    with pytest.raises(Exception):
        required_contract_addresses(
            ProbedChain(name="anvil", rpc_url="http://anvil.test", address_config_path=str(book))
        )


def test_a_chain_has_no_result_before_its_first_probe() -> None:
    probe = _probe(Rpc())

    assert probe.result("anvil") is None
    assert probe.public_results() == {"anvil": None}


def _readiness_resources(probe: AlkahestChainProbe) -> dict:
    return {
        "wallet": {"address": "0x" + "33" * 20},
        "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
        "chain_name": "anvil",
        "chain_probe": probe,
    }


@pytest.mark.asyncio
async def test_readiness_calls_no_chain_however_often_it_runs() -> None:
    rpc = Rpc()
    probe = _probe(rpc)
    await probe.step()
    calls = len(rpc.calls)

    for _ in range(10):
        await alkahest_preflight(
            AlkahestSettlementConfig(enabled=True), _readiness_resources(probe), "seller"
        )

    assert len(rpc.calls) == calls


@pytest.mark.asyncio
async def test_each_step_probes_every_chain_without_waiting_for_the_interval() -> None:
    """The loop's timer spaces the steps; an explicit step always probes, so a
    held scenario stepping the loop sees the chain as it is now."""
    rpc = Rpc()
    clock = Clock()
    probe = _probe(rpc, clock, interval_seconds=30.0)
    await probe.step()
    rpc.down = True

    second = await probe.step()

    assert second["probed"] == ["anvil"]
    assert probe.result("anvil").result == CHAIN_UNREACHABLE
    assert probe.interval_seconds == 30.0


@pytest.mark.asyncio
async def test_readiness_reports_a_held_result_however_old() -> None:
    rpc = Rpc()
    clock = Clock()
    probe = _probe(rpc, clock)
    await probe.step()

    rpc.down = True
    clock.now += timedelta(days=3)
    readiness = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True), _readiness_resources(probe), "seller"
    )

    assert readiness.ready is True
    assert readiness.public_details["chain_probe"] == {
        "anvil": {"result": CHAIN_REACHABLE, "probed_at": START.isoformat()}
    }


@pytest.mark.asyncio
async def test_a_missing_client_is_rebuilt_on_a_later_probe_in_the_live_map() -> None:
    attempts: list[str] = []

    def build(chain_name: str) -> object:
        attempts.append(chain_name)
        if len(attempts) == 1:
            raise ConnectionError("rpc refused")
        return f"client:{chain_name}"

    clients: dict[str, object] = {}
    clock = Clock()
    probe = _probe(Rpc(), clock, build_client=build, clients=clients)

    await probe.step()
    assert clients == {}
    await probe.step()

    assert probe.clients is clients
    assert clients == {"anvil": "client:anvil"}
    await probe.step()
    assert attempts == ["anvil", "anvil"]
