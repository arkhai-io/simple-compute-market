"""Explicit same-identifier refresh of a tracked open bare-metal listing."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from arkhai_bare_metal import storefront_publication
from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    bare_metal_listing_candidates,
    record_derived_bare_metal_listing,
    resolve_refresh_target_derivation_key,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
)
from core_storefront.publication_runner import PublicationPayload
from market_alkahest import AlkahestSettlementConfig, create_alkahest_registration
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_identity import Ed25519Signer
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementPublicationClause,
)
from typer.testing import CliRunner

from arkhai_bare_metal_storefront import publication_cli
from arkhai_bare_metal_storefront.cli import app
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.publication import (
    build_bare_metal_publication_selection,
    run_bare_metal_publication,
)
from arkhai_bare_metal_storefront.server import BARE_METAL_STOREFRONT_REGISTRY
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

# Obviously synthetic fixture values. They must never be used on a public
# network.
_TRACKED_LISTING_ID = "listing-fixture-tracked"
_UNTRACKED_LISTING_ID = "listing-fixture-untracked"
_STOREFRONT_URL = "https://storefront.example"
# Deterministic development-only signing key. It is a fixture value and must
# never be used on a public network.
_SELLER = Ed25519Signer(bytes.fromhex("33" * 32)).identity
_BUYER = Ed25519Signer(bytes.fromhex("44" * 32)).identity

_ORIGINAL_ESCROW = {"chain_name": "base", "token": "fixture-token-a"}
_CHANGED_ESCROW = {"chain_name": "base", "token": "fixture-token-b"}


def _projection() -> TrustedBareMetalProjection:
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        complete=True,
        resources=[
            BareMetalResourceProjection(
                physical_resource_id="resource-1",
                pool_id="pool-1",
                physical_host_id="physical-host-1",
                machine_id="machine-1",
                available=True,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
                capabilities={"gpu_model": "H200"},
            ),
        ],
    )


def _candidate() -> dict:
    (candidate,) = bare_metal_listing_candidates([_projection()])
    return candidate


def _tracked_open_listing(tmp_path) -> str:
    """Create a storefront database holding one tracked open listing."""
    path = str(tmp_path / "storefront.db")
    _write_open_listing(SQLiteClient(path), listing_id=_TRACKED_LISTING_ID)
    record_derived_bare_metal_listing(
        path,
        listing_id=_TRACKED_LISTING_ID,
        candidate=_candidate(),
    )
    return path


def _write_open_listing(
    db: SQLiteClient,
    *,
    listing_id: str,
    physical_resource_id: str | None = None,
) -> None:
    candidate = _candidate()
    now = datetime.now(timezone.utc).isoformat()
    asyncio.run(
        db.upsert_bare_metal_listing(
            listing_id=listing_id,
            status="open",
            created_at=now,
            updated_at=now,
            seller_principal=_SELLER,
            storefront_url=_STOREFRONT_URL,
            listing=candidate["listing"],
            accepted_escrows=[_ORIGINAL_ESCROW],
            settlement_options=[{"option_id": "fixture-option-a"}],
            demands=[],
            site_id=candidate["site_id"],
            pool_id=str(candidate["pool_id"]),
            physical_resource_id=physical_resource_id
            or candidate["physical_resource_id"],
        )
    )


def _local_terms(db_path: str, listing_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT accepted_escrows, settlement_options, status"
            " FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
    finally:
        conn.close()
    return {
        "accepted_escrows": json.loads(row[0]),
        "settlement_options": json.loads(row[1]),
        "status": row[2],
    }


def _run(
    db_path: str,
    *,
    refresh_listing_ids,
    publish_existing_listing,
    skip_ids=None,
    payload=None,
):
    selection = build_bare_metal_publication_selection(
        BARE_METAL_STOREFRONT_REGISTRY,
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=publish_existing_listing,
        refresh_listing_ids=refresh_listing_ids,
    )
    skip_open = not refresh_listing_ids
    if refresh_listing_ids and skip_ids is None:
        skip_ids = set()
    return run_bare_metal_publication(
        selection,
        config=StorefrontPublicationCommandConfig(
            db_path=db_path,
            base_url=_STOREFRONT_URL,
            close_stale=False,
            skip_open=skip_open,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=lambda _source, _candidate, _offer: (
                payload
                if payload is not None
                else ([_CHANGED_ESCROW], [], 7200)
            ),
            publish_offer=lambda *_args, **_kwargs: pytest.fail(
                "a refresh must never create a second listing identity"
            ),
        ),
        skip_ids=skip_ids,
    )


def test_refresh_republishes_the_same_identity_and_matches_local_terms(tmp_path):
    db_path = _tracked_open_listing(tmp_path)
    published = []

    def publish_existing_listing(**values):
        published.append(values)
        return {"status": "published", "listing_id": values["listing_id"]}

    result = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=publish_existing_listing,
    )

    assert result.failed == []
    assert result.published_count == 1
    assert [call["listing_id"] for call in published] == [_TRACKED_LISTING_ID]
    assert published[0]["accepted_escrows"] == [_CHANGED_ESCROW]
    local = _local_terms(db_path, _TRACKED_LISTING_ID)
    assert local["accepted_escrows"] == published[0]["accepted_escrows"]
    assert local["settlement_options"] == published[0]["settlement_options"]
    assert local["status"] == "open"


def test_a_failed_refresh_leaves_local_terms_intact_and_retries_clean(tmp_path):
    db_path = _tracked_open_listing(tmp_path)
    attempts = []

    def failing_publish(**values):
        attempts.append(values["listing_id"])
        raise RuntimeError("registry publication failed: fixture")

    result = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=failing_publish,
    )

    assert result.published == []
    assert result.failed_count == 1
    assert attempts == [_TRACKED_LISTING_ID]
    assert _local_terms(db_path, _TRACKED_LISTING_ID)["accepted_escrows"] == [
        _ORIGINAL_ESCROW
    ]

    def publish_existing_listing(**values):
        return {"status": "published", "listing_id": values["listing_id"]}

    retried = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=publish_existing_listing,
    )

    assert retried.failed == []
    assert retried.published_count == 1
    assert _local_terms(db_path, _TRACKED_LISTING_ID)["accepted_escrows"] == [
        _CHANGED_ESCROW
    ]


def test_the_routine_round_still_skips_a_tracked_open_listing(tmp_path):
    db_path = _tracked_open_listing(tmp_path)

    result = _run(
        db_path,
        refresh_listing_ids=frozenset(),
        publish_existing_listing=lambda **_values: pytest.fail(
            "an open listing must not be republished without an explicit refresh"
        ),
    )

    assert result.published == []
    assert result.failed == []
    assert result.skipped_count == 1
    assert _local_terms(db_path, _TRACKED_LISTING_ID)["accepted_escrows"] == [
        _ORIGINAL_ESCROW
    ]


def test_a_named_refresh_does_not_reach_another_open_listing(tmp_path):
    """The refreshed key is the only one lifted out of the skip set."""
    db_path = _tracked_open_listing(tmp_path)

    result = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=lambda **_values: pytest.fail(
            "a listing outside the narrowed skip set must not be republished"
        ),
        skip_ids={_candidate()["derivation_key"]},
    )

    assert result.published == []
    assert result.skipped_count == 1


@pytest.mark.parametrize("listing_id", [_UNTRACKED_LISTING_ID, "listing-fixture-absent"])
def test_an_unknown_or_untracked_refresh_target_is_refused_before_any_write(
    tmp_path, listing_id
):
    db_path = _tracked_open_listing(tmp_path)
    # A listing row this storefront never derived: open locally, but with no
    # tracked derivation naming it, so a refresh cannot claim it.
    _write_open_listing(
        SQLiteClient(db_path),
        listing_id=_UNTRACKED_LISTING_ID,
        physical_resource_id="resource-2",
    )

    with pytest.raises(ValueError):
        resolve_refresh_target_derivation_key(
            db_path,
            listing_id=listing_id,
            candidates=bare_metal_listing_candidates([_projection()]),
        )

    assert _local_terms(db_path, _TRACKED_LISTING_ID)["accepted_escrows"] == [
        _ORIGINAL_ESCROW
    ]


def test_a_refresh_target_absent_from_available_candidates_is_refused(tmp_path):
    db_path = _tracked_open_listing(tmp_path)

    with pytest.raises(ValueError):
        resolve_refresh_target_derivation_key(
            db_path,
            listing_id=_TRACKED_LISTING_ID,
            candidates=[],
        )


def _contact_composition_payload() -> PublicationPayload:
    """One canonical payload from the real contact settlement composition."""
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "priority": [CONTACT_MECHANISM],
            "contact": {
                "enabled": True,
                "contact_payload": {"telegram": "@fixture_broker"},
                "profiles": {
                    "default": {
                        "channel": "telegram",
                        "terms": "Fixture terms, development only.",
                    }
                },
            },
        },
        resources={"claimant_principal": _SELLER},
    )
    now = datetime.now(timezone.utc)
    return asyncio.run(
        composition.publication_payload(
            candidate=_candidate(),
            clauses=[
                SettlementPublicationClause(
                    mechanism=CONTACT_MECHANISM,
                    asset="introduction",
                    mechanism_input={"profile": "default"},
                )
            ],
            offer_expires_at=now + timedelta(hours=2),
            funding_deadlines={},
            fulfillment_deadline=now + timedelta(hours=3),
            demands=[],
            max_duration_seconds=7200,
        )
    )


def _alkahest_option_payload() -> PublicationPayload:
    """One canonical payload from the real Alkahest publication option builder.

    The builder runs over an already-advertised escrow entry, which is the
    branch that needs no chain client, so both published carriers are the ones
    production generates.
    """
    # Deterministic development-only addresses. They must never be used on a
    # public network.
    entry = {
        "chain_name": "base_sepolia",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": "0x" + "aa" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
    }
    artifacts = create_alkahest_registration().option_builder(
        AlkahestSettlementConfig(enabled=True),
        MechanismReadiness(
            mechanism="alkahest.v1",
            configured=True,
            enabled=True,
            ready=True,
        ),
        {"accepted_escrows": [entry]},
        "seller",
    )
    return PublicationPayload(
        accepted_escrows=(entry,),
        settlement_options=tuple(artifacts["settlement_options"]),
        max_duration_seconds=7200,
    )


@pytest.mark.parametrize(
    "build",
    [_contact_composition_payload, _alkahest_option_payload],
    ids=["contact-composition", "alkahest-option-builder"],
)
def test_a_canonical_payload_refresh_publishes_and_persists_both_carriers(
    tmp_path, build
):
    db_path = _tracked_open_listing(tmp_path)
    payload = build()
    published = []

    def publish_existing_listing(**values):
        published.append(values)
        return {"status": "published", "listing_id": values["listing_id"]}

    result = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=publish_existing_listing,
        payload=payload,
    )

    assert result.failed == []
    assert result.published_count == 1
    (call,) = published
    assert call["listing_id"] == _TRACKED_LISTING_ID
    assert call["accepted_escrows"] == list(payload.accepted_escrows)
    assert call["settlement_options"] == list(payload.settlement_options)
    assert payload.settlement_options != ()
    local = _local_terms(db_path, _TRACKED_LISTING_ID)
    assert local["accepted_escrows"] == list(payload.accepted_escrows)
    assert local["settlement_options"] == list(payload.settlement_options)


def _accepted_agreement(db_path: str) -> None:
    """Record one accepted agreement against the tracked listing."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO negotiation_threads(
              negotiation_id, our_listing_id, status, terminal_state,
              agreed_price, agreed_duration_seconds, agreed_at,
              buyer_scheme, buyer_identifier, seller_scheme, seller_identifier
            )
            VALUES ('negotiation-fixture-1', ?, 'closed', 'success',
                    '100', 3600, '2026-01-01T00:00:00Z', ?, ?, ?, ?)
            """,
            (
                _TRACKED_LISTING_ID,
                _BUYER.scheme.value,
                _BUYER.identifier,
                _SELLER.scheme.value,
                _SELLER.identifier,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _agreement_rows(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM negotiation_threads ORDER BY negotiation_id"
        ).fetchall()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "failure",
    ["ambiguous-registry-success", "local-persistence-failure"],
)
def test_a_refresh_interrupted_after_publication_retries_under_the_same_identity(
    tmp_path, monkeypatch, failure
):
    db_path = _tracked_open_listing(tmp_path)
    _accepted_agreement(db_path)
    agreements = _agreement_rows(db_path)
    payload = _contact_composition_payload()
    attempts = []

    def publish_existing_listing(**values):
        attempts.append(values["listing_id"])
        return {"status": "published", "listing_id": values["listing_id"]}

    if failure == "ambiguous-registry-success":

        def first_publish(**values):
            # The registry accepted this write; the caller never learns it did,
            # so the remote may already advertise the new terms.
            publish_existing_listing(**values)
            raise RuntimeError(
                "connection reset after the registry accepted the write"
            )

    else:
        first_publish = publish_existing_listing

        def refuse_local_write(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(
            storefront_publication, "_write_listing_terms", refuse_local_write
        )

    interrupted = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=first_publish,
        payload=payload,
    )

    assert interrupted.published == []
    assert interrupted.failed_count == 1
    # The interruption happened after the registry accepted the publication,
    # under the original identifier.
    assert attempts == [_TRACKED_LISTING_ID]
    assert _local_terms(db_path, _TRACKED_LISTING_ID)["accepted_escrows"] == [
        _ORIGINAL_ESCROW
    ]
    assert _agreement_rows(db_path) == agreements

    monkeypatch.undo()
    retried = _run(
        db_path,
        refresh_listing_ids=frozenset({_TRACKED_LISTING_ID}),
        publish_existing_listing=publish_existing_listing,
        payload=payload,
    )

    assert retried.failed == []
    assert retried.published_count == 1
    # Exactly two publications, both naming the original identifier, and the
    # new-listing callback would have failed the test if it had been reached.
    assert attempts == [_TRACKED_LISTING_ID, _TRACKED_LISTING_ID]
    local = _local_terms(db_path, _TRACKED_LISTING_ID)
    assert local["settlement_options"] == list(payload.settlement_options)
    assert local["status"] == "open"
    assert _agreement_rows(db_path) == agreements


def test_the_publish_command_forwards_an_explicit_refresh_target(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        publication_cli,
        "run_publication_once",
        lambda **kwargs: captured.update(kwargs)
        or {"closed": [], "published": [], "failed": [], "skipped": []},
    )

    result = CliRunner().invoke(
        app, ["publish", "--refresh-listing-id", _TRACKED_LISTING_ID]
    )

    assert result.exit_code == 0
    assert captured == {"refresh_listing_id": _TRACKED_LISTING_ID}


def test_the_publish_command_reports_a_refused_refresh_target(monkeypatch):
    def refuse(**_kwargs):
        raise ValueError("refresh target is not a tracked bare-metal listing")

    monkeypatch.setattr(publication_cli, "run_publication_once", refuse)

    result = CliRunner().invoke(
        app, ["publish", "--refresh-listing-id", _UNTRACKED_LISTING_ID]
    )

    assert result.exit_code != 0
    assert "not a tracked bare-metal listing" in result.output


def test_the_tracked_open_target_resolves_to_its_derivation_key(tmp_path):
    db_path = _tracked_open_listing(tmp_path)

    assert (
        resolve_refresh_target_derivation_key(
            db_path,
            listing_id=_TRACKED_LISTING_ID,
            candidates=bare_metal_listing_candidates([_projection()]),
        )
        == _candidate()["derivation_key"]
    )
