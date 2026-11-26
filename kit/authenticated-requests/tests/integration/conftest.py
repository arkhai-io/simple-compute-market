from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import injected_time
import pytest
from market_identity import Ed25519Signer, Eip191Signer, Signer
from tests.integration.support import START, STRANGER_SEED, World, make_world


# Well-known deterministic development keys, never for a public network: the
# Ed25519 seed is the bytes 3..34, the EIP-191 key a public test-chain account's.
CALLER_ED25519_SEED = bytes(range(3, 35))
CALLER_EIP191_KEY = bytes.fromhex("5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a")


@pytest.fixture(autouse=True)
def injected_clock() -> Iterator[injected_time.InjectedTime]:
    previous = injected_time.installed()
    source = injected_time.install(injected_time.InjectedTime(START))
    yield source
    injected_time.install(previous)


@pytest.fixture(params=["ed25519", "eip191"])
def caller_signer(request: pytest.FixtureRequest) -> Signer:
    if request.param == "ed25519":
        return Ed25519Signer(CALLER_ED25519_SEED)
    return Eip191Signer(CALLER_EIP191_KEY)


@pytest.fixture
def stranger() -> Signer:
    return Ed25519Signer(STRANGER_SEED)


@pytest.fixture(params=["middleware", "dependency"])
def form(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def world(tmp_path: Path, form: str, caller_signer: Signer) -> World:
    return make_world(tmp_path, form, caller_signer)
