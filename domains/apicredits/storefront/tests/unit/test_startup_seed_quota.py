"""The configured seed listing, created by the ``listing-seed`` step.

The quota registration goes through the typed capacity-administration client,
over a stub transport standing for the credits service. The step's own tests
construct it with the boundaries it acts through replaced: the registration,
the listing lookup, and the listing service. Its cycles run through the
storefront's own loop controller, which records each one's outcome. Every key
and address here is a deterministic development value, never for a public
network.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from core_storefront.auth import signed_response_headers
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_site_client import SiteCapacityAdminClientError, SiteCapacityClientError

from apicredits_storefront import listing_seed
from apicredits_storefront.lifecycle_steps import api_credit_loop_controller
from apicredits_storefront.listing_seed import (
    CREDITS_SERVICE_UNANSWERED,
    DONE,
    GIVEN_UP,
    LISTING_SEED,
    LISTING_SEED_ROUTE,
    SETTLEMENT_MECHANISM_UNREACHED,
    WAITING,
    ListingSeed,
    ListingSeedGivenUp,
)
from apicredits_storefront.services.listing_service import SettlementMechanismUnreachable
from apicredits_storefront.utils import config as storefront_config
from tests._settings_overrides import settings_overrides

_SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
_AUTHORITY_SIGNER = Ed25519Signer(bytes.fromhex("33" * 32))
_CREDITS_SITE = SimpleNamespace(
    url="http://credits-service:8082",
    expected_authorities=TrustedIdentitySet(identities=(_AUTHORITY_SIGNER.identity,)),
)
_SEED = {
    "resource_id": "demo-quota",
    "service_name": "Acme",
    "chain": "anvil",
    "token": "0x" + "01" * 20,
    "escrow_address": "0x" + "11" * 20,
    "total_units": 100,
}
_ANVIL = ChainConfig(name="anvil", rpc_url="http://anvil.test", chain_id=31337)


def _signed_response(request: httpx.Request, *, status: int, body) -> httpx.Response:
    headers = signed_response_headers(
        signer=_AUTHORITY_SIGNER,
        role="service",
        method=request.method,
        operation="capacity_resource_put",
        resource="demo-quota",
        request_id=request.headers["X-Market-Request-ID"],
        status=status,
        body=body,
    )
    return (
        httpx.Response(status, json=body, headers=headers)
        if isinstance(body, dict)
        else httpx.Response(status, text=body, headers=headers)
    )


async def _register(handle) -> None:
    await listing_seed.register_seed_quota(
        resource_id="demo-quota",
        total_units=100,
        site=_CREDITS_SITE,
        signer=_SELLER_SIGNER,
        transport=httpx.MockTransport(handle),
    )


@pytest.mark.asyncio
async def test_the_quota_is_registered_through_the_typed_client():
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return _signed_response(request, status=200, body={"resource_id": "demo-quota"})

    await _register(handle)

    assert captured["path"] == "/api/v1/capacity/resources/demo-quota"
    assert captured["headers"]["x-market-role"] == "seller"
    # Declared explicitly in the quota's own dimension, in its pool.
    assert captured["body"]["capacity"] == {"units": 100}
    assert captured["body"]["pool_id"] == "default"
    assert captured["body"]["resource_type"] == "api_credits"


@pytest.mark.asyncio
async def test_a_ledger_refusal_raises_the_clients_error():
    def handle(request: httpx.Request) -> httpx.Response:
        return _signed_response(request, status=409, body="pool mismatch")

    with pytest.raises(SiteCapacityAdminClientError) as refused:
        await _register(handle)

    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_an_unanswering_ledger_raises_the_clients_error_with_no_status():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SiteCapacityAdminClientError) as unanswered:
        await _register(handle)

    assert unanswered.value.status_code is None


class _Listings:
    """The listing service: what each publish answers."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    async def publish_from_quota(self, **request):
        self.calls.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Registrations:
    """The quota registration: what each attempt answers, ``None`` registering."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, **_request) -> None:
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, Exception):
            raise answer


async def _no_listing(_resource_id: str) -> None:
    return None


@pytest.fixture
def seeded():
    """A seed over the given boundaries, and the loop controller stepping it."""

    def install(listings, *, register=None, find=_no_listing):
        seed = ListingSeed(
            seed=dict(_SEED),
            register_quota=register or _Registrations(),
            find_listing=find,
            listing_service=listings,
        )
        controller = api_credit_loop_controller()
        controller.register_step(LISTING_SEED, route=LISTING_SEED_ROUTE, step=seed.step)
        return seed, controller

    with patch.dict(storefront_config.CHAINS, {"anvil": _ANVIL}, clear=True):
        yield install


def _errors(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


# Known flaky: the `no-response` case failed once in a full `make test` on
# 2026-10-28, with asyncio reporting a task destroyed while pending, and passed
# on every rerun. Not yet investigated.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unanswered",
    [
        pytest.param(SiteCapacityAdminClientError("PUT failed"), id="no-response"),
        pytest.param(SiteCapacityAdminClientError("PUT 503", status_code=503), id="5xx"),
    ],
)
async def test_the_seed_waits_while_the_credits_service_does_not_answer_its_registration(
    seeded, caplog, unanswered
):
    registrations = _Registrations(unanswered, None)
    listings = _Listings({"listing_id": "L-1"})
    seed, controller = seeded(listings, register=registrations)

    waiting = await controller.run_cycle(LISTING_SEED_ROUTE)
    assert (waiting["state"], waiting["reason"]) == (WAITING, CREDITS_SERVICE_UNANSWERED)
    assert listings.calls == []
    done = await controller.run_cycle(LISTING_SEED_ROUTE)

    assert (done["state"], done["listing_id"]) == (DONE, "L-1")
    assert controller.last_outcome(LISTING_SEED).completed
    assert _errors(caplog) == []


@pytest.mark.asyncio
async def test_the_seed_waits_while_the_credits_service_does_not_answer_its_availability_read(
    seeded, caplog
):
    registrations = _Registrations()
    listings = _Listings(SiteCapacityClientError("GET failed"), {"listing_id": "L-1"})
    seed, controller = seeded(listings, register=registrations)

    waiting = await controller.run_cycle(LISTING_SEED_ROUTE)
    done = await controller.run_cycle(LISTING_SEED_ROUTE)

    assert (waiting["state"], waiting["reason"]) == (WAITING, CREDITS_SERVICE_UNANSWERED)
    assert done["state"] == DONE
    # Registered once: the ledger re-asserts a registration it already holds.
    assert registrations.calls == 1
    assert _errors(caplog) == []


@pytest.mark.asyncio
async def test_the_seed_waits_while_a_mechanism_it_uses_is_unknown(seeded, caplog):
    listings = _Listings(SettlementMechanismUnreachable(("alkahest.v1",)), {"listing_id": "L-1"})
    seed, controller = seeded(listings)

    waiting = await controller.run_cycle(LISTING_SEED_ROUTE)
    done = await controller.run_cycle(LISTING_SEED_ROUTE)

    assert (waiting["state"], waiting["reason"]) == (WAITING, SETTLEMENT_MECHANISM_UNREACHED)
    assert waiting["mechanisms"] == ["alkahest.v1"]
    assert _errors(caplog) == []
    assert (done["state"], done["listing_id"]) == (DONE, "L-1")
    # The seed waits for every mechanism it uses, not only when nothing would
    # publish, and offers its escrow on its configured chain.
    assert all(call["wait_for_every_mechanism"] for call in listings.calls)
    (escrow,) = listings.calls[0]["accepted_escrows"]
    assert escrow["chain_name"] == "anvil"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("registration", "publish", "error_type"),
    [
        pytest.param(
            None,
            ValueError("no settlement alternative is ready (alkahest.chains_missing)"),
            "ValueError",
            id="unready-for-configuration",
        ),
        pytest.param(
            SiteCapacityAdminClientError("PUT 409", status_code=409),
            None,
            "SiteCapacityAdminClientError",
            id="ledger-refusal",
        ),
    ],
)
async def test_the_seed_gives_up_once_and_its_cycle_records_the_failure(
    seeded, caplog, registration, publish, error_type
):
    listings = _Listings(*([publish] if publish is not None else []))
    seed, controller = seeded(listings, register=_Registrations(registration))

    with pytest.raises(ListingSeedGivenUp):
        await controller.run_cycle(LISTING_SEED_ROUTE)
    failed = controller.last_outcome(LISTING_SEED)
    later = await controller.run_cycle(LISTING_SEED_ROUTE)

    assert not failed.completed
    assert failed.error.type == "ListingSeedGivenUp"
    assert (later["state"], later["reason"], later["attempts"]) == (GIVEN_UP, error_type, 1)
    assert len(listings.calls) == (1 if publish is not None else 0)
    # Logged once, by the cycle that gave up, and naming no error text.
    (logged,) = _errors(caplog)
    assert "chains_missing" not in later["reason"]
    assert LISTING_SEED in logged.getMessage()


@pytest.mark.asyncio
async def test_the_seed_finishes_on_a_listing_already_there(seeded):
    async def found(_resource_id: str) -> str:
        return "L-existing"

    listings = _Listings()
    registrations = _Registrations()
    seed, controller = seeded(listings, register=registrations, find=found)

    report = await controller.run_cycle(LISTING_SEED_ROUTE)
    again = await controller.run_cycle(LISTING_SEED_ROUTE)

    assert (report["state"], report["listing_id"]) == (DONE, "L-existing")
    assert again["attempts"] == 1
    assert listings.calls == []
    assert registrations.calls == 0


_SITE_A = "http://site-a:8082"
_SITE_B = "http://site-b:8082"


def _capacity_sites(**urls: str) -> dict:
    """``[capacity.sites]`` naming each site's URL, each trusting the authority
    signer."""
    authority = _AUTHORITY_SIGNER.identity.model_dump(mode="json")
    return {
        site_id: {"url": url, "expected_authorities": {"identities": [authority]}}
        for site_id, url in urls.items()
    }


@pytest.mark.parametrize(
    ("sites", "named", "expected"),
    [
        ({"a": _SITE_A}, "", _SITE_A),
        ({"a": _SITE_A, "b": _SITE_B}, "b", _SITE_B),
    ],
    ids=["the only site", "the named site"],
)
def test_the_seed_registers_at_its_site(sites, named, expected):
    with settings_overrides(
        capacity__sites=_capacity_sites(**sites), capacity__seed_site=named
    ):
        assert listing_seed.capacity_authority_site().url == expected


@pytest.mark.parametrize(
    ("sites", "named", "message"),
    [
        ({"a": _SITE_A, "b": _SITE_B}, "", "seed_site is required"),
        ({"a": _SITE_A}, "missing", "unknown capacity.seed_site 'missing'"),
    ],
    ids=["several sites and none named", "an unknown site named"],
)
def test_a_seed_site_the_configuration_cannot_name_is_refused(sites, named, message):
    """Resolved when the seed registers, so the step gives up rather than
    stopping startup."""
    with settings_overrides(
        capacity__sites=_capacity_sites(**sites), capacity__seed_site=named
    ), pytest.raises(RuntimeError, match=message):
        listing_seed.capacity_authority_site()


@pytest.mark.asyncio
async def test_the_seeds_listing_is_found_beyond_the_first_page():
    """Every open listing is read, so a storefront with more open listings than
    one page still finds the seeded one rather than creating it again."""
    rows = [
        {"listing_id": f"L-{index}", "listing_resource": {"resource_id": f"other-{index}"}}
        for index in range(listing_seed._LISTING_PAGE)
    ] + [{"listing_id": "L-seed", "listing_resource": json.dumps({"resource_id": "demo-quota"})}]

    class _Db:
        async def list_listings(self, *, status, limit, offset):
            assert status == "open"
            return rows[offset : offset + limit]

    assert await listing_seed._listing_for(_Db(), "demo-quota") == "L-seed"
    assert await listing_seed._listing_for(_Db(), "absent") is None
