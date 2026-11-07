from __future__ import annotations

from tests._settings_overrides import settings_overrides

from .conftest import fake_chain


def test_redeliver_refuses_a_retired_address_book_key(monkeypatch, runner, app):
    """Spec scenario "A retired key is stated", through a command run without
    the server's startup refusal: opening a legacy database synthesizes its
    listings' accepted escrows from each chain's address book, and the
    refusal that raises is reported by name instead of escaping as a
    traceback."""
    from market_storefront.utils.config import chain_address_books

    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain("anvil")})
    monkeypatch.setattr(
        "market_storefront.services.capacity_client._capacity_settings",
        lambda: ({}, None),
    )
    monkeypatch.setattr(
        "market_storefront.utils.sqlite_client.get_sqlite_client",
        lambda **_kwargs: chain_address_books(),
    )

    with settings_overrides(**{"chains.anvil.alkahest_address_config_path": "/book.json"}):
        result = runner.invoke(
            app, ["settlement", "contact", "redeliver", "--obligation-ref", "0xREF"]
        )

    assert result.exit_code == 2
    assert "[Chains.anvil].alkahest_address_config_path is retired" in result.output
    assert "[Settlement.alkahest.address_books]" in result.output
    assert "/book.json" not in result.output
