from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alkahest_py import StringObligationData

from market_alkahest.fulfillment import AlkahestStringFulfillmentPublisher


SELLER = "0x" + "22" * 20
ESCROW = "0x" + "33" * 32
FULFILLMENT = "0x" + "44" * 32
EVIDENCE = '{"kind":"bare_metal.alkahest-lease-ready-evidence.v1"}'


def _publisher(*, fetched=None):
    obligation = SimpleNamespace(
        do_obligation=AsyncMock(return_value=FULFILLMENT),
        get_obligation=AsyncMock(return_value=fetched),
    )
    return AlkahestStringFulfillmentPublisher(
        client=SimpleNamespace(string_obligation=obligation),
        publisher_address=SELLER,
    ), obligation


@pytest.mark.asyncio
async def test_submit_and_confirm_exact_string_obligation() -> None:
    fetched = {
        "attestation": SimpleNamespace(
            uid=FULFILLMENT,
            ref_uid=ESCROW,
            recipient=SELLER.upper().replace("0X", "0x"),
            revocation_time=0,
        ),
        "data": SimpleNamespace(item=EVIDENCE),
    }
    publisher, obligation = _publisher(fetched=fetched)

    uid = await publisher.submit_fulfillment(
        condition_anchor=ESCROW,
        evidence=EVIDENCE,
    )
    confirmed = await publisher.confirm_fulfillment(
        fulfillment_uid=uid,
        condition_anchor=ESCROW,
        evidence=EVIDENCE,
    )

    assert uid == FULFILLMENT
    assert confirmed == FULFILLMENT
    obligation.do_obligation.assert_awaited_once_with(EVIDENCE, ESCROW)
    obligation.get_obligation.assert_awaited_once_with(FULFILLMENT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uid", "0x" + "55" * 32),
        ("ref_uid", "0x" + "66" * 32),
        ("recipient", "0x" + "77" * 20),
        ("revocation_time", 1),
    ],
)
async def test_confirmation_rejects_changed_attestation_envelope(
    field: str,
    value: object,
) -> None:
    envelope = {
        "uid": FULFILLMENT,
        "ref_uid": ESCROW,
        "recipient": SELLER,
        "revocation_time": 0,
    }
    envelope[field] = value
    publisher, _ = _publisher(
        fetched={
            "attestation": SimpleNamespace(**envelope),
            "data": SimpleNamespace(item=EVIDENCE),
        }
    )

    with pytest.raises(ValueError, match="fulfillment attestation"):
        await publisher.confirm_fulfillment(
            fulfillment_uid=FULFILLMENT,
            condition_anchor=ESCROW,
            evidence=EVIDENCE,
        )


@pytest.mark.asyncio
async def test_confirmation_rejects_changed_evidence() -> None:
    publisher, _ = _publisher(
        fetched={
            "attestation": SimpleNamespace(
                uid=FULFILLMENT,
                ref_uid=ESCROW,
                recipient=SELLER,
                revocation_time=0,
            ),
            "data": SimpleNamespace(item="different"),
        }
    )

    with pytest.raises(ValueError, match="evidence does not match"):
        await publisher.confirm_fulfillment(
            fulfillment_uid=FULFILLMENT,
            condition_anchor=ESCROW,
            evidence=EVIDENCE,
        )


def test_constructor_rejects_non_address_publisher() -> None:
    with pytest.raises(ValueError, match="publisher_address"):
        AlkahestStringFulfillmentPublisher(
            client=object(),
            publisher_address="seller",
        )


def test_evidence_round_trips_through_installed_string_obligation_codec() -> None:
    encoded = StringObligationData(EVIDENCE).encode_self()

    decoded = StringObligationData.decode(encoded)

    assert decoded.item == EVIDENCE
