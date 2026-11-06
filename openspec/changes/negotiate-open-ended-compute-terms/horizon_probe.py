"""Replay proposed acceptance horizons, not a hosted rate execution.

All authority identities are deterministic public development fixtures. No
approval, mandate, remote deployment, or provisioned service is created.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from market_core.schemas import PriceBasis, SettlementOption
from market_settlement_runtime.horizon import RateTermTiming, resolve_horizon
from storefront_client import StorefrontClientError

from recurring_publication_probe import ENTRY, MECHANISM, PAYEE, acceptance_snapshot
from market_deal_lifecycle.terms import TermContext


def timing(option):
    return RateTermTiming(900, 300, TermContext(
        mechanism=MECHANISM, has_adapter=True, has_stoppable_part=True,
        dispute_interfaces=frozenset({ENTRY.interface}), authority=ENTRY.requirements,
        supported_partial_periods=frozenset({"charged", "returned"}),
    ))


def billing(option):
    return PriceBasis(unit="per_period", period="PT15M", period_seconds=900)


class ProposedPayments:
    """Accepted-data placeholder, deliberately not an authority/mandate adapter."""

    def settlement_data(self, agreement):
        return SimpleNamespace(to_wire=lambda: {})


class ProposedSellerStage:
    """Preserve domain admission; provide no claimed authority data."""

    def __init__(self, stage):
        self.stage = stage

    def __getattr__(self, name):
        return getattr(self.stage, name)

    def accepted_data(self, agreement, payment_stage):
        return {}


def pure(option):
    instant = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(microseconds=900000)
    base = dict(requested_duration_seconds=None, requested_start_utc=None,
                accepted_at=instant, max_duration_seconds=7201,
                available_until_utc=None, option=SettlementOption.model_validate(option),
                rate_terms={MECHANISM: timing})
    resolved = resolve_horizon(**base)
    assert resolved.duration_seconds == 7201 and resolved.start_utc == "2030-01-01T00:00:00Z"
    assert resolve_horizon(**{**base, "requested_duration_seconds": 2401}).duration_seconds == 2401
    assert resolve_horizon(**{**base, "available_until_utc": "2030-01-01T01:00:01Z"}).duration_seconds == 3601
    assert resolve_horizon(**{**base, "available_until_utc": "2030-01-02T00:00:00.5Z"}).duration_seconds == 7201
    assert resolve_horizon(**{**base, "requested_start_utc": "2030-01-01T01:00:00Z", "requested_duration_seconds": 2100}).duration_seconds == 2100
    cases = (
        ({"requested_duration_seconds": 2399}, "The horizon leaves no runway: minimum duration_seconds is 2400"),
        ({"requested_duration_seconds": 899}, "one whole period"),
        ({"requested_duration_seconds": 7202}, "exceeds listing bound"),
        ({"requested_start_utc": "2030-01-01T00:00:00.1Z"}, "whole seconds"),
        ({"available_until_utc": "2029-01-01T00:00:00Z"}, "expired"),
        ({"max_duration_seconds": None}, "finite listing bound"),
        ({"available_until_utc": "2030-01-01T01:00:00.5Z"}, "state a shorter horizon"),
        ({"option": None}, "reserved duration_seconds is required"),
        ({"rate_terms": {}}, "projection unavailable"),
    )
    for change, expected in cases:
        try:
            resolve_horizon(**{**base, **change})
        except ValueError as exc:
            assert expected in str(exc), (change, str(exc))
        else:
            raise AssertionError(change)
    # Once-only timestamps retain their fractional precision, while both bounds
    # still limit the explicit duration exactly.
    once = resolve_horizon(**{**base, "option": None, "requested_duration_seconds": 3600})
    assert once.start_utc == instant.isoformat().replace("+00:00", "Z")
    print("pure horizons: equal/unrounded/absolute/future start/expiry/fractional/period/runway/unsupported: PASS")


async def exercise(buyer, db, identity, option, mode, preview=None, reserved=None):
    pure(option)
    kind = "compute.v1" if mode == "VM" else "bare_metal.v2"
    async def invoke(duration, *, start=None, chosen=option):
        payload = {"ssh_public_key": "ssh-ed25519 fixture"}
        if duration is not None:
            payload["duration_seconds"] = duration
        if start is not None:
            payload["start_utc"] = start
        if mode != "VM":
            payload["access_method"] = "ssh"
        return await buyer.negotiate_new(
            listing_id=identity, initial_amount=625000,
            provision_terms={"kind": kind, "version": 1, "payload": payload},
            settlement_selection={"option_id": chosen["option_id"], "expiration_unix": 2147483647,
                                  "settlement": {"schema": MECHANISM, "payer_account": PAYEE}},
            selection_only=True,
        )
    for duration, start, expected in (
        (2399, None, "The horizon leaves no runway"),
        (899, None, "one whole period"),
        (7201, None, "listing"),
        (3600, "2030-01-01T00:00:00.1Z", "whole seconds"),
    ):
        before = acceptance_snapshot(db)
        try:
            await invoke(duration, start=start)
        except StorefrontClientError as exc:
            assert expected in str(exc), str(exc)
        else:
            raise AssertionError((duration, start))
        assert acceptance_snapshot(db) == before
    if reserved is not None:
        before = acceptance_snapshot(db)
        try:
            await invoke(None, chosen=reserved)
        except StorefrontClientError as exc:
            assert "reserved duration_seconds is required" in str(exc), str(exc)
        else:
            raise AssertionError("missing reserved duration was accepted")
        assert acceptance_snapshot(db) == before
    for duration, expected in ((None, 7200), (2401, 2401)):
        if preview is not None:
            before = acceptance_snapshot(db)
            result = await preview(identity, option, duration)
            assert acceptance_snapshot(db) == before
        else:
            result = await invoke(duration)
        agreement = result["agreement"]
        assert agreement["duration_seconds"] == expected, result
        assert agreement["settlement"] == option
        assert "." not in agreement["start_utc"]
        assert ("duration_seconds" in agreement["provision_terms"]["payload"]) == (duration is not None)
    print(mode, "valid omitted/shorter horizon artifacts:", "no-write preview" if preview else "signed committed acceptance", "; period/runway/excess/fractional signed refusals without writes: PASS")
