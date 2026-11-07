"""The listing entry points: the publish route reaches the composed listing
service with what was asked, and the CLI's listing commands are clients of the
running storefront.

The CLI's storefront client is replaced at ``_open_storefront``, the one place
the commands reach the storefront through, so these tests show the request the
listing client builds and the signer each command opens with, not the signed
transport itself; constructing the storefront's services or its database fails
the test. Every key is a deterministic development value, never for a public
network.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
from market_identity import Ed25519Signer
from storefront_client import StorefrontClientError
from storefront_client.models import ListingListResponse
from typer.testing import CliRunner

from apicredits_storefront import cli, server
from apicredits_storefront.controllers.listings_controller import (
    ListingsController,
    PublishFromQuotaRequest,
)
from apicredits_storefront.listing_publication import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
)
from apicredits_storefront.utils import config as storefront_config
from apicredits_storefront.utils import sqlite_client as sqlite_module
from tests._settings_overrides import replaced_setting

SELLER = Ed25519Signer(b"\x22" * 32)


class _ListingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish_from_quota(self, **request):
        self.calls.append(request)
        return {"status": "created", "listing_id": "L-1"}


async def test_the_publish_route_passes_the_submitted_settlement_clauses():
    service = _ListingService()
    controller = ListingsController.__new__(ListingsController)
    controller._listing_svc = service
    clauses = [{"mechanism": "arkhai.payments.v1", "asset": "usd"}]

    await controller.publish_from_quota(
        PublishFromQuotaRequest(
            resource_id="svc-quota", service_name="Acme", settlement_clauses=clauses
        )
    )

    assert service.calls[0]["settlement_clauses"] == clauses


class _Storefront:
    """The running storefront, as the typed client reaches it."""

    def __init__(self, *, refuse: Exception | None = None) -> None:
        self.opened: list[tuple[str, object]] = []
        self.requests: list[tuple[tuple, dict]] = []
        self.refuse = refuse

    def open(self, url, signer):
        self.opened.append((url, signer))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def authenticated_request(self, *args, **kwargs):
        if self.refuse is not None:
            raise self.refuse
        self.requests.append((args, kwargs))
        return {"status": "created", "listing_id": "L-1"}

    def list_listings(self, *, status=None, limit=50, offset=0):
        if self.refuse is not None:
            raise self.refuse
        self.requests.append(((), {"status": status, "limit": limit, "offset": offset}))
        return ListingListResponse(listings=[], count=0, limit=limit, offset=offset)


def _never_composed(*_args, **_kwargs):
    raise AssertionError("a listing command composed the storefront's services")


def _never_opened(*_args, **_kwargs):
    raise AssertionError("a listing command opened the storefront's database")


def _cli(monkeypatch, storefront: _Storefront):
    monkeypatch.setattr(cli, "_open_storefront", storefront.open)
    monkeypatch.setattr(storefront_config, "resolve_identity_signer", lambda: SELLER)
    monkeypatch.setattr(
        storefront_config,
        "resolve_identity_config",
        lambda: SimpleNamespace(principal=SELLER.identity),
    )
    monkeypatch.setattr(server, "_build_api_credit_services", _never_composed)
    monkeypatch.setattr(sqlite_module.SQLiteClient, "__init__", _never_opened)
    return CliRunner()


def test_the_publish_command_creates_through_the_running_storefront(monkeypatch):
    storefront = _Storefront()

    result = _cli(monkeypatch, storefront).invoke(
        cli.app,
        [
            "publish",
            "--resource-id",
            "svc-quota",
            "--service-name",
            "Acme",
            "--storefront-url",
            "http://seller.test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert storefront.opened == [("http://seller.test", SELLER)]
    ((args, kwargs),) = storefront.requests
    assert args == ("POST", PUBLISH_FROM_QUOTA_PATH)
    assert kwargs["role"] == "seller"
    assert kwargs["operation"] == PUBLISH_FROM_QUOTA_OPERATION
    assert kwargs["body"]["resource_id"] == "svc-quota"
    assert '"listing_id": "L-1"' in result.output


def test_the_listings_command_reads_the_running_storefront_without_a_credential(
    monkeypatch,
):
    storefront = _Storefront()

    result = _cli(monkeypatch, storefront).invoke(
        cli.app, ["listings", "--status", "open", "-a", "http://seller.test"]
    )

    assert result.exit_code == 0, result.output
    assert storefront.opened == [("http://seller.test", None)]
    assert storefront.requests == [((), {"status": "open", "limit": 50, "offset": 0})]


def test_a_command_no_storefront_answers_fails_naming_where_it_was_sent(monkeypatch):
    storefront = _Storefront(refuse=httpx.ConnectError("connection refused"))

    result = _cli(monkeypatch, storefront).invoke(
        cli.app,
        ["publish", "--resource-id", "svc-quota", "--service-name", "Acme", "-a", "http://seller.test"],
    )

    assert result.exit_code == 1
    assert "no storefront answered at http://seller.test (ConnectError)" in result.output


def test_a_refused_create_fails_with_the_storefronts_reason(monkeypatch):
    storefront = _Storefront(
        refuse=StorefrontClientError(
            "settlement mechanism alkahest.v1 cannot be reached yet", status_code=503
        )
    )

    result = _cli(monkeypatch, storefront).invoke(
        cli.app,
        ["publish", "--resource-id", "svc-quota", "--service-name", "Acme", "-a", "http://seller.test"],
    )

    assert result.exit_code == 1
    assert "refused: settlement mechanism alkahest.v1 cannot be reached yet" in result.output


def test_publishing_an_alkahest_rate_refuses_a_retired_address_book_key(monkeypatch):
    """Spec scenario "A retired key is stated", through a command run without
    the server's startup refusal: the chain's escrow is not resolved from the
    built-in addresses, and the key and the table are named."""
    storefront = _Storefront()
    runner = _cli(monkeypatch, storefront)
    monkeypatch.setattr(storefront_config, "CHAINS", {"anvil": object()})
    monkeypatch.setattr(
        cli,
        "get_erc20_escrow_obligation_default",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an escrow was resolved")
        ),
    )

    with replaced_setting(
        "chains",
        {"anvil": {"rpc_url": "http://anvil.test", "alkahest_address_config_path": "/book.json"}},
    ):
        result = runner.invoke(
            cli.app,
            [
                "publish",
                "--resource-id",
                "svc-quota",
                "--service-name",
                "Acme",
                "--price-per-token",
                "1",
                "--token",
                "0x0000000000000000000000000000000000000001",
                "--chain",
                "anvil",
                "-a",
                "http://seller.test",
            ],
        )

    assert result.exit_code == 2
    assert "[Chains.anvil].alkahest_address_config_path is retired" in result.output
    assert "[Settlement.alkahest.address_books]" in result.output
    assert "/book.json" not in result.output
    assert storefront.requests == []
