"""The eligible-reclaim wait retries what can change and answers what cannot."""

from __future__ import annotations

import json

import pytest

from tests.e2e.roles.scenarios.vms.hosted.network import (
    HostedAuthorityRefusal,
    _authority_refusal,
)


def _error(status: int, code: str, *, retryable: bool = False) -> RuntimeError:
    body = json.dumps({"code": code, "message": "refused", "retryable": retryable})
    return RuntimeError(f"POST /x -> authenticated HTTP {status}: {body}")


def test_lost_reservation_is_retryable() -> None:
    code, retryable = _authority_refusal(_error(409, "operation_conflict"))
    assert (code, retryable) == ("operation_conflict", True)


def test_unsupported_reversal_is_not_retryable() -> None:
    code, retryable = _authority_refusal(_error(409, "reversal_unsupported"))
    assert (code, retryable) == ("reversal_unsupported", False)


def test_missing_funding_relation_is_not_retryable() -> None:
    code, retryable = _authority_refusal(_error(503, "funding_relation_missing"))
    assert (code, retryable) == ("funding_relation_missing", False)


def test_authority_retryable_flag_is_honoured() -> None:
    """A code the harness does not enumerate is still retried when the
    authority says the same request may be re-sent."""

    code, retryable = _authority_refusal(_error(503, "provider_busy", retryable=True))
    assert (code, retryable) == ("provider_busy", True)


def test_storefront_detail_is_recorded_when_no_code_survives() -> None:
    """The storefront does not forward the authority's code. Recording its
    detail keeps a refused wait from reporting that it was never refused."""

    body = json.dumps({"detail": "hosted settlement reclaim is temporarily unavailable"})
    code, retryable = _authority_refusal(
        RuntimeError(f"POST /x -> authenticated HTTP 503: {body}")
    )
    assert code is not None and code.startswith("storefront: ")
    # Retryable: the storefront gives nothing to tell a permanent refusal from a
    # lost reservation, so the wait keeps its retry and only gains the text.
    assert retryable is True


def test_unparseable_body_is_not_retryable() -> None:
    assert _authority_refusal(RuntimeError("connection reset")) == (None, False)
    assert _authority_refusal(
        RuntimeError("POST /x -> authenticated HTTP 409: not json")
    ) == (None, False)


class _Reclaimer:
    """The wait under test, with `reclaim` standing in for the authority."""

    def __init__(self, answers: list[object]) -> None:
        self._answers = answers
        self.calls = 0

    def reclaim(self, settlement_ref: str) -> object:
        self.calls += 1
        answer = self._answers[min(self.calls - 1, len(self._answers) - 1)]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _wait(reclaimer: _Reclaimer, monkeypatch: pytest.MonkeyPatch, timeout: str = "180"):
    from tests.e2e.roles.scenarios.vms.hosted import network

    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", timeout)
    monkeypatch.setattr(network.time, "sleep", lambda _seconds: None)
    return network.NetworkMarketplacePort.request_eligible_pretransfer_refund(
        reclaimer, "settlement-1"
    )


def test_retryable_refusal_is_outlasted(monkeypatch: pytest.MonkeyPatch) -> None:
    reclaimer = _Reclaimer([_error(409, "operation_conflict"), "terminal"])
    assert _wait(reclaimer, monkeypatch) == "terminal"
    assert reclaimer.calls == 2


def test_permanent_refusal_stops_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    reclaimer = _Reclaimer([_error(409, "reversal_unsupported")])
    with pytest.raises(HostedAuthorityRefusal) as caught:
        _wait(reclaimer, monkeypatch)
    assert caught.value.code == "reversal_unsupported"
    assert reclaimer.calls == 1


def test_missing_relation_stops_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    reclaimer = _Reclaimer([_error(503, "funding_relation_missing")])
    with pytest.raises(HostedAuthorityRefusal) as caught:
        _wait(reclaimer, monkeypatch)
    assert caught.value.code == "funding_relation_missing"
    assert reclaimer.calls == 1


def test_exhausted_wait_names_its_last_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    reclaimer = _Reclaimer([_error(409, "operation_conflict")])
    with pytest.raises(TimeoutError) as caught:
        _wait(reclaimer, monkeypatch, timeout="0")
    assert "operation_conflict" in str(caught.value)


def test_timeout_without_any_refusal_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    reclaimer = _Reclaimer([RuntimeError("POST /x -> authenticated HTTP 409: not json")])
    with pytest.raises(TimeoutError) as caught:
        _wait(reclaimer, monkeypatch, timeout="0")
    assert "none received" in str(caught.value)


class _Projector:
    """`_wait_public_status` under test, with `_buyer_status` standing in."""

    def __init__(self, statuses: list[dict[str, object]]) -> None:
        self._statuses = statuses
        self.calls = 0

    def _buyer_status(self, settlement_ref: str) -> dict[str, object]:
        self.calls += 1
        return self._statuses[min(self.calls - 1, len(self._statuses) - 1)]


def _public_wait(
    projector: _Projector,
    monkeypatch: pytest.MonkeyPatch,
    terminal: set[str],
    timeout: str = "180",
):
    from tests.e2e.roles.scenarios.vms.hosted import network

    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", timeout)
    monkeypatch.setattr(network.time, "sleep", lambda _seconds: None)
    return network.NetworkMarketplacePort._wait_public_status(
        projector, "settlement-1", terminal
    )


def test_parked_obligation_ends_the_wait_naming_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parked deal waits for a person, so time cannot resolve it."""

    projector = _Projector(
        [{"status": "manual_required", "funding_reason": "reversal_rejected"}]
    )

    with pytest.raises(HostedAuthorityRefusal) as refused:
        _public_wait(projector, monkeypatch, {"reclaimed"})

    assert refused.value.code == "reversal_rejected"
    assert projector.calls == 1


def test_unexplained_parked_state_is_waited_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parked state with no reason is derived from the authority's current
    status and a later poll re-derives it, so a lane passing through one must
    not be failed for it."""

    projector = _Projector(
        [{"status": "manual_required"}, {"status": "reclaimed"}]
    )

    assert _public_wait(projector, monkeypatch, {"reclaimed"})["status"] == "reclaimed"


def test_unexplained_parked_state_that_persists_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projector = _Projector([{"status": "manual_required"}])

    with pytest.raises(HostedAuthorityRefusal) as refused:
        _public_wait(projector, monkeypatch, {"reclaimed"}, timeout="0.05")

    assert refused.value.code == "settlement_parked"


def test_terminal_status_still_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    projector = _Projector([{"status": "pending"}, {"status": "reclaimed"}])

    assert _public_wait(projector, monkeypatch, {"reclaimed"})["status"] == "reclaimed"


def test_non_terminal_status_still_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    projector = _Projector([{"status": "pending"}])

    with pytest.raises(TimeoutError):
        _public_wait(projector, monkeypatch, {"reclaimed"}, timeout="0.01")
