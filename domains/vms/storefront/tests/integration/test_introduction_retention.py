"""Introduction retention on the VM storefront, through its typed clients.

A storefront composing contact exchange discloses its retention window before a
buyer hands anything over, lets an operator delete one introduction's payloads,
and runs the retention sweep as a lifecycle loop an operator can preview and
step. Every check goes through the client a deployed caller uses: the
storefront client for health, administration, and lifecycle; the production
buyer's ``IntroductionTransport`` for the reveal.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from core_buyer.introductions import IntroductionPayloadsDeleted
from market_contact_exchange import (
    IntroductionAdminClient,
    IntroductionPayloadsDeletedError,
    format_introduction_timestamp,
)

from tests.introduction_deals import (
    BUYER_CONTACT,
    CONTACT_PUBLISHABLE,
    accept_introduction,
    introduction_transport,
    offer_introduction,
    publish,
)
from tests.loopback import serving
from tests.publication_app import SITE, SITE_CONTACTS, pool, publication_app

pytestmark = pytest.mark.asyncio

_DEFAULT_WINDOW_DAYS = 30


def _backdate_reveal(db_path: str, obligation_ref: str, *, days: int) -> None:
    """Make one revealed introduction ``days`` old.

    Service-internal precondition state no API can express: the reveal time is
    the storefront's clock at insert, and the persistence triggers refuse any
    change to it. The fixture steps around them the way a database owner
    repairing data would, and restores them before the storefront reads again.
    """
    conn = sqlite3.connect(db_path)
    try:
        triggers = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='contact_introductions'"
        ).fetchall()
        conn.execute("DROP TRIGGER contact_introductions_redaction_only")
        conn.execute("DROP TRIGGER contact_introductions_keep_unredacted")
        conn.execute(
            "UPDATE contact_introductions SET created_at=? WHERE obligation_ref=?",
            (
                format_introduction_timestamp(
                    datetime.now(timezone.utc) - timedelta(days=days)
                ),
                obligation_ref,
            ),
        )
        for (sql,) in triggers:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
async def world(tmp_path):
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as app:
        app.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(app, SITE, "broker-a")
        yield app


async def test_readiness_discloses_the_window_the_reveal_carries(world) -> None:
    health = await world.client.get_health()
    disclosure = health.disclosures["introduction_retention"]
    assert disclosure["scope"] == "introduction_record"
    assert disclosure["window_seconds"] == _DEFAULT_WINDOW_DAYS * 86400

    listing = (await publish(world))["broker-a"]
    negotiation_id, obligation_ref = await accept_introduction(world, listing)
    with serving(world.app) as base_url:
        revealed = introduction_transport(base_url).start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            contact_payload=dict(BUYER_CONTACT),
        )
    assert revealed["retention"] == disclosure


async def test_operator_deletion_keeps_the_deal_and_stops_every_reveal(world) -> None:
    listing = (await publish(world))["broker-a"]
    negotiation_id, obligation_ref = await accept_introduction(world, listing)
    with serving(world.app) as base_url:
        introduction_transport(base_url).start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            contact_payload=dict(BUYER_CONTACT),
        )
        admin = IntroductionAdminClient(world.client)
        deleted = await admin.delete_introduction_payloads(obligation_ref)
        again = await admin.delete_introduction_payloads(obligation_ref)
        with pytest.raises(IntroductionPayloadsDeleted) as on_read:
            introduction_transport(base_url).read(obligation_ref=obligation_ref)
        with pytest.raises(IntroductionPayloadsDeleted) as on_start:
            introduction_transport(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(BUYER_CONTACT),
            )

    assert deleted.redacted is True
    assert again == deleted.model_copy(update={"redacted": False})
    assert on_read.value.payloads_deleted_at == deleted.payloads_deleted_at
    assert on_start.value.outcome()["revealed"] is False
    # Operator re-delivery reads the durable reveal, so it has nothing to send.
    with pytest.raises(IntroductionPayloadsDeletedError):
        await world.contact_exchange.seller_view(obligation_ref)
    # The deal remains: its obligation record still resolves.
    assert (
        await world.composition.repository.load_settlement_obligation(obligation_ref)
        is not None
    )


async def test_the_retention_sweep_deletes_what_its_preview_named(world) -> None:
    listing = (await publish(world))["broker-a"]
    with serving(world.app) as base_url:
        refs = []
        for _ in range(2):
            negotiation_id, obligation_ref = await accept_introduction(world, listing)
            introduction_transport(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(BUYER_CONTACT),
            )
            refs.append(obligation_ref)
        expired, fresh = refs
        _backdate_reveal(world.db.db_path, expired, days=_DEFAULT_WINDOW_DAYS + 1)

        preview = await world.client.admin_dry_run_lifecycle_cycle("introduction-retention")
        assert preview["eligible"] == [expired]
        assert introduction_transport(base_url).read(obligation_ref=expired)

        stepped = await world.client.admin_run_lifecycle_cycle("introduction-retention")
        assert stepped == {"loop": "introduction_retention", "deleted": 1}
        with pytest.raises(IntroductionPayloadsDeleted):
            introduction_transport(base_url).read(obligation_ref=expired)
        assert (
            introduction_transport(base_url).read(obligation_ref=fresh)[
                "counterparty_contact"
            ]
            == SITE_CONTACTS[SITE]
        )
