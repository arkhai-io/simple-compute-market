"""The request's own checks, from a request shaped as frps sends a `NewProxy`.

The grant's verdicts are the vector's (`test_vector.py`); these tests cover what is
decided before a grant is read, and that the grant is read from the proxy's own
metadata only.
"""

from __future__ import annotations

import json

import pytest

from frp_grant_admission.config import parse_config
from frp_grant_admission.reasons import Reason
from frp_grant_admission.request import MAX_BODY_BYTES, decide_body, decide_request
from tests.frps_request import GRANT, new_proxy
from tests.vector_builder import CONFIGURATION, NOW, PORT, claims, forged, header

CONFIG = parse_config(CONFIGURATION)


def test_a_valid_request_is_admitted_unchanged() -> None:
    decision = decide_request(new_proxy(), CONFIG, NOW)

    assert decision.admitted
    assert decision.answer() == {"reject": False, "unchange": True}
    assert (decision.proxy, decision.proxy_type, decision.remote_port) == (
        "host-1.guest-17",
        "tcp",
        PORT,
    )
    assert decision.grant is not None and decision.grant.verified


def test_a_refusal_answers_with_its_code_and_text() -> None:
    decision = decide_request(new_proxy(proxy_type="stcp"), CONFIG, NOW)

    assert decision.answer() == {
        "reject": True,
        "reject_reason": "proxy_type_not_allowed: only tcp proxies are admitted",
    }


@pytest.mark.parametrize(
    ("request_", "reason"),
    [
        ([], Reason.MALFORMED_REQUEST),
        ({"content": {}}, Reason.MALFORMED_REQUEST),
        ({"op": 7, "content": {}}, Reason.MALFORMED_REQUEST),
        ({"op": "NewProxy"}, Reason.MALFORMED_REQUEST),
        ({"op": "NewProxy", "content": []}, Reason.MALFORMED_REQUEST),
        ({"op": "Login", "content": {}}, Reason.OPERATION_NOT_SUPPORTED),
        ({"op": "CloseProxy", "content": {}}, Reason.OPERATION_NOT_SUPPORTED),
        (new_proxy(proxy_type="stcp"), Reason.PROXY_TYPE_NOT_ALLOWED),
        (new_proxy(proxy_type="TCP"), Reason.PROXY_TYPE_NOT_ALLOWED),
        (new_proxy(proxy_type=None), Reason.PROXY_TYPE_NOT_ALLOWED),
        (new_proxy(group="pool"), Reason.GROUP_NOT_ALLOWED),
        (new_proxy(remote_port=0), Reason.PORT_INVALID),
        (new_proxy(remote_port=65536), Reason.PORT_INVALID),
        (new_proxy(remote_port=str(PORT)), Reason.PORT_INVALID),
        (new_proxy(remote_port=True), Reason.PORT_INVALID),
        (new_proxy(remote_port=None), Reason.PORT_INVALID),
        (new_proxy(metas=None), Reason.GRANT_MISSING),
        (new_proxy(metas={}), Reason.GRANT_MISSING),
        (new_proxy(metas={"grant": ""}), Reason.GRANT_MISSING),
        (new_proxy(metas={"grant": 7}), Reason.GRANT_MALFORMED),
    ],
    ids=lambda value: value.code if isinstance(value, Reason) else None,
)
def test_each_request_refusal(request_: object, reason: Reason) -> None:
    assert decide_request(request_, CONFIG, NOW).reason is reason


def test_an_empty_group_is_no_group() -> None:
    assert decide_request(new_proxy(group=""), CONFIG, NOW).admitted


def test_a_grant_only_in_the_client_wide_metadata_is_missing() -> None:
    request = new_proxy(metas=None, user={"user": "host-1", "metas": {"grant": GRANT}})

    decision = decide_request(request, CONFIG, NOW)

    assert decision.reason is Reason.GRANT_MISSING
    assert decision.grant is None


def test_the_request_checks_run_before_the_grant_is_read() -> None:
    grant = forged(header(), claims())
    decision = decide_request(new_proxy(remote_port=0, metas={"grant": grant}), CONFIG, NOW)

    assert decision.reason is Reason.PORT_INVALID
    assert decision.grant is None


def test_the_grant_is_checked_against_the_requested_port() -> None:
    decision = decide_request(new_proxy(remote_port=PORT + 1), CONFIG, NOW)

    assert decision.reason is Reason.PORT_MISMATCH


def test_a_body_is_decided_from_its_json() -> None:
    assert decide_body(json.dumps(new_proxy()).encode(), CONFIG, NOW).admitted
    assert decide_body(b"not json", CONFIG, NOW).reason is Reason.MALFORMED_REQUEST
    assert decide_body(b"\xff\xfe", CONFIG, NOW).reason is Reason.MALFORMED_REQUEST


def test_a_body_over_64_kib_is_refused_unread() -> None:
    request = new_proxy(proxy_name="x" * MAX_BODY_BYTES)

    assert decide_body(json.dumps(request).encode(), CONFIG, NOW).reason is Reason.MALFORMED_REQUEST
