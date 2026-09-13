"""One production buyer client negotiates an advertised Alkahest option.

The whole path runs for real: `core_buyer.negotiation_client.negotiate_with_seller`
signs and serializes the request, the composed bare-metal storefront app
authenticates it, accepts through the shared registry, signs its reply, and the
same client parses that reply, verifies the response signature and runs
`_validate_settlement_acceptance` plus the domain's own accepted-plan callback.

Only the socket is substituted: `urllib.request.urlopen` is routed into a
Starlette test client for the real seller app. Request bytes, response bytes,
signatures, status codes and both sides' validation are the production ones.

Every fixture value is obviously synthetic development material with no value on
any network and must never be used on one. Nothing is published, purchased,
funded or provisioned; the seller writes only to a temporary SQLite database.
"""

from __future__ import annotations

import base64
import io
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any

import pytest
from arkhai_bare_metal import make_bare_metal_provision_terms
from arkhai_bare_metal_buyer.settlement_composition import (
    bare_metal_escrow_proposal,
    validate_accepted_alkahest_plan,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from core_buyer.negotiation_client import negotiate_with_seller
from fastapi.testclient import TestClient
from market_alkahest import AlkahestSettlementConfig, create_alkahest_registration
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import Eip191Signer, TrustedIdentitySet
from market_settlement_runtime import MechanismReadiness

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
SELLER_WALLET = "0x" + "bb" * 20
ESCROW_ADDRESS = "0x" + "11" * 20
TOKEN_ADDRESS = "0x" + "aa" * 20
CHAIN = "base_sepolia"

LISTING_ID = "alkahest-listing"
OTHER_LISTING_ID = "other-listing"
MACHINE_ID = "bm-machine-1"
PHYSICAL_HOST_ID = "physical-host-1"
SITE_ID = "site-a"
POOL_ID = "pool-a"
PHYSICAL_RESOURCE_ID = "resource-1"
OTHER_MACHINE_ID = "bm-machine-2"
OTHER_PHYSICAL_HOST_ID = "physical-host-2"
SSH_PUBLIC_KEY = "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()
DURATION_SECONDS = 7200
RATE_PER_HOUR = 1000
SELLER_URL = "http://seller.invalid:8000"

ACCEPTED_ESCROW = {
    "chain_name": CHAIN,
    "escrow_address": ESCROW_ADDRESS,
    "literal_fields": {"token": TOKEN_ADDRESS},
    "rates": [{"field": "amount", "per": "hour", "value": str(RATE_PER_HOUR)}],
}


def _published_option() -> SettlementOption:
    """The advertised option, from the real Alkahest publication builder."""

    registration = create_alkahest_registration()
    artifacts = registration.option_builder(
        AlkahestSettlementConfig(enabled=True),
        MechanismReadiness(
            mechanism="alkahest.v1",
            configured=True,
            enabled=True,
            ready=True,
        ),
        {"accepted_escrows": [ACCEPTED_ESCROW]},
        "seller",
    )
    option = SettlementOption.model_validate(artifacts["settlement_options"][0])
    assert set(option.params) == {"accepted_escrow"}
    return option


async def _runtime(tmp_path, option: SettlementOption) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    for listing_id, machine_id, host_id, resource_id in (
        (LISTING_ID, MACHINE_ID, PHYSICAL_HOST_ID, PHYSICAL_RESOURCE_ID),
        (OTHER_LISTING_ID, OTHER_MACHINE_ID, OTHER_PHYSICAL_HOST_ID, "resource-2"),
    ):
        await db.upsert_bare_metal_listing(
            listing_id=listing_id,
            status="open",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            seller_principal=SELLER_SIGNER.identity,
            storefront_url=SELLER_URL,
            site_id=SITE_ID,
            pool_id=POOL_ID,
            physical_resource_id=resource_id,
            listing={
                "kind": "bare_metal.v1",
                "machine_id": machine_id,
                "physical_host_id": host_id,
                "access_methods": ["ssh"],
                "min_duration_seconds": 3600,
                "max_duration_seconds": 14400,
            },
            accepted_escrows=[],
            settlement_options=[option.model_dump(mode="json")]
            if listing_id == LISTING_ID
            else [],
        )
    return BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url=SELLER_URL,
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address=SELLER_WALLET,
        settlement_composition=BareMetalStorefrontSettlementComposition.from_raw_config(
            {"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
            resources={"wallet": {"address": SELLER_WALLET}, "clients": {}},
        ),
        plan_builder=lambda **kwargs: {},
    )


class _AppTransport:
    """Route one urllib request into the real seller app, bytes for bytes."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        del timeout
        response = self._client.request(
            request.get_method(),
            request.full_url,
            content=request.data,
            headers={key: value for key, value in request.header_items()},
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                "error",
                response.headers,  # type: ignore[arg-type]
                io.BytesIO(response.content),
            )
        return _Answer(response)


class _Answer:
    """The subset of a urllib response the client actually reads."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.status = response.status_code
        self.headers = response.headers

    def read(self) -> bytes:
        return self._response.content

    def __enter__(self) -> "_Answer":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _expected_physical_terms(option: SettlementOption) -> dict[str, Any]:
    """The envelope this listing must produce, written out independently."""

    return {
        "listing_id": LISTING_ID,
        "option_id": option.option_id,
        "mechanism": "alkahest.v1",
        "physical_binding": {
            "site_id": SITE_ID,
            "pool_id": POOL_ID,
            "physical_resource_id": PHYSICAL_RESOURCE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "access_method": "ssh",
        },
        "provision_terms": {
            "kind": "bare_metal.v1",
            "machine_id": MACHINE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "duration_seconds": DURATION_SECONDS,
            "access_method": "ssh",
            "ssh_public_key": SSH_PUBLIC_KEY,
            "listing_ref": LISTING_ID,
        },
    }


def _negotiate(
    runtime: BareMetalStorefrontRuntime,
    option: SettlementOption,
    monkeypatch: pytest.MonkeyPatch,
    *,
    listing_id: str = LISTING_ID,
    duration_seconds: int = DURATION_SECONDS,
    expiration_unix: int | None = None,
    access_method: str = "ssh",
    trusted_seller_principals: TrustedIdentitySet | None = None,
    extra_payload: dict[str, Any] | None = None,
):
    """Run one real client negotiation against the real seller app."""

    expiry = expiration_unix or (int(time.time()) + 3600)
    proposal = bare_metal_escrow_proposal(
        listing={"demands": []},
        option=option,
        expiration_unix=expiry,
    )
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=expiry,
    )
    provision_terms = make_bare_metal_provision_terms(
        duration_seconds=duration_seconds,
        ssh_public_key=SSH_PUBLIC_KEY,
    )
    if access_method != "ssh" or extra_payload:
        payload = dict(provision_terms.payload)
        if access_method != "ssh":
            payload["access_method"] = access_method
            payload.pop("ssh_public_key", None)
        payload.update(extra_payload or {})
        provision_terms = provision_terms.model_copy(update={"payload": payload})
    app = build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )
    with TestClient(app) as client:
        monkeypatch.setattr(urllib.request, "urlopen", _AppTransport(client))
        return negotiate_with_seller(
            seller_url=SELLER_URL,
            principal=BUYER_SIGNER.identity,
            signer=BUYER_SIGNER,
            listing_id=listing_id,
            resolve_seller_principals=lambda: (
                trusted_seller_principals
                or TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
            ),
            initial_price=float(RATE_PER_HOUR),
            max_price=float(RATE_PER_HOUR),
            unit_count=duration_seconds / 3600,
            provision_terms=provision_terms,
            settlement_selection=selection,
            policy_params={
                "_selected_settlement_option": option.model_dump(mode="json")
            },
            validate_advertised_plan=lambda plan: validate_accepted_alkahest_plan(
                plan=plan,
                proposal=proposal,
                duration_seconds=duration_seconds,
                address_config_path=None,
                seller_payout_address=SELLER_WALLET,
            ),
        )


