"""Compute-end classification from exact commands, not site arrival order."""

from types import SimpleNamespace

import pytest

from arkhai_compute.end_classification import CommandEnd, classify_site_end


def classify(**changes):
    values = dict(event_id="event", effective_at=100, cause="release", source_state="reserved",
                  caller=None, reason="command", deadline_phase=None, claimed_deadline=None)
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("kind", ["buyer_surrender", "ruling", "provisioning_failure"])
def test_direct_release_echo_keeps_controlling_source_even_for_failure(kind):
    result = classify_site_end(
        classify(), seller="seller", term_end=200, available=False,
        commands=[CommandEnd("command", "terminate", 100, "source", kind, ["proof"])],
        termination_ref="command",
    )
    assert result.kind == kind
    assert result.controlling_source_ref == "source"
    assert result.evidence_refs == ["site-event:event", "source", "proof"]


def test_ambiguity_remains_pending_but_independent_earlier_failure_is_not_an_echo():
    args = dict(seller="seller", term_end=200, available=True, termination_ref="command")
    command = CommandEnd("command", "terminate", 100, "source", "buyer_surrender", ["proof"])
    assert classify_site_end(classify(reason="unresolved", cause="release_failure"), commands=[], **args).kind is None
    assert classify_site_end(classify(effective_at=99, cause="force_release", caller="site", reason="independent failure"), commands=[command], **args).kind == "unentitled_withdrawal"
    assert classify_site_end(classify(reason="command", caller="seller"), commands=[], **args).kind is None


def test_only_exact_truncation_or_agreement_deadline_is_lawful_expiry():
    args = dict(seller="seller", term_end=200, available=True, termination_ref="command")
    event = classify(cause="expiry", reason=None, effective_at=150, deadline_phase="lease", claimed_deadline=150)
    command = CommandEnd("truncate", "truncate", 150, "ruling", "ruling", ["proof"])
    assert classify_site_end(event, commands=[], **args).kind is None
    result = classify_site_end(event, commands=[command], **args)
    assert result.kind == "ruling" and result.controlling_source_ref == "ruling"
    assert classify_site_end(classify(cause="expiry", deadline_phase="lease", claimed_deadline=200, effective_at=200), commands=[], **args).kind == "terms"
    assert classify_site_end(classify(cause="expiry", deadline_phase="reservation", claimed_deadline=100), commands=[], **(args | {"available": False})).kind == "provisioning_failure"
