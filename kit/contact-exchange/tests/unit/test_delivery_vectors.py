"""The shared data trace binds JCS, policy identity, paths and signed resources."""

import json
from importlib.resources import files

from market_core.schemas import derive_settlement_option_id
from market_identity import (
    EMPTY_BODY,
    Identity,
    TrustedIdentitySet,
    canonical_body_hash,
    canonical_json,
    verify_request,
    verify_response,
)


def test_shared_wire_trace_and_substitution_refusals():
    trace = json.loads(
        files("market_contact_exchange.fixtures")
        .joinpath("delivery_vectors.json")
        .read_text()
    )
    for option in trace["options"]:
        assert (
            derive_settlement_option_id(
                **{k: option[k] for k in ("mechanism", "asset", "rates", "params")}
            )
            == option["option_id"]
        )
    assert trace["options"][0]["option_id"] != trace["options"][1]["option_id"]
    assert "delivery_policy" not in trace["options"][0]["params"]
    for row in trace["requests"]:
        signed = row["signed_request"]
        body = row["body"] if row["body"] is not None else EMPTY_BODY
        assert canonical_body_hash(body) == signed["body_hash"]
        assert (canonical_json(body).hex() if row["body"] is not None else "") == row[
            "canonical_body_utf8_hex"
        ]
        context = dict(
            now=1900000000,
            max_skew=0,
            expected_role="buyer",
            expected_method=signed["method"],
            expected_operation=signed["operation"],
            expected_resource=signed["resource"],
            expected_principals=TrustedIdentitySet(
                identities=(Identity.model_validate(signed["principal"]),)
            ),
            body=body,
        )
        verified = verify_request(signed, **context)
        assert verified.dispatch_allowed
        assert verify_request(
            signed, **context, existing_replay=verified.reservation
        ).verified
        for changed in (
            {"expected_resource": signed["resource"] + "-other"},
            {"expected_method": "DELETE"},
            {
                "expected_operation": "introduction_finalization_cancel"
                if signed["operation"] != "introduction_finalization_cancel"
                else "introduction_finalization_read"
            },
        ):
            assert not verify_request(signed, **{**context, **changed}).verified
        response = row["signed_response"]
        response_context = {
            **context,
            "expected_role": "seller",
            "expected_principals": TrustedIdentitySet(
                identities=(Identity.model_validate(response["principal"]),)
            ),
            "expected_request_id": signed["request_id"],
            "body": row["response_body"],
        }
        assert verify_response(response, **response_context).verified
        for changed in (
            {"expected_resource": signed["resource"] + "-other"},
            {"expected_method": "DELETE"},
            {"expected_request_id": "other-request"},
        ):
            assert not verify_response(
                response, **{**response_context, **changed}
            ).verified
        assert not verify_response(
            {**response, "status": response["status"] + 1}, **response_context
        ).verified
