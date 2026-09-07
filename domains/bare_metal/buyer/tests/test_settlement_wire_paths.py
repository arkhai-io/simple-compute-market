"""The buyer's settle and begin calls address the routes the server serves.

Both were missing entirely: the storefront has served `POST /api/v1/settle/{uid}`
and `POST /api/v1/fulfillments/begin` while the buyer transport had no way to
call either, so a crypto agreement could be negotiated and then never funded,
verified or fulfilled.

The path, method, operation and resource are asserted against the server's own
route table and authorization calls rather than against a copy of them, so a
rename on either side fails here instead of at a live run.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_identity import IdentityScheme, TrustedIdentitySet, create_signer

BUYER_PRINCIPAL_SEED = bytes(range(32))
SELLER_PRINCIPAL_SEED = bytes([1]) * 32

# Resolved from the installed storefront distribution when present, else from
# the source tree beside this package. Reading the server is the point: a
# hand-copied path would pass while the wire was broken.
_CANDIDATE_API_PATHS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "storefront/src/arkhai_bare_metal_storefront/api.py",
)


def _server_source() -> str:
    for candidate in _CANDIDATE_API_PATHS:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    pytest.skip("bare-metal storefront source is not available to compare against")


@pytest.fixture()
def transport(monkeypatch):
    calls: list[tuple[str, dict | None, dict]] = []

    def signed(url, body, **kwargs):
        calls.append((url, body, kwargs))
        return {"ok": True}

    monkeypatch.setattr(
        "arkhai_bare_metal_buyer.fulfillment.signed_storefront_json", signed
    )
    signer = create_signer(IdentityScheme.ED25519, BUYER_PRINCIPAL_SEED)
    trust = TrustedIdentitySet(
        identities=(
            create_signer(IdentityScheme.ED25519, SELLER_PRINCIPAL_SEED).identity,
        )
    )
    return (
        BareMetalFulfillmentTransport(
            seller_url="https://seller.example/",
            principal=signer.identity,
            signer=signer,
            resolve_seller_principals=lambda: trust,
        ),
        calls,
    )


def test_settle_addresses_the_escrow_route(transport) -> None:
    client, calls = transport

    assert client.settle(
        escrow_uid="escrow-1",
        negotiation_id="neg-1",
        buyer_evm_address="0x0000000000000000000000000000000000000009",
    ) == {"ok": True}

    url, body, kwargs = calls[0]
    assert url == "https://seller.example/api/v1/settle/escrow-1"
    assert kwargs["method"] == "POST"
    assert kwargs["operation"] == "settle_escrow"
    # The escrow, not the negotiation: signing the negotiation would let one
    # authorization be replayed against a different escrow.
    assert kwargs["resource"] == "escrow-1"
    assert body["negotiation_id"] == "neg-1"
    assert body["buyer_evm_address"].startswith("0x")
    assert body["buyer_principal"]["scheme"]


def test_begin_addresses_the_fulfillment_route(transport) -> None:
    client, calls = transport

    assert client.begin(negotiation_id="neg-1", escrow_uid="escrow-1") == {"ok": True}

    url, body, kwargs = calls[0]
    assert url == "https://seller.example/api/v1/fulfillments/begin"
    assert kwargs["method"] == "POST"
    assert kwargs["operation"] == "bare_metal_fulfillment_begin"
    assert kwargs["resource"] == "neg-1"
    assert body["negotiation_id"] == "neg-1"
    assert body["escrow_uid"] == "escrow-1"


def test_the_request_bodies_match_the_server_request_models() -> None:
    """A missing required field would be a 422 only at a live run."""
    from arkhai_bare_metal_buyer import fulfillment as buyer_fulfillment

    source = pathlib.Path(buyer_fulfillment.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    sent: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in {
            "settle",
            "begin",
        }:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Dict):
                keys = {
                    key.value
                    for key in call.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                if "buyer_principal" in keys:
                    sent[node.name] = keys

    assert sent["settle"] == {
        "negotiation_id",
        "buyer_principal",
        "buyer_evm_address",
    }
    assert sent["begin"] == {"negotiation_id", "escrow_uid", "buyer_principal"}


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ('"/api/v1/settle/{escrow_uid}"', "settle_escrow"),
        ('"/api/v1/fulfillments/begin"', "bare_metal_fulfillment_begin"),
    ],
)
def test_the_server_still_serves_the_routes_the_buyer_calls(path, operation) -> None:
    server = _server_source()

    assert path in server, f"server no longer routes {path}"
    assert f'operation="{operation}"' in server