async def _counts(runtime: BareMetalStorefrontRuntime) -> dict[str, int]:
    with sqlite3.connect(runtime.db.db_path) as db:
        return {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "negotiation_threads",
                "negotiation_messages",
                "settlement_obligations",
                "capacity_holds",
            )
        }


async def test_production_client_negotiates_an_advertised_alkahest_option(
    tmp_path, monkeypatch
) -> None:
    option = _published_option()
    runtime = await _runtime(tmp_path, option)

    outcome = _negotiate(runtime, option, monkeypatch)

    assert outcome.status == "agreed"
    assert outcome.negotiation_id is not None
    assert outcome.agreed_amount == RATE_PER_HOUR * DURATION_SECONDS // 3600
    assert outcome.settlement_selection is not None
    assert outcome.settlement_selection.option_id == option.option_id
    plan = outcome.settlement_plan
    assert plan is not None
    # The whole physical envelope, against an expectation written out here
    # rather than read back from the seller's own answer.
    assert plan.service_terms["bare_metal.v1"] == _expected_physical_terms(option)
    assert plan.service_terms["alkahest.v1"]["option_id"] == option.option_id
    # The client checks the seller's echo against what it asked for; this is
    # that echo, still in the wire shape the client parsed it from.
    assert outcome.accepted_provision_terms == {
        "kind": "bare_metal.v1",
        "version": 1,
        "payload": {
            "duration_seconds": DURATION_SECONDS,
            "access_method": "ssh",
            "ssh_public_key": SSH_PUBLIC_KEY,
        },
    }

    counts = await _counts(runtime)
    assert counts["negotiation_threads"] == 1
    # Acceptance is not provisioning: nothing is held or reserved here.
    assert counts["capacity_holds"] == 0


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        pytest.param(
            {"expiration_unix": int(time.time()) - 60},
            "already expired",
            id="expired-selection",
        ),
        pytest.param(
            {"duration_seconds": 1800},
            "outside listing bounds",
            id="duration-below-listing-bound",
        ),
        pytest.param(
            {"access_method": "none"},
            "unadvertised access method",
            id="unadvertised-access",
        ),
        pytest.param(
            {"listing_id": OTHER_LISTING_ID},
            "does not exact-match",
            id="option-of-another-listing",
        ),
        pytest.param(
            # The physical identities are the seller's; a buyer that names one
            # is refused by the provision envelope before admission.
            {"extra_payload": {"machine_id": OTHER_MACHINE_ID}},
            "incompatible bare-metal provision terms",
            id="buyer-supplied-machine-identity",
        ),
        pytest.param(
            {"extra_payload": {"physical_host_id": OTHER_PHYSICAL_HOST_ID}},
            "incompatible bare-metal provision terms",
            id="buyer-supplied-host-identity",
        ),
        pytest.param(
            {"extra_payload": {"site_id": "substituted-site"}},
            "incompatible bare-metal provision terms",
            id="buyer-supplied-site",
        ),
        pytest.param(
            {"extra_payload": {"pool_id": "substituted-pool"}},
            "incompatible bare-metal provision terms",
            id="buyer-supplied-pool",
        ),
        pytest.param(
            {"extra_payload": {"physical_resource_id": "substituted-resource"}},
            "incompatible bare-metal provision terms",
            id="buyer-supplied-resource",
        ),
    ],
)
async def test_client_negotiation_is_refused_and_nothing_is_written(
    tmp_path, monkeypatch, kwargs, detail
) -> None:
    option = _published_option()
    runtime = await _runtime(tmp_path, option)

    with pytest.raises(RuntimeError, match=detail):
        _negotiate(runtime, option, monkeypatch, **kwargs)

    assert await _counts(runtime) == {
        "negotiation_threads": 0,
        "negotiation_messages": 0,
        "settlement_obligations": 0,
        "capacity_holds": 0,
    }


async def test_client_refuses_a_reply_from_an_untrusted_seller_principal(
    tmp_path, monkeypatch
) -> None:
    """A signed reply is only an answer if it came from the pinned seller.

    This rejection happens after the seller has already accepted and written
    its own thread — the buyer's refusal protects the buyer, not the seller's
    storage, so the negotiation row is expected to exist.
    """

    option = _published_option()
    runtime = await _runtime(tmp_path, option)

    with pytest.raises(RuntimeError, match="authentication failed|untrusted seller"):
        _negotiate(
            runtime,
            option,
            monkeypatch,
            trusted_seller_principals=TrustedIdentitySet(
                identities=(ADMIN_SIGNER.identity,)
            ),
        )

    assert (await _counts(runtime))["capacity_holds"] == 0
