"""The cross-registry client's read of each registry's signed descriptor.

Each registry's client is a fake built by the injected client factory, which
counts the descriptor reads made of it. A selection reads only the registries
it names; no selection reads every configured registry; a selection naming an
unconfigured registry, or a string in place of a collection, is refused before
anything is read.
"""

from __future__ import annotations

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import RegistryClientError

from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)

_SIGNER = Ed25519Signer(b"\x41" * 32)
_TRUST = RegistryAuthorityTrust(
    authority="registry-test",
    principals=TrustedIdentitySet(identities=(Ed25519Signer(b"\x42" * 32).identity,)),
)
_A = "https://registry-a.example"
_B = "https://registry-b.example"
_C = "https://registry-c.example"


class _DescriptorRegistry:
    """One registry, answering its descriptor or failing as an unreachable one."""

    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.reads = 0
        # The wrapper passes a descriptor through untouched, so its identity
        # shows which registry answered.
        self.descriptor = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def get_registry_descriptor(self) -> object:
        self.reads += 1
        if self.fails:
            raise RegistryClientError("GET", "/descriptor", 503, "unavailable")
        return self.descriptor


def _client(registries: dict[str, _DescriptorRegistry]) -> MultiRegistryClient:
    return MultiRegistryClient(
        list(registries),
        signer=_SIGNER,
        caller_role="seller",
        expected_registries={url: _TRUST for url in registries},
        client_factory=lambda url, **_kwargs: registries[url],
    )


@pytest.mark.asyncio
async def test_no_selection_reads_every_registry_and_keeps_a_failure_apart():
    registries = {_A: _DescriptorRegistry(), _B: _DescriptorRegistry(fails=True)}

    async with _client(registries) as client:
        descriptors = await client.get_descriptors()

    assert descriptors == {_A: registries[_A].descriptor, _B: None}
    assert list(descriptors) == [_A, _B]
    assert [registry.reads for registry in registries.values()] == [1, 1]


@pytest.mark.asyncio
async def test_a_selection_reads_and_returns_only_the_selected_registries():
    registries = {
        _A: _DescriptorRegistry(),
        _B: _DescriptorRegistry(),
        _C: _DescriptorRegistry(),
    }

    async with _client(registries) as client:
        descriptors = await client.get_descriptors(registries=[_C, _A])

    # Configured order, whatever order the selection names them in.
    assert list(descriptors) == [_A, _C]
    assert descriptors == {_A: registries[_A].descriptor, _C: registries[_C].descriptor}
    assert [registry.reads for registry in registries.values()] == [1, 0, 1]


@pytest.mark.asyncio
async def test_an_empty_selection_reads_nothing():
    registry = _DescriptorRegistry()

    async with _client({_A: registry}) as client:
        assert await client.get_descriptors(registries=[]) == {}

    assert registry.reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unconfigured",
    # Another registry, and a configured one spelled other than ``urls`` names it.
    [_C, _B + "/"],
)
async def test_a_selection_naming_an_unconfigured_registry_is_refused_and_reads_nothing(
    unconfigured: str,
):
    registries = {_A: _DescriptorRegistry(), _B: _DescriptorRegistry()}

    async with _client(registries) as client:
        with pytest.raises(ValueError, match="not configured") as refused:
            await client.get_descriptors(registries=[_A, unconfigured])

    assert repr(unconfigured) in str(refused.value)
    assert [registry.reads for registry in registries.values()] == [0, 0]


@pytest.mark.asyncio
async def test_a_string_given_as_the_selection_is_refused_and_reads_nothing():
    # A configured URL as a bare string: its characters are not registries.
    registries = {_A: _DescriptorRegistry()}

    async with _client(registries) as client:
        with pytest.raises(ValueError, match="not a string"):
            await client.get_descriptors(registries=_A)

    assert registries[_A].reads == 0
