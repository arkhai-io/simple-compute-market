"""`buy` drives the rail its selected option names, on both rails.

Every advertised option here is produced by the production builder a seller
publishes through — `alkahest_option_builder` and
`build_ready_bare_metal_hosted_options` — so a fixture cannot advertise
something no seller could. The command under test is the real
`buy_bare_metal`; only the registry client, identity and negotiation transport
are controlled.

The negative cases run through the real acceptance callback the command hands
to `negotiate_with_seller`, which is where `core_buyer` delegates the
`params`/`conditions` equality it would otherwise perform itself.
"""

from __future__ import annotations

import base64
import contextlib
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from arkhai_bare_metal import (
    BareMetalHostedPublicationPolicy,
    BareMetalListing,
    build_ready_bare_metal_hosted_options,
)
from arkhai_bare_metal_buyer import cli as buy_cli
from arkhai_bare_metal_buyer.settlement_composition import (
    ALKAHEST_MECHANISM,
    HOSTED_MECHANISM,
    BareMetalBuyerMechanismError,
)
from market_alkahest.settlement_config import (
    AlkahestSettlementConfig,
    alkahest_option_builder,
)
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_settlement_runtime import MechanismReadiness

CHAIN = "base_sepolia"   # bundled deployed addresses; resolves offline
SELLER_PAYOUT = "0x00000000000000000000000000000000000000cc"
TOKEN = "0x00000000000000000000000000000000000000aa"
MACHINE_ID = "fixture-node"
PHYSICAL_HOST_ID = "fixture-physical-host-id"
DURATION_SECONDS = 900
ESCROW_TTL_SECONDS = 3600
# The negotiated absolute total for this rental: the option advertises 1000 per
# hour and the negotiation scales that by the rental's unit count (900s = 0.25h).
# The advertised rate is not the total for any rental that is not one hour.
HOURLY_RATE = 1000
AGREED_AMOUNT = 250

NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)
OFFER_EXPIRES = datetime(2099, 1, 1, 2, tzinfo=timezone.utc)
FUNDING_DEADLINE = datetime(2099, 1, 1, 1, tzinfo=timezone.utc)
FULFILLMENT_DEADLINE = datetime(2099, 1, 1, 3, tzinfo=timezone.utc)

# A structurally valid ed25519 public key over a constant body. Obviously
# synthetic: no private counterpart exists for it.
_ED25519_BLOB = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(32)
FIXTURE_SSH_PUBLIC_KEY = (
    "ssh-ed25519 " + base64.b64encode(_ED25519_BLOB).decode() + " buyer@fixture"
)

def _escrow_address() -> str:
    from market_alkahest.alkahest import get_erc20_escrow_obligation_default

    return get_erc20_escrow_obligation_default(CHAIN)


ACCEPTED_ESCROW = {
    "chain_name": CHAIN,
    "escrow_address": _escrow_address(),
    "literal_fields": {"token": TOKEN},
    "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
}
def _offer() -> dict[str, Any]:
    return {
        "kind": "bare_metal.v1",
        "virtualization_type": "bare_metal",
        "machine_id": MACHINE_ID,
        "physical_host_id": PHYSICAL_HOST_ID,
        "access_methods": ["ssh"],
        "capabilities": {"units": 1},
        "accepted_escrows": [ACCEPTED_ESCROW],
    }


def _alkahest_option() -> dict[str, Any]:
    """The option a seller publishes, from the mechanism's own builder."""
    built = alkahest_option_builder(
        AlkahestSettlementConfig(enabled=True),
        MechanismReadiness(
            mechanism=ALKAHEST_MECHANISM, configured=True, enabled=True, ready=True
        ),
        {"accepted_escrows": [ACCEPTED_ESCROW]},
        "seller",
    )
    return dict(built["settlement_options"][0])


def _hosted_base(profile: str = "card.v1") -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=100)]
    params = {
        "authority_id": "authority",
        "account_ref": "seller-account-ref",
        "country": "US",
        "environment": "test",
        "claimant_principal": {"scheme": "ed25519", "identifier": "seller"},
        "funds_flow": "separate_charges_transfers",
        "funding_profile": profile,
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "1" * 64,
        "condition": {"kind": "portable-remote.v1", "identifier": "lease-ready"},
    }
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=HOSTED_MECHANISM, asset="usd", rates=rates, params=params
        ),
        mechanism=HOSTED_MECHANISM,
        asset="usd",
        rates=rates,
        params=params,
    )


