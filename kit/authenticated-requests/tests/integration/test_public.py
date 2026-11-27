"""A public operation, and requests of its shape that no route serves, in each form.

Library integration, as the admission tests are: the toy's ``GET /descriptor`` is a
public operation, bound in the middleware form's table or admitted through its
``PublicAdmission`` in the dependency form. A public request is built by
``kit/identity``'s public request builder, and its answer verified against the
binding the builder gave.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from market_identity import MarketRequest, Signer, sign_market_request
from market_identity.wire import MARKET_RESOURCE, SIGNATURE, SIGNATURE_INPUT

from market_authenticated_requests import (
    REPLAY_TABLE,
    ROUTE_FAILURE_DETAIL,
    PublicAdmission,
    PublicAdmitted,
    PublicBinding,
    RouteBinding,
    RouteNotServed,
    install,
)
from tests.integration.support import (
    DESCRIPTOR_OPERATION,
    DESCRIPTOR_PATH,
    START,
    Caller,
    Toy,
    World,
    authority_signer,
    make_core,
    migrated_database,
)


def _replay_rows(world: World) -> int:
    with closing(sqlite3.connect(world.toy.database)) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {REPLAY_TABLE}").fetchone()[0])


def test_a_public_read_is_answered_signed_over_its_request_identity_and_reserves_nothing(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response, binding = await caller.send_public("GET", DESCRIPTOR_PATH)
        again, rebound = await caller.send_public("GET", DESCRIPTOR_PATH)

        assert response.status_code == 200
        assert response.json() == {"name": "toy", "request_id": binding.request_id}
        assert caller.verified_binding(response, binding)
        assert not caller.verified_binding(response, rebound)
        assert again.status_code == 200 and caller.verified_binding(again, rebound)

    world.run(scenario)
    assert _replay_rows(world) == 0
    assert world.outcomes == []


def test_a_signed_request_to_a_public_operation_is_refused_as_malformed(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        signed = await caller.send("GET", DESCRIPTOR_PATH, operation=DESCRIPTOR_OPERATION)
        half, binding = await caller.send_public("GET", DESCRIPTOR_PATH, extra={SIGNATURE: "market=:AAAA:"})
        input_only, input_binding = await caller.send_public(
            "GET", DESCRIPTOR_PATH, extra={SIGNATURE_INPUT: 'market=("@method");created=1'}
        )

        assert signed.status_code == 400
        assert signed.json() == {"detail": "A public operation's request carries no signature"}
        assert caller.verified(signed, method="GET", operation=DESCRIPTOR_OPERATION)
        assert half.status_code == 400 and caller.verified_binding(half, binding)
        assert input_only.status_code == 400 and caller.verified_binding(input_only, input_binding)

    world.run(scenario)
    assert _replay_rows(world) == 0


def test_another_operation_or_a_resource_stated_to_a_public_operation_is_a_mismatch(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        other, other_binding = await caller.send_public("GET", DESCRIPTOR_PATH, operation="toy.other.read")
        resource, resource_binding = await caller.send_public("GET", DESCRIPTOR_PATH, extra={MARKET_RESOURCE: "toy"})

        assert other.status_code == 400
        assert other.json() == {
            "code": "operation_mismatch",
            "stated": {"operation": "toy.other.read", "resource": None},
            "bound": {"operation": DESCRIPTOR_OPERATION, "resource": None},
        }
        route = other_binding.model_copy(update={"operation": DESCRIPTOR_OPERATION})
        assert caller.verified_binding(other, route)
        assert resource.status_code == 400
        assert resource.json() == {
            "code": "operation_mismatch",
            "stated": {"operation": DESCRIPTOR_OPERATION, "resource": "toy"},
            "bound": {"operation": DESCRIPTOR_OPERATION, "resource": None},
        }
        assert caller.verified_binding(resource, resource_binding)

    world.run(scenario)


def test_a_request_to_a_public_operation_stating_no_identity_is_answered_unsigned(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response = await caller.client.get(DESCRIPTOR_PATH)

        assert response.status_code == 400
        assert "signature" not in response.headers and "signature-input" not in response.headers

    world.run(scenario)


# -- unmatched requests of a public operation's shape --------------------------------


def test_a_public_request_on_a_mistyped_path_is_a_signed_404(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response, binding = await caller.send_public("GET", DESCRIPTOR_PATH + "s")

        assert response.status_code == 404
        assert response.json() == {"code": "operation_not_served", "operation": DESCRIPTOR_OPERATION}
        assert caller.verified_binding(response, binding)

    world.run(scenario)


def test_a_public_post_to_a_get_only_public_path_is_a_signed_405_with_allow(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        response, binding = await caller.send_public("POST", DESCRIPTOR_PATH)

        assert response.status_code == 405 and response.headers["allow"] == "GET"
        assert response.json() == {"code": "operation_not_served", "operation": DESCRIPTOR_OPERATION}
        assert caller.verified_binding(response, binding)

    world.run(scenario)


def test_a_signed_request_under_an_unknown_profile_on_an_unmatched_path_is_unsupported(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        headers = sign_market_request(
            signer=caller.signer,
            request=MarketRequest(
                method="POST", operation="item_set", resource="a", request_id="request-1", role="seller", origin=START
            ),
            body=b"",
            created=START,
            audience=caller.authority,
        ).headers
        headers[SIGNATURE_INPUT] = headers[SIGNATURE_INPUT].replace(
            "market-request-signature.v3", "market-request-signature.v4"
        )
        response = await caller.client.post("/nowhere", headers=headers)

        assert response.status_code == 400
        assert response.json() == {"code": "unsupported_protocol", "supported": ["arkhai.market-request-signature.v3"]}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)


def test_a_forged_signature_on_an_unmatched_path_is_refused_as_an_invalid_proof(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        def signed(request_id: str) -> dict[str, str]:
            return sign_market_request(
                signer=caller.signer,
                request=MarketRequest(
                    method="POST", operation="item_set", resource="a", request_id=request_id, role="seller",
                    origin=START,
                ),
                body=b"",
                created=START,
                audience=caller.authority,
            ).headers

        forged = {**signed("request-1"), SIGNATURE: signed("request-2")[SIGNATURE]}
        response = await caller.client.post("/nowhere", headers=forged)

        assert response.status_code == 401 and response.json() == {"detail": "Invalid request proof"}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)


class _PublicOnly:
    """A middleware-form table binding the descriptor read alone."""

    def resolve(self, method: str, path: str, body: bytes) -> RouteBinding | PublicBinding:
        if (method, path) == ("GET", DESCRIPTOR_PATH):
            return PublicBinding(DESCRIPTOR_OPERATION)
        raise RouteNotServed()

    def declares(self, method: str, path_template: str) -> bool:
        return (method, path_template) == ("GET", DESCRIPTOR_PATH)


def test_a_public_handler_that_raises_is_a_signed_500_revealing_nothing(
    tmp_path: Path, form: str, caller_signer: Signer, caplog: pytest.LogCaptureFixture
) -> None:
    toy = Toy(migrated_database(tmp_path / "public.sqlite3"))
    authority = authority_signer()
    core = make_core(toy, caller=caller_signer, authority=authority)
    app = FastAPI()

    async def from_state(request: Request) -> PublicAdmitted:
        return request.state.authenticated_request

    admission = PublicAdmission(core, operation=DESCRIPTOR_OPERATION) if form == "dependency" else from_state

    @app.get(DESCRIPTOR_PATH)
    async def descriptor(admitted: PublicAdmitted = Depends(admission)) -> None:
        raise LookupError("a secret detail of the failure")

    world = World(
        toy=toy, core=core, caller_signer=caller_signer, authority=authority,
        app=install(app, core, routes=_PublicOnly() if form == "middleware" else None),
    )

    async def scenario(caller: Caller) -> None:
        response, binding = await caller.send_public("GET", DESCRIPTOR_PATH)

        assert response.status_code == 500 and response.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified_binding(response, binding)

    world.run(scenario)
    assert "a secret detail of the failure" in caplog.text
    assert _replay_rows(world) == 0
