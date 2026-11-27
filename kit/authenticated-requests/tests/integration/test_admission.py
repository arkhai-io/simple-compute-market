"""Admission in each form: one case per refusal row, and the checks before dispatch.

Library integration: the toy authority's real application, in the middleware and
the dependency form, over a real SQLite database its chain migrated, reached
through httpx's in-process transport with requests signed under the version 3
profile. Raw requests are this library's contract: it has no typed client.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_identity import (
    REQUEST_PROTOCOL,
    ExactRetry,
    MarketRequest,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    principal_text,
    sign_market_request,
    sign_request,
    verify_request_evidence,
)
from fastapi import Depends, FastAPI
from market_identity import Ed25519Signer, Signer
from starlette.exceptions import HTTPException

from market_authenticated_requests import ROUTE_FAILURE_DETAIL, RouteAdmission, install
from tests.integration.support import (
    ROTATED_AUTHORITY_SEED,
    SKEW,
    START,
    Caller,
    Toy,
    World,
    authority_signer,
    make_core,
    make_world,
    migrated_database,
)


def test_a_signed_first_use_is_dispatched_and_answered_signed(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})

        assert response.status_code == 200 and response.json() == {"item": "a", "value": 5}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {"item_set": 1}


def test_a_path_no_route_serves_is_a_signed_404_naming_the_stated_operation(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/nowhere", operation="capacity_reserve", resource="pool-a")

        assert response.status_code == 404
        assert response.json() == {"code": "operation_not_served", "operation": "capacity_reserve"}
        assert caller.verified(response, method="POST", operation="capacity_reserve", resource="pool-a")

    world.run(scenario)


def test_a_method_no_route_serves_is_a_signed_405_with_allow(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("PUT", "/items/a/set", operation="item_set", resource="a")

        assert response.status_code == 405 and response.headers["allow"] == "POST"
        assert response.json()["code"] == "operation_not_served"
        assert caller.verified(response, method="PUT", operation="item_set", resource="a")

    world.run(scenario)


def test_another_stated_operation_or_resource_is_a_signed_400_bound_over_the_route(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        operation = await caller.send("POST", "/items/a/set", operation="item_raise", resource="a", body={"value": 1})
        resource = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="b", body={"value": 1}, request_id="request-2"
        )

        assert operation.status_code == 400
        assert operation.json() == {
            "code": "operation_mismatch",
            "stated": {"operation": "item_raise", "resource": "a"},
            "bound": {"operation": "item_set", "resource": "a"},
        }
        assert caller.verified(operation, method="POST", operation="item_set", resource="a")
        assert resource.status_code == 400 and resource.json()["bound"] == {"operation": "item_set", "resource": "a"}
        assert caller.verified(resource, method="POST", operation="item_set", resource="a", request_id="request-2")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_an_audience_without_this_authority_is_a_signed_421(world: World, stranger: Signer) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send(
            "POST",
            "/items/a/set",
            operation="item_set",
            resource="a",
            body={"value": 1},
            audience=TrustedIdentitySet(identities=(stranger.identity,)),
        )

        assert response.status_code == 421 and response.json() == {"code": "audience_mismatch"}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_request_under_an_unknown_profile_carrying_the_fields_is_a_signed_400(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        body = b'{"value":1}'
        headers = sign_market_request(
            signer=caller.signer,
            request=MarketRequest(
                method="POST", operation="item_set", resource="a", request_id="request-1", role="seller", origin=START
            ),
            body=body,
            created=START,
            audience=caller.authority,
        ).headers
        headers["Signature-Input"] = headers["Signature-Input"].replace("market-request-signature.v3", "market-request-signature.v4")
        response = await caller.client.post("/items/a/set", content=body, headers=headers)

        assert response.status_code == 400
        assert response.json() == {"code": "unsupported_protocol", "supported": ["arkhai.market-request-signature.v3"]}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)


def test_a_version_2_request_is_an_unsigned_unsupported_protocol(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        body = {"value": 1}
        signed = sign_request(
            signer=caller.signer,
            envelope=RequestEnvelope(
                role="seller",
                principal=caller.signer.identity,
                method="POST",
                operation="item_set",
                resource="a",
                request_id="request-1",
                timestamp=START,
                body_hash=canonical_body_hash(body),
            ),
        )
        response = await caller.client.post(
            "/items/a/set",
            content=json.dumps(body).encode(),
            headers={
                "X-Market-Signature-Version": REQUEST_PROTOCOL,
                "X-Market-Identity-Scheme": signed.principal.scheme.value,
                "X-Market-Identity-Identifier": signed.principal.identifier,
                "X-Market-Role": signed.role,
                "X-Market-Request-ID": signed.request_id,
                "X-Market-Timestamp": str(signed.timestamp),
                "X-Market-Signature": signed.proof.value,
            },
        )

        assert response.status_code == 400
        assert response.json() == {"code": "unsupported_protocol", "supported": ["arkhai.market-request-signature.v3"]}
        assert "signature" not in response.headers and "signature-input" not in response.headers

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_request_with_no_request_identity_is_answered_unsigned(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        unmatched = await caller.client.post("/nowhere")
        routed = await caller.client.post("/items/a/set", content=b'{"value":1}')

        assert unmatched.status_code == 404 and "signature" not in unmatched.headers
        assert routed.status_code == 400 and "signature" not in routed.headers

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_an_unauthenticated_route_is_served_as_it_is(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.client.get("/health")

        assert response.status_code == 200 and response.json() == {"status": "ok"}
        assert "signature" not in response.headers

    world.run(scenario)


def test_a_rotated_authority_accepts_an_audience_holding_both_principals(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    old, new = authority_signer(), Ed25519Signer(ROTATED_AUTHORITY_SEED)
    world = make_world(tmp_path, form, caller_signer, authority=new)
    overlap = TrustedIdentitySet(identities=(old.identity, new.identity))

    async def scenario(caller: Caller) -> None:
        caller.authority = overlap
        response = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 2})

        assert response.status_code == 200
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)


def test_a_reused_request_id_asking_anything_else_is_refused_before_dispatch(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        first = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1})
        assert first.status_code == 200

        changed_body = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 2})
        changed_role = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1}, role="admin"
        )
        changed_origin = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1}, origin=START - 1
        )
        changed_operation = await caller.send(
            "POST", "/items/a/raise", operation="item_raise", resource="a", body={"value": 1}
        )
        for refused, operation in (
            (changed_body, "item_set"),
            (changed_role, "item_set"),
            (changed_origin, "item_set"),
            (changed_operation, "item_raise"),
        ):
            assert refused.status_code == 409
            assert refused.json() == {"detail": "Request ID was reused with changed signed content"}
            assert caller.verified(refused, method="POST", operation=operation, resource="a")

        headers = dict(
            sign_market_request(
                signer=caller.signer,
                request=MarketRequest(
                    method="POST", operation="item_set", resource="a", request_id="request-1", role="seller", origin=START
                ),
                body=b'{"value":1}',
                created=START,
                audience=caller.authority,
            ).headers
        )
        headers["Signature-Input"] = headers["Signature-Input"].replace(
            caller.signer.identity.identifier, authority_signer().identity.identifier
        )
        changed_principal = await caller.client.post("/items/a/set", content=b'{"value":1}', headers=headers)
        assert changed_principal.status_code == 401

    world.run(scenario)
    assert world.toy.dispatches == {"item_set": 1}
    assert world.toy.items() == {"a": 1}


def test_a_caller_outside_the_route_roles_or_the_trust_is_refused(world: World, stranger: Signer) -> None:
    async def scenario(caller: Caller) -> None:
        wrong_role = await caller.send("POST", "/items/a/raise", operation="item_raise", resource="a", body={"value": 1}, role="admin")
        untrusted = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1}, signer=stranger, request_id="request-2"
        )

        assert wrong_role.status_code == 403
        assert caller.verified(wrong_role, method="POST", operation="item_raise", resource="a")
        assert untrusted.status_code == 403 and untrusted.json() == {"detail": "Request principal is not trusted"}
        assert caller.verified(untrusted, method="POST", operation="item_set", resource="a", request_id="request-2")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_request_outside_the_skew_or_with_an_origin_ahead_is_refused(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        stale = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1}, created=START - SKEW - 1
        )
        ahead = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1},
            origin=START + SKEW + 1, request_id="request-2",
        )

        assert stale.status_code == 401 and ahead.status_code == 401
        assert stale.json() == {"detail": "Request timestamp is outside the allowed skew"}
        assert caller.verified(stale, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_the_time_setting_operation_is_exempt_from_freshness_alone(world: World) -> None:
    ahead = START + 900

    async def scenario(caller: Caller) -> None:
        other = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 1},
            origin=ahead, created=ahead, request_id="request-2",
        )
        assert other.status_code == 401

        moved = await caller.send(
            "POST", "/admin/time", operation="time_set", body={"now": ahead}, role="admin", origin=ahead, created=ahead
        )
        assert moved.status_code == 200 and moved.json()["now"] == ahead
        assert caller.verified(moved, method="POST", operation="time_set")

    world.run(scenario)
    assert world.toy.dispatches == {"time_set": 1}


def test_a_route_whose_body_holds_no_resource_is_a_signed_400(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/claims", operation="item_claim", body={})

        assert response.status_code == 400 and response.json() == {"detail": "item is required"}
        assert caller.verified(response, method="POST", operation="item_claim")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_route_deriving_its_resource_from_the_body_admits_the_resource_stated(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/claims", operation="item_claim", resource="a", body={"item": "a"})

        assert response.status_code == 200 and response.json() == {"claimed": "a"}
        assert caller.verified(response, method="POST", operation="item_claim", resource="a")

    world.run(scenario)


def test_a_proof_that_fails_on_a_route_is_a_signed_401_bound_over_the_route(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        headers = sign_market_request(
            signer=caller.signer,
            request=MarketRequest(
                method="POST", operation="item_raise", resource="z", request_id="request-1", role="seller", origin=START
            ),
            body=b'{"value":1}',
            created=START,
            audience=caller.authority,
        ).headers
        response = await caller.client.post("/items/a/set", content=b'{"value":2}', headers=headers)

        assert response.status_code == 401
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_declared_route_refused_by_an_earlier_dependency_answers_signed(
    tmp_path: Path, caller_signer: Signer
) -> None:
    toy = Toy(migrated_database(tmp_path / "toy.sqlite3"))
    core = make_core(toy, caller=caller_signer, authority=authority_signer())
    app = FastAPI()

    async def closed() -> None:
        raise HTTPException(status_code=503)

    admission = RouteAdmission(core, operation="item_set", roles={"seller"}, exact_retry=ExactRetry.RECORDED)

    @app.post("/closed")
    async def closed_route(_: None = Depends(closed), admitted: object = Depends(admission)) -> None: ...

    world = World(toy=toy, core=core, app=install(app, core), caller_signer=caller_signer, authority=authority_signer())

    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/closed", operation="item_set")

        assert response.status_code == 503
        assert caller.verified(response, method="POST", operation="item_set")

    world.run(scenario)


def test_a_request_failing_before_its_admission_is_a_500_signed_over_its_stated_fields(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/claims", operation="item_claim", resource="a", raw_body=b"not json")

        assert response.status_code == 500 and response.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified(response, method="POST", operation="item_claim", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


# -- an operation with no target ----------------------------------------------------


def test_a_resource_stated_for_an_operation_with_no_target_is_a_signed_400(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send(
            "POST", "/items", operation="item_publish", resource="items", body={"item": "a", "value": 1}
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "operation_mismatch",
            "stated": {"operation": "item_publish", "resource": "items"},
            "bound": {"operation": "item_publish", "resource": None},
        }
        assert caller.verified(response, method="POST", operation="item_publish")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_no_resource_stated_for_an_operation_with_a_target_is_a_signed_400(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items/a/set", operation="item_set", body={"value": 1})

        assert response.status_code == 400
        assert response.json() == {
            "code": "operation_mismatch",
            "stated": {"operation": "item_set", "resource": None},
            "bound": {"operation": "item_set", "resource": "a"},
        }
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_request_for_an_operation_with_no_target_is_admitted_and_answered_signed(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items", operation="item_publish", body={"item": "b", "value": 3})

        assert response.status_code == 200 and response.json() == {"item": "b", "value": 3}
        assert caller.verified(response, method="POST", operation="item_publish")
        assert "market-resource" not in response.headers["signature-input"]

    world.run(scenario)
    assert world.toy.items() == {"b": 3}


# -- the admission's record ---------------------------------------------------------


def test_a_handler_reads_the_admissions_record_and_body(world: World) -> None:
    sent = json.dumps({"item": "c", "value": 4}).encode()

    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items", operation="item_publish", raw_body=sent)
        assert response.status_code == 200

    world.run(scenario)

    (admission,) = world.toy.kept
    assert admission.body == sent
    assert admission.record == admission.request.record
    assert admission.record.audience == (principal_text(world.authority.identity),)
    kept = verify_request_evidence(
        json.loads(admission.record.model_dump_json()), body=admission.body,
        trusted=TrustedIdentitySet(identities=(world.caller_signer.identity,)),
        expected_role="seller", expected_operation="item_publish", expected_resource=None,
    )
    assert kept.verified