def _hosted_option() -> dict[str, Any]:
    """The hosted option a seller publishes, from the domain's own builder.

    Its `derivation_key` binds the trusted facts, so a hand-written fixture is
    refused by the hosted contract. Building it here is what lets the hosted
    rail be driven through `buy` rather than asserted about in isolation.
    """
    listing = BareMetalListing(
        machine_id=MACHINE_ID,
        physical_host_id=PHYSICAL_HOST_ID,
        access_methods=["ssh"],
    )
    result = build_ready_bare_metal_hosted_options(
        candidate={
            "derivation_key": "fixture-site:fixture-resource",
            "site_id": "fixture-site",
            "projection_revision": 1,
            "projection_digest": "generation-1",
            "physical_resource_id": "fixture-resource",
            "machine_id": MACHINE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "pool_id": "fixture-pool",
            "listing": listing,
        },
        base_hosted_options=[_hosted_base()],
        policy=BareMetalHostedPublicationPolicy(),
        offer_expires_at=OFFER_EXPIRES,
        funding_deadlines={"card.v1": FUNDING_DEADLINE},
        fulfillment_deadline=FULFILLMENT_DEADLINE,
        now=NOW,
    )
    return result.settlement_options[0].model_dump(mode="json")


def _canonical_plan() -> dict[str, Any]:
    """Exactly what the seller materializes from the buyer's proposal.

    Derived with the shared codec rather than written out, so a fixture cannot
    quietly disagree with what the acceptance check re-derives.
    """
    from arkhai_bare_metal_buyer.settlement_composition import bare_metal_escrow_proposal
    from market_alkahest.plans import materialize_settlement_plan_from_proposal

    proposal = bare_metal_escrow_proposal(
        listing=_offer(),
        option=_alkahest_option(),
        expiration_unix=int(time.time()) + ESCROW_TTL_SECONDS,
    )
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=SELLER_PAYOUT,
        agreed_amount=AGREED_AMOUNT,
        duration_seconds=DURATION_SECONDS,
        addr_config_path=None,
    )
    return plan.model_dump(mode="json")


def _listing(options: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        offer=_offer(),
        settlement_options=options,
        storefront_url="http://fixture-storefront:8000",
        publisher_id="fixture-publisher",
        publisher_principals=SimpleNamespace(
            identities=[],
            model_dump=lambda mode=None: {"identities": []},
        ),
    )


@pytest.fixture()
def world(monkeypatch, tmp_path):
    key_file = tmp_path / "buyer_key.pub"
    key_file.write_text(FIXTURE_SSH_PUBLIC_KEY + "\n")

    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        buy_cli,
        "load_bare_metal_buyer_config",
        lambda config: SimpleNamespace(
            registry_url="http://fixture-registry:8080",
            registry_authority="registry-fixture",
            default_max_rounds=1,
        ),
    )
    monkeypatch.setattr(
        buy_cli,
        "fresh_identity",
        lambda: SimpleNamespace(
            profile_id="fixture-profile",
            principal=SimpleNamespace(
                model_dump=lambda mode=None: {
                    "scheme": "ed25519",
                    "identifier": "fixture-buyer",
                }
            ),
            signer=object(),
        ),
    )

    def _negotiate(**kwargs: Any) -> Any:
        captured["negotiate"] = kwargs
        validator = kwargs.get("validate_advertised_plan")
        plan = captured.get("plan")
        if validator is not None and plan is not None:
            validator(plan)
        return SimpleNamespace(
            status="exited",
            reason="fixture stops before acceptance",
            negotiation_id=None,
            to_dict=lambda: {"status": "exited"},
        )

    # The buyer must have the chain configured to propose an escrow on it; the
    # bundled address set is used, as an operator with no override file would.
    from market_config.config_loader import ChainConfig

    monkeypatch.setattr(
        buy_cli,
        "resolve_buyer_chain",
        lambda chain_name: ChainConfig(
            name=chain_name,
            rpc_url="http://127.0.0.1:1",
            chain_id=84532,
            alkahest_address_config_path=None,
        ),
    )
    monkeypatch.setattr(buy_cli, "negotiate_with_seller", _negotiate)
    monkeypatch.setattr(
        buy_cli.RunLog,
        "start",
        classmethod(
            lambda cls, **kwargs: SimpleNamespace(
                run_id="fixture-run",
                event=lambda *a, **k: None,
                end=lambda *a, **k: None,
            )
        ),
    )

    def _set_listing(options: list[dict[str, Any]]) -> None:
        listing = _listing(options)

        @contextlib.contextmanager
        def _client(*_args: Any, **_kwargs: Any):
            yield SimpleNamespace(get_listing=lambda listing_id: listing)

        monkeypatch.setattr(buy_cli, "registry_client", _client)

    return SimpleNamespace(
        captured=captured, key_file=key_file, set_listing=_set_listing
    )


