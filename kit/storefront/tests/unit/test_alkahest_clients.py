from __future__ import annotations

from dataclasses import dataclass, field

import market_storefront_kit.alkahest_clients as subject
import pytest
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    alkahest_client_constructor,
    build_alkahest_clients,
)


@dataclass
class Log:
    warnings: list[tuple[object, ...]] = field(default_factory=list)
    infos: list[tuple[object, ...]] = field(default_factory=list)

    def warning(self, message, *args, **_kwargs):
        self.warnings.append((message, *args))

    def info(self, message, *args, **_kwargs):
        self.infos.append((message, *args))


class Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_factory_builds_each_chain_from_injected_immutable_values(monkeypatch):
    prewarmed: list[str | None] = []
    monkeypatch.setattr(
        subject,
        "_load_dependencies",
        lambda: (
            Client,
            lambda name: f"network:{name}",
            prewarmed.append,
            lambda network, *, config_path: (network, config_path),
        ),
    )

    clients = build_alkahest_clients(
        AlkahestClientPolicy(
            private_key="secret",
            chains=(
                AlkahestChain(
                    name="anvil",
                    rpc_url="http://rpc",
                    address_book="addresses.json",
                ),
            ),
        )
    )

    assert tuple(clients) == ("anvil",)
    assert clients["anvil"].kwargs == {
        "private_key": "secret",
        "rpc_url": "http://rpc",
        "address_config": ("network:anvil", "addresses.json"),
    }
    assert prewarmed == ["addresses.json"]


def test_factory_omits_only_the_chain_that_fails(monkeypatch):
    def resolve(network, *, config_path):
        if network == "bad":
            raise ValueError("bad config")
        return config_path

    monkeypatch.setattr(
        subject,
        "_load_dependencies",
        lambda: (Client, lambda name: name, lambda _path: None, resolve),
    )
    log = Log()

    clients = build_alkahest_clients(
        AlkahestClientPolicy(
            private_key="secret",
            chains=(
                AlkahestChain("bad", "http://bad"),
                AlkahestChain("good", "http://good"),
            ),
        ),
        logger=log,
    )

    assert tuple(clients) == ("good",)
    assert len(log.warnings) == 1


def test_the_constructor_builds_one_chain_and_raises_for_one_that_fails(monkeypatch):
    def resolve(network, *, config_path):
        if network == "bad":
            raise ValueError("bad config")
        return config_path

    monkeypatch.setattr(
        subject,
        "_load_dependencies",
        lambda: (Client, lambda name: name, lambda _path: None, resolve),
    )
    construct = alkahest_client_constructor(
        AlkahestClientPolicy(
            private_key="secret",
            chains=(
                AlkahestChain("bad", "http://bad"),
                AlkahestChain("good", "http://good", "good.json"),
            ),
        )
    )

    assert construct is not None
    assert construct("good").kwargs == {
        "private_key": "secret",
        "rpc_url": "http://good",
        "address_config": "good.json",
    }
    with pytest.raises(ValueError, match="bad config"):
        construct("bad")


def test_no_constructor_while_a_requirement_is_missing():
    assert (
        alkahest_client_constructor(
            AlkahestClientPolicy(
                private_key=None, chains=(AlkahestChain("anvil", "http://rpc"),)
            )
        )
        is None
    )


def test_factory_fails_closed_before_loading_sdk_when_requirements_are_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        subject,
        "_load_dependencies",
        lambda: (_ for _ in ()).throw(AssertionError("SDK loaded")),
    )

    assert build_alkahest_clients(
        AlkahestClientPolicy(
            private_key=None,
            chains=(AlkahestChain("anvil", "http://rpc"),),
            missing_requirements=("wallet.address",),
        )
    ) == {}
