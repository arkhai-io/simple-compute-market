"""Compute policy consumes supplied facts without interpreting opaque accounts."""

from types import SimpleNamespace

import pytest

from arkhai_compute.end_classification import (
    payment_actor, resolve_site_corrections, site_classification,
)


def test_shared_journal_matching_and_pending_selection_preserve_controlling_failure():
    event = SimpleNamespace(event_id="echo", effective_at=100, reason="command", caller="seller",
                            cause="termination", source_state="active", deadline_phase=None,
                            claimed_deadline=None)
    failure = SimpleNamespace(kind="provisioning_failure", evidence_refs=["failure-proof"])
    requests = [SimpleNamespace(source_ref="failure", source="fulfillment_failure", ended_at=100),
                SimpleNamespace(source_ref="site-event:echo", source="lease_ended", ended_at=100)]
    classes = {"failure": failure, "site-event:echo": None}

    def classify(event):
        return site_classification(
            event, seller="seller", term_end=200, available=True,
            intents=[SimpleNamespace(intent_ref="command", kind="terminate", payload={"at": 100})],
            requests=requests, classifications=classes, termination_ref="command",
        )

    corrections = list(resolve_site_corrections(
        requests, classifications=classes, report_for=lambda _: event, classify=classify,
    ))
    assert len(corrections) == 1
    request, result = corrections[0]
    assert request.source_ref == "site-event:echo"
    assert result.kind == "provisioning_failure"
    assert result.controlling_source_ref == "failure"
    assert result.evidence_refs == ["site-event:echo", "failure", "failure-proof"]
    classes["site-event:echo"] = failure
    assert not list(resolve_site_corrections(
        requests, classifications=classes, report_for=lambda _: pytest.fail("resolved report reloaded"),
        classify=classify,
    ))


def test_payment_actor_matches_only_accepted_opaque_accounts():
    buyer, seller, authority = object(), object(), object()
    args = dict(payer_account="opaque payer", payee_account="opaque payee", buyer=buyer, seller=seller,
                authority_account="opaque authority", authority=authority)
    assert payment_actor("opaque payer", **args) is buyer
    assert payment_actor("opaque payee", **args) is seller
    assert payment_actor("terms", **args) is seller
    assert payment_actor("opaque authority", **args) is authority
    with pytest.raises(ValueError, match="unrecognized payment actor"):
        payment_actor("ed25519:looks-like-an-identity", **args)