def _buy(world, option_id: str) -> None:
    buy_cli.buy_bare_metal(
        "fixture-listing",
        option_id=option_id,
        ssh_public_key_file=str(world.key_file),
        duration_seconds=DURATION_SECONDS,
        escrow_expiration_seconds=ESCROW_TTL_SECONDS,
        config=None,
    )


def _selection(world) -> Any:
    return world.captured["negotiate"]["settlement_selection"]


# --------------------------------------------------------------------------
# Rail selection
# --------------------------------------------------------------------------


def test_a_published_alkahest_option_reaches_negotiation(world) -> None:
    option = _alkahest_option()
    world.set_listing([option])

    before = int(time.time())
    _buy(world, option["option_id"])
    after = int(time.time())

    selection = _selection(world)
    assert selection.mechanism == ALKAHEST_MECHANISM
    assert selection.option_id == option["option_id"]
    # The expiry is the buyer's own instant, not anything the listing carried.
    assert before + ESCROW_TTL_SECONDS <= selection.expiration_unix
    assert selection.expiration_unix <= after + ESCROW_TTL_SECONDS


def test_a_published_hosted_option_still_reaches_negotiation(world) -> None:
    """The Stripe rail must not regress while the crypto rail is added."""
    option = _hosted_option()
    world.set_listing([option])

    _buy(world, option["option_id"])

    selection = _selection(world)
    assert selection.mechanism == HOSTED_MECHANISM
    assert selection.expiration_unix == int(FUNDING_DEADLINE.timestamp())


def test_option_id_decides_the_rail_when_both_are_published(world) -> None:
    alkahest, hosted = _alkahest_option(), _hosted_option()
    world.set_listing([alkahest, hosted])

    _buy(world, alkahest["option_id"])
    assert _selection(world).mechanism == ALKAHEST_MECHANISM

    _buy(world, hosted["option_id"])
    assert _selection(world).mechanism == HOSTED_MECHANISM


def test_an_unsupported_mechanism_is_refused_by_name(world) -> None:
    option = dict(_alkahest_option())
    params = dict(option["params"])
    option = {
        **option,
        "mechanism": "barter.v1",
        "option_id": derive_settlement_option_id(
            mechanism="barter.v1",
            asset=option["asset"],
            rates=[RateValue.model_validate(r) for r in option["rates"]],
            params=params,
        ),
    }
    world.set_listing([option])

    with pytest.raises(typer.BadParameter) as exc:
        _buy(world, option["option_id"])

    assert "barter.v1" in str(exc.value)


# --------------------------------------------------------------------------
# The acceptance callback, through the real command
# --------------------------------------------------------------------------


