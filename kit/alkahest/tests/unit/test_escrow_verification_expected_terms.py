"""An accepted obligation is verified including its accepted expiry.

The real verifier runs here; only the escrow codec lookup and the chain read
are substituted. Every address is obviously synthetic development material and
must never be used on a public network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from market_alkahest import escrow_verification
from market_alkahest.escrow_verification import (
    EscrowVerificationError,
    verify_escrow_for_settlement,
)
from market_alkahest.schemas import EscrowProposal

CHAIN = "base_sepolia"
ESCROW_ADDRESS = "0x" + "11" * 20
TOKEN_ADDRESS = "0x" + "aa" * 20
ARBITER_ADDRESS = "0x" + "cc" * 20
SELLER_WALLET = "0x" + "bb" * 20
ESCROW_UID = "0x" + "ab" * 32
DEMAND = "0x" + "dd" * 32
ACCEPTED_AMOUNT = 1000
ACCEPTED_EXPIRY = 2_000_000_000
NOW_UNIX = ACCEPTED_EXPIRY - 7200

ACCEPTED_OBLIGATION_DATA = {
    "arbiter": ARBITER_ADDRESS,
    "demand": DEMAND,
    "token": TOKEN_ADDRESS,
    "amount": str(ACCEPTED_AMOUNT),
}


def _proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name=CHAIN,
        escrow_address=ESCROW_ADDRESS,
        fields={"token": TOKEN_ADDRESS},
        literal_fields={"token": TOKEN_ADDRESS},
        expiration_unix=ACCEPTED_EXPIRY,
    )


def _chain_read(expiration_time: int):
    """One decoded on-chain escrow matching the accepted obligation data."""

    async def get_obligation(_client: Any, _uid: str) -> dict[str, Any]:
        return {
            "attestation": SimpleNamespace(
                revocation_time=0,
                expiration_time=expiration_time,
            ),
            "data": SimpleNamespace(
                arbiter=ARBITER_ADDRESS,
                demand=bytes.fromhex(DEMAND.removeprefix("0x")),
                token=TOKEN_ADDRESS,
                amount=ACCEPTED_AMOUNT,
            ),
        }

    return get_obligation


async def _verify(expiration_time: int) -> int:
    return await verify_escrow_for_settlement(
        escrow_uid=ESCROW_UID,
        seller_wallet=SELLER_WALLET,
        agreed_price=ACCEPTED_AMOUNT,
        agreed_duration_seconds=3600,
        listing={},
        alkahest_client=object(),
        chain_name=CHAIN,
        alkahest_address_config_path=None,
        escrow_proposal=_proposal(),
        expected_obligation_data=ACCEPTED_OBLIGATION_DATA,
        expected_expiration_unix=ACCEPTED_EXPIRY,
        now_unix=NOW_UNIX,
        get_obligation_fn=_chain_read(expiration_time),
    )


@pytest.fixture(autouse=True)
def _codec(monkeypatch):
    monkeypatch.setattr(
        escrow_verification._codecs,
        "get_escrow_codec_for",
        lambda *_args, **_kwargs: SimpleNamespace(
            kind="erc20_escrow_obligation_default",
        ),
    )


async def test_the_accepted_expiry_is_matched_exactly() -> None:
    assert await _verify(ACCEPTED_EXPIRY) == 0


@pytest.mark.parametrize(
    "expiration_time",
    [ACCEPTED_EXPIRY - 1, ACCEPTED_EXPIRY + 1],
    ids=["earlier-but-future", "later"],
)
async def test_a_different_future_expiry_is_refused(expiration_time) -> None:
    # A funded escrow whose reclaim boundary is not the accepted one moves the
    # collect-vs-reclaim deadline in one direction or the other, so matching
    # obligation data alone must not settle it.
    with pytest.raises(EscrowVerificationError) as raised:
        await _verify(expiration_time)

    assert "expiration_time" in str(raised.value)


async def test_expected_obligation_data_requires_its_accepted_expiry() -> None:
    with pytest.raises(EscrowVerificationError):
        await verify_escrow_for_settlement(
            escrow_uid=ESCROW_UID,
            seller_wallet=SELLER_WALLET,
            agreed_price=ACCEPTED_AMOUNT,
            agreed_duration_seconds=3600,
            listing={},
            alkahest_client=object(),
            chain_name=CHAIN,
            alkahest_address_config_path=None,
            escrow_proposal=_proposal(),
            expected_obligation_data=ACCEPTED_OBLIGATION_DATA,
            now_unix=NOW_UNIX,
            get_obligation_fn=_chain_read(ACCEPTED_EXPIRY),
        )


async def test_an_accepted_expiry_without_its_payload_is_refused() -> None:
    # Half the pair would leave the expiry unpinned on the legacy builder path,
    # where any still-future deadline matches.
    with pytest.raises(EscrowVerificationError):
        await verify_escrow_for_settlement(
            escrow_uid=ESCROW_UID,
            seller_wallet=SELLER_WALLET,
            agreed_price=ACCEPTED_AMOUNT,
            agreed_duration_seconds=3600,
            listing={},
            alkahest_client=object(),
            chain_name=CHAIN,
            alkahest_address_config_path=None,
            escrow_proposal=_proposal(),
            expected_expiration_unix=ACCEPTED_EXPIRY,
            build_obligation_data_fn=lambda **_kwargs: dict(
                ACCEPTED_OBLIGATION_DATA
            ),
            now_unix=NOW_UNIX,
            get_obligation_fn=_chain_read(ACCEPTED_EXPIRY + 1),
        )


async def test_expected_obligation_data_requires_the_accepted_proposal() -> None:
    with pytest.raises(EscrowVerificationError):
        await verify_escrow_for_settlement(
            escrow_uid=ESCROW_UID,
            seller_wallet=SELLER_WALLET,
            agreed_price=ACCEPTED_AMOUNT,
            agreed_duration_seconds=3600,
            listing={},
            alkahest_client=object(),
            chain_name=CHAIN,
            alkahest_address_config_path=None,
            expected_obligation_data=ACCEPTED_OBLIGATION_DATA,
            expected_expiration_unix=ACCEPTED_EXPIRY,
            now_unix=NOW_UNIX,
            get_obligation_fn=_chain_read(ACCEPTED_EXPIRY),
        )
