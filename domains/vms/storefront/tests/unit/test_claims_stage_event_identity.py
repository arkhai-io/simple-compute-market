"""A claims stage event carries the escrow the deal is keyed by.

The claims engine is mechanism-neutral and names only `claim_ref`. Everything
downstream of a VM deal — the lease truncation path, the `stage_events` table's
indexed `escrow_uid` column, any consumer joining a claim to the deal it settles
— holds the escrow uid instead. For alkahest the two are the same value under two
names, and the translation belongs to this domain rather than to the engine.

Proven here rather than end-to-end: an end-to-end scenario asserting on a claims
event is a slow and indirect way to learn that a field is absent, and the one
that did was blocked by an unrelated error before it ever evaluated its filter.
"""

from __future__ import annotations

from typing import Any

import pytest

from market_storefront.services import claims_runtime


@pytest.fixture
def emitted(monkeypatch) -> list[tuple[str, str, dict[str, Any]]]:
    captured: list[tuple[str, str, dict[str, Any]]] = []

    def _capture(stage: str, event: str, **fields: Any) -> None:
        captured.append((stage, event, fields))

    monkeypatch.setattr(claims_runtime, "stage_event", _capture)
    return captured


class TestSubmittedClaimIdentity:
    async def test_submission_carries_both_names_and_they_agree(
        self, emitted, monkeypatch
    ):
        escrow_uid = "0x" + "ab" * 32

        class _Db:
            async def upsert_claim(self, _row):
                return None

        await claims_runtime.submit_claim(
            sqlite_client=_Db(),
            escrow_uid=escrow_uid,
            fulfillment_uid=None,
            negotiation_id="neg-1",
            listing_id="listing-1",
            chain_name="anvil",
        )

        stage, event, fields = emitted[-1]
        assert (stage, event) == ("claims", "claim_submitted")
        assert fields["claim_ref"] == escrow_uid
        assert fields["escrow_uid"] == escrow_uid, (
            "a submitted claim must be correlatable to its deal by the identity "
            "the deal is keyed by, not only by the engine's neutral reference"
        )


class TestTranslationRules:
    def test_alkahest_claim_reference_becomes_the_escrow_identity(self):
        fields = claims_runtime._with_escrow_identity(
            {"claim_ref": "0xdead", "mechanism": claims_runtime.ALKAHEST_MECHANISM}
        )

        assert fields["escrow_uid"] == "0xdead"

    def test_another_mechanism_is_left_alone(self):
        """A different mechanism's claim reference is not an escrow uid.

        Copying it under that name would assert an identity that does not hold,
        and a consumer filtering on `escrow_uid` would match a value that is not
        one.
        """
        fields = claims_runtime._with_escrow_identity(
            {"claim_ref": "ref-1", "mechanism": "some.other.v1"}
        )

        assert "escrow_uid" not in fields

    def test_an_explicit_escrow_identity_is_not_overwritten(self):
        fields = claims_runtime._with_escrow_identity(
            {"claim_ref": "0xdead", "escrow_uid": "0xbeef"}
        )

        assert fields["escrow_uid"] == "0xbeef"

    def test_an_event_without_a_claim_reference_is_unchanged(self):
        fields = claims_runtime._with_escrow_identity({"reason": "expired"})

        assert fields == {"reason": "expired"}