def _mutated(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """The canonical plan with one nested field replaced."""
    plan = _canonical_plan()
    target: Any = plan["obligations"][0]
    for key in path[:-1]:
        target = target[key]
    if value is _REMOVE:
        target.pop(path[-1], None)
    else:
        target[path[-1]] = value
    return plan


_REMOVE = object()


def _buy_with_plan(world, plan: dict[str, Any]) -> None:
    option = _alkahest_option()
    world.set_listing([option])
    world.captured["plan"] = plan
    _buy(world, option["option_id"])


def test_a_canonically_materialized_plan_is_accepted(world) -> None:
    _buy_with_plan(world, _canonical_plan())

    assert _selection(world).mechanism == ALKAHEST_MECHANISM


@pytest.mark.parametrize(
    ("path", "value", "substitution"),
    [
        (("params", "chain_name"), "ethereum_sepolia", "settles on another chain"),
        (
            ("params", "escrow_contract"),
            "0x00000000000000000000000000000000000000ff",
            "names another escrow contract",
        ),
        # The three below are NESTED inside obligation_data, which the buyer
        # funds verbatim. A field-by-field check of the top-level obligation
        # passed every one of them.
        (
            ("params", "obligation_data", "amount"),
            "999999",
            "raises the amount actually escrowed",
        ),
        (
            ("params", "obligation_data", "token"),
            "0x00000000000000000000000000000000000000ee",
            "funds another token",
        ),
        (
            ("params", "obligation_data", "arbiter"),
            "0x00000000000000000000000000000000000000dd",
            "substitutes the arbiter that releases the funds",
        ),
        (
            ("params", "obligation_data"),
            {"token": TOKEN, "amount": "1000"},
            "drops the arbiter and demand entirely",
        ),
        (("params", "obligation_data"), _REMOVE, "carries no escrow data at all"),
        (("conditions",), [{"arbiter": "0x00", "demand_data": {}}], "adds a condition"),
    ],
)
def test_a_substituted_plan_is_refused(world, path, value, substitution) -> None:
    """Each case is a substitution the buyer would otherwise fund.

    `core_buyer` delegates `params`/`conditions` equality to this callback, and
    the nested cases are the ones an enumerated field list missed.
    """
    with pytest.raises(BareMetalBuyerMechanismError):
        _buy_with_plan(world, _mutated(path, value))


def test_the_payee_is_pinned_when_the_seller_advertises_it(world) -> None:
    """A seller that advertised where it is paid may not then be paid elsewhere."""
    from arkhai_bare_metal_buyer.settlement_composition import (
        bare_metal_escrow_proposal,
        validate_accepted_alkahest_plan,
    )

    proposal = bare_metal_escrow_proposal(
        listing=_offer(),
        option=_alkahest_option(),
        expiration_unix=int(time.time()) + ESCROW_TTL_SECONDS,
    )
    substituted = _mutated(
        ("params", "obligation_data", "demand"), "0x" + "00" * 31 + "ff"
    )

    with pytest.raises(BareMetalBuyerMechanismError):
        validate_accepted_alkahest_plan(
            plan=substituted,
            proposal=proposal,
            duration_seconds=DURATION_SECONDS,
            seller_payout_address=SELLER_PAYOUT,
        )


def test_the_pinned_payee_is_read_out_of_the_encoded_demand(world) -> None:
    """The payee is decoded with the arbiter's codec, not guessed.

    Without this case the refusal above would pass even if the demand could
    never be decoded at all: an unreadable payee also fails the pin.
    """
    from arkhai_bare_metal_buyer.settlement_composition import (
        bare_metal_escrow_proposal,
        validate_accepted_alkahest_plan,
    )
    from market_alkahest.plans import decode_accepted_alkahest_obligation
    from market_core.schemas import SettlementPlan

    proposal = bare_metal_escrow_proposal(
        listing=_offer(),
        option=_alkahest_option(),
        expiration_unix=int(time.time()) + ESCROW_TTL_SECONDS,
    )
    canonical = _canonical_plan()
    obligation = SettlementPlan.model_validate(canonical).obligations[0]

    assert obligation.params["obligation_data"].get("recipient") is None, (
        "this plan carries the payee only as an encoded demand; if that changes "
        "the decode below is no longer what the pin relies on"
    )
    read_back = decode_accepted_alkahest_obligation(obligation).payout_address
    assert (read_back or "").lower() == SELLER_PAYOUT.lower()

    validate_accepted_alkahest_plan(
        plan=canonical,
        proposal=proposal,
        duration_seconds=DURATION_SECONDS,
        seller_payout_address=SELLER_PAYOUT,
    )


def test_an_unadvertised_payee_is_the_sellers_own_choice(world) -> None:
    """A documented limit, asserted so it is not mistaken for a check.

    The advertised escrow entry carries no recipient, so nothing in the listing
    says where the seller will be paid. The buyer re-derives the whole
    obligation from whatever payee the acceptance names, which catches every
    other substitution but cannot contradict the payee itself.
    """
    from market_alkahest.schemas import accepted_recipient_address

    proposal_recipient = accepted_recipient_address(ACCEPTED_ESCROW)

    assert proposal_recipient is None, (
        "this fixture advertises no payee; if that changes, the pin above "
        "applies and this limitation no longer holds"
    )

    _buy_with_plan(
        world, _mutated(("params", "obligation_data", "demand"), "0x" + "00" * 31 + "ff")
    )
    assert _selection(world).mechanism == ALKAHEST_MECHANISM


# --------------------------------------------------------------------------
# The negotiated total, through the universal acceptance validator
# --------------------------------------------------------------------------


def _fixture_identity(seed: int) -> Any:
    """A structurally valid ed25519 principal. Obviously synthetic."""
    from market_identity import Identity, IdentityScheme

    return Identity(
        scheme=IdentityScheme.ED25519,
        identifier=base64.urlsafe_b64encode(bytes([seed]) * 32)
        .rstrip(b"=")
        .decode(),
    )


def _accepted_plan(amount: int, *, nested_amount: int | None = None) -> Any:
    """What the seller returns: the canonical plan, bound to both principals."""
    from market_core.schemas import SettlementPlan

    plan = SettlementPlan.model_validate(_canonical_plan())
    obligation = plan.obligations[0]
    if nested_amount is not None:
        params = dict(obligation.params or {})
        obligation_data = dict(params["obligation_data"])
        obligation_data["amount"] = str(nested_amount)
        params["obligation_data"] = obligation_data
        obligation = obligation.model_copy(update={"params": params})
    obligation = obligation.model_copy(
        update={
            "amount": amount,
            "payer_principal": _fixture_identity(1).model_dump(mode="json"),
            "claimant_principal": _fixture_identity(2).model_dump(mode="json"),
        }
    )
    return plan.model_copy(
        update={
            "obligations": [obligation],
            "buyer_principal": _fixture_identity(1).model_dump(mode="json"),
            "seller_principal": _fixture_identity(2).model_dump(mode="json"),
        }
    )


def _accept(plan: Any, *, agreed_amount: int) -> None:
    """Run the real universal acceptance validator over an accepted reply.

    This is the seam the buyer actually validates through: it enforces the
    negotiated total itself and then delegates the mechanism-specific
    `params`/`conditions` equality to the domain callback under test.
    """
    from core_buyer.negotiation_client import _validate_settlement_acceptance
    from market_core.schemas import SettlementSelection
    from market_identity import TrustedIdentitySet

    from arkhai_bare_metal_buyer.settlement_composition import (
        bare_metal_escrow_proposal,
        validate_accepted_alkahest_plan,
    )

    option = _alkahest_option()
    proposal = bare_metal_escrow_proposal(
        listing=_offer(),
        option=option,
        expiration_unix=plan.obligations[0].expiration_unix,
    )
    selection = SettlementSelection(
        mechanism=ALKAHEST_MECHANISM,
        option_id=option["option_id"],
        expiration_unix=plan.obligations[0].expiration_unix,
    )
    buyer = _fixture_identity(1)
    seller = _fixture_identity(2)
    _validate_settlement_acceptance(
        reply={
            "buyer_principal": buyer.model_dump(mode="json"),
            "seller_principal": seller.model_dump(mode="json"),
        },
        selection=selection,
        plan=plan,
        expected_selection=selection,
        advertised_option=SettlementOption.model_validate(option),
        agreed_amount=agreed_amount,
        expected_plan=None,
        buyer_principal=buyer,
        trusted_seller_principals=TrustedIdentitySet(identities=(buyer, seller)),
        validate_advertised_plan=lambda accepted: validate_accepted_alkahest_plan(
            plan=accepted,
            proposal=proposal,
            duration_seconds=DURATION_SECONDS,
        ),
    )


def test_a_fractional_hour_rental_accepts_its_negotiated_total() -> None:
    """900 seconds of a 1000/hour option is 250, not 1000.

    Validating against the advertised hourly rate refused every rental that was
    not exactly one hour, before anything was funded.
    """
    _accept(_accepted_plan(AGREED_AMOUNT), agreed_amount=AGREED_AMOUNT)


def test_the_hourly_rate_is_not_accepted_as_the_total() -> None:
    """The rate charged for a full hour is a substitution on a 15-minute lease."""
    with pytest.raises(RuntimeError, match="amount"):
        _accept(_accepted_plan(HOURLY_RATE), agreed_amount=AGREED_AMOUNT)


def test_a_nested_amount_substitution_is_still_refused_at_the_real_total() -> None:
    """The buyer funds `obligation_data`, so its amount must be the total too."""
    with pytest.raises(BareMetalBuyerMechanismError):
        _accept(
            _accepted_plan(AGREED_AMOUNT, nested_amount=HOURLY_RATE),
            agreed_amount=AGREED_AMOUNT,
        )


def test_buy_hands_negotiation_the_rental_unit_count_and_advertised_rate(
    world,
) -> None:
    """The total the validator enforces comes from these two inputs.

    `negotiate_with_seller` scales the per-unit price by the unit count; if the
    command passed hours as seconds, or the rate as a total, the negotiated
    amount above would not be the one the seller is asked to accept.
    """
    option = _alkahest_option()
    world.set_listing([option])

    _buy(world, option["option_id"])

    negotiated = world.captured["negotiate"]
    assert negotiated["unit_count"] == DURATION_SECONDS / 3600
    assert negotiated["initial_price"] == float(HOURLY_RATE)
    assert negotiated["max_price"] == float(HOURLY_RATE)
    assert int(round(negotiated["initial_price"] * negotiated["unit_count"])) == (
        AGREED_AMOUNT
    )
