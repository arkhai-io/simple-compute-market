"""What ``buy`` records is what the commands that recover a deal read back.

``market bare-metal buy`` writes the run log that ``access``, ``result``,
``teardown``, and the introduction commands recover a deal from, through
``_recovered_deal``. Producer and consumer are both run here: ``buy`` writes a
real run log under one temporary state directory, and the deal is recovered from
it, so a change to what the producer records that the consumer cannot read fails
this test.

Only the command module's own factories are replaced, as the command-module
convention in ``docs/development/TESTING.md`` asks: ``fresh_identity``,
``registry_client``, and ``payment_approval`` for the purchase, and
``recovery_identity`` for the recovery. Configuration is a real file read by the
real loader. The seller is a fake served over loopback HTTP: it verifies each
request's version 2 proof against the buyer's principal, derives the payment
mandate through the payments kit's seller stage, and signs every response as the
listing's publisher. Payment approval is the payments kit's real
``PaymentApproval`` over its in-memory ``FakePaymentsClient``. Nothing here is a
live purchase or a real storefront.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from arkhai_bare_metal_buyer import cli
from core_buyer import ResolvedBuyerIdentity
from core_buyer.run_log import read_run
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    PaymentApproval,
)
from market_arkhai_payments.fixtures.payments_client import FakePaymentsClient
from market_arkhai_payments.seller import PaymentSellerStage
from market_core.schemas import (
    Agreement,
    RateValue,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    verify_request,
)
from registry_client import ListingSummary
from typer.testing import CliRunner

# Deterministic development keys and accounts for this test only; never use
# them on any network.
_BUYER = Ed25519Signer(bytes([11]) * 32)
_SELLER = Ed25519Signer(bytes([12]) * 32)
_REGISTRY = Ed25519Signer(bytes([13]) * 32)
_PAYMENTS_SERVICE = Ed25519Signer(bytes([14]) * 32)
_PAYER_ACCOUNT = "11111111-1111-4111-8111-111111111111"
_PAYEE_ACCOUNT = "22222222-2222-4222-8222-222222222222"
_DISPUTE_AUTHORITY = "33333333-3333-4333-8333-333333333333"
_PROFILE_ID = uuid.UUID(int=11)

_LISTING_ID = "listing-0001"
_PUBLISHER_ID = 7
_NEGOTIATION_ID = "negotiation-0001"
_REGISTRY_URL = "https://registry.example"
_REGISTRY_AUTHORITY = "registry-test"
# A reserved documentation address standing in for the buyer's route to a host.
_ACCESS = {"host": "192.0.2.10", "port": 22, "user": "tenant0000"}

_PAYMENTS = {
    # Never contacted: the approval's payments client is the in-memory fake.
    "service_url": "http://127.0.0.1:9",
    "fee_bps": 250,
    "dispute_authority": _DISPUTE_AUTHORITY,
}

_OPTION_PARAMS = {
    "payee_account": _PAYEE_ACCOUNT,
    "asset": "USD/6",
    "window": "P7D",
    "deposit_agreement": False,
}
_RATES = [RateValue(field="amount", value="1000000", per="hour")]
_OPTION = SettlementOption(
    option_id=derive_settlement_option_id(
        mechanism=ARKHAI_PAYMENTS_MECHANISM,
        asset="USD/6",
        rates=_RATES,
        params=_OPTION_PARAMS,
    ),
    mechanism=ARKHAI_PAYMENTS_MECHANISM,
    asset="USD/6",
    rates=_RATES,
    params=_OPTION_PARAMS,
)


class _Seller:
    """A storefront's signed negotiate, settle, and access routes, faked."""

    def __init__(self) -> None:
        self.stage = PaymentSellerStage(
            ArkhaiPaymentsConfig(
                enabled=True,
                service_identity=_PAYMENTS_SERVICE.identity,
                development_auth=True,
                **_PAYMENTS,
            )
        )
        self.transaction_id: str | None = None
        self.requests: list[tuple[str, str]] = []
        self.refusals: list[str] = []

    def route(self, method: str, path: str, body: Any) -> tuple[str, str, dict[str, Any]]:
        """The operation and resource a route binds, and its answer."""

        if method == "POST" and path == "/api/v1/negotiate/new":
            return "negotiate_new", body["listing_id"], self._accept(body)
        settle = f"/api/v1/settle/{_NEGOTIATION_ID}"
        if method == "POST" and path == settle:
            return "settle_escrow", _NEGOTIATION_ID, {
                "negotiation_id": _NEGOTIATION_ID,
                "escrow_uid": _NEGOTIATION_ID,
                "settlement_ref": self.transaction_id,
                "status": "settlement_verified",
                "retryable": False,
                "buyer_principal": _BUYER.identity.model_dump(mode="json"),
                "seller_principal": _SELLER.identity.model_dump(mode="json"),
            }
        access = f"/api/v1/fulfillments/{_NEGOTIATION_ID}/access"
        if method == "GET" and path == access:
            return "bare_metal_fulfillment_access", _NEGOTIATION_ID, dict(_ACCESS)
        raise LookupError(f"{method} {path}")

    def _accept(self, body: dict[str, Any]) -> dict[str, Any]:
        proposal = body["proposal"]
        selection = proposal["settlement_selection"]
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        agreement = Agreement(
            negotiation_id=_NEGOTIATION_ID,
            listing_id=body["listing_id"],
            listing_hash="0" * 64,
            buyer=body["buyer_principal"],
            seller=_SELLER.identity.model_dump(mode="json"),
            settlement=_OPTION,
            settlement_params=selection["params"],
            amount=proposal["fields"]["amount"],
            asset=_OPTION.asset,
            duration_seconds=body["provision_terms"]["payload"]["duration_seconds"],
            start_utc=now,
            provision_terms=body["provision_terms"],
            accepted_at=now,
        ).model_dump(mode="json", exclude_none=True)
        data = self.stage.settlement_data(agreement)
        self.transaction_id = data.transaction_id
        return {
            "negotiation_id": _NEGOTIATION_ID,
            "action": "accept",
            "proposal": proposal,
            "accepted_provision_terms": body["provision_terms"],
            "settlement_selection": selection,
            "agreement": agreement,
            "agreement_bytes": base64.b64encode(
                json.dumps(agreement, sort_keys=True).encode("utf-8")
            ).decode("ascii"),
            "settlement_data": data.to_wire(),
            "buyer_principal": body["buyer_principal"],
            "seller_principal": _SELLER.identity.model_dump(mode="json"),
        }


@contextmanager
def _served(seller: _Seller) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._answer()

        def do_POST(self) -> None:
            self._answer()

        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else EMPTY_BODY
            operation, resource, payload = seller.route(self.command, self.path, body)
            request_id = self.headers["X-Market-Request-ID"]
            proof = verify_request(
                AuthenticatedRequest.model_validate({
                    "protocol": self.headers["X-Market-Signature-Version"],
                    "role": self.headers["X-Market-Role"],
                    "principal": {
                        "scheme": self.headers["X-Market-Identity-Scheme"],
                        "identifier": self.headers["X-Market-Identity-Identifier"],
                    },
                    "method": self.command,
                    "operation": operation,
                    "resource": resource,
                    "request_id": request_id,
                    "timestamp": int(self.headers["X-Market-Timestamp"]),
                    "body_hash": canonical_body_hash(body),
                    "proof": {
                        "scheme": self.headers["X-Market-Identity-Scheme"],
                        "value": self.headers["X-Market-Signature"],
                    },
                }),
                body=body,
                now=int(time.time()),
                max_skew=300,
                expected_role="buyer",
                expected_method=self.command,
                expected_operation=operation,
                expected_resource=resource,
                expected_principals=TrustedIdentitySet(identities=(_BUYER.identity,)),
            )
            seller.requests.append((self.command, self.path))
            if not proof.verified:
                seller.refusals.append(f"{self.path}: {proof.code.value}")
            status = 200 if proof.verified else 401
            answer = payload if proof.verified else {"detail": proof.code.value}
            signed = sign_response(
                signer=_SELLER,
                envelope=ResponseEnvelope(
                    role="seller",
                    principal=_SELLER.identity,
                    method=self.command,
                    operation=operation,
                    resource=resource,
                    request_id=request_id,
                    timestamp=int(time.time()),
                    status=status,
                    body_hash=canonical_body_hash(answer),
                ),
            )
            encoded = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Market-Signature-Version", signed.protocol)
            self.send_header("X-Market-Role", signed.role)
            self.send_header("X-Market-Identity-Scheme", signed.principal.scheme.value)
            self.send_header("X-Market-Identity-Identifier", signed.principal.identifier)
            self.send_header("X-Market-Request-ID", signed.request_id)
            self.send_header("X-Market-Timestamp", str(signed.timestamp))
            self.send_header("X-Market-Signature", signed.proof.value)
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config_file(path: Path) -> Path:
    identity = _REGISTRY.identity
    service = _PAYMENTS_SERVICE.identity
    path.write_text(
        f"""
[bare_metal]
registry_url = "{_REGISTRY_URL}/"
registry_authority = "{_REGISTRY_AUTHORITY}"
registry_principals = [{{scheme = "{identity.scheme.value}", identifier = "{identity.identifier}"}}]
payer_account = "{_PAYER_ACCOUNT}"

[bare_metal.arkhai_payments]
enabled = true
service_url = "{_PAYMENTS["service_url"]}"
service_identity = {{scheme = "{service.scheme.value}", identifier = "{service.identifier}"}}
fee_bps = {_PAYMENTS["fee_bps"]}
dispute_authority = "{_DISPUTE_AUTHORITY}"
development_auth = true
""".strip(),
        encoding="utf-8",
    )
    return path


def _identity(source: str) -> ResolvedBuyerIdentity:
    return ResolvedBuyerIdentity(
        profile_id=_PROFILE_ID,
        principal=_BUYER.identity,
        signer=_BUYER,
        source=source,  # type: ignore[arg-type]
    )


def test_a_deal_bought_is_recovered_from_the_run_log_buy_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # No buyer.toml: the negotiation policy is the default one.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    config = _config_file(tmp_path / "bare-metal-buyer.toml")
    seller = _Seller()
    payments = FakePaymentsClient(signer=_PAYMENTS_SERVICE)
    listing_reads: list[str] = []

    with _served(seller) as seller_url:
        publisher = TrustedIdentitySet(identities=(_SELLER.identity,))
        listing = ListingSummary(
            id=_LISTING_ID,
            status="open",
            publisher_id=_PUBLISHER_ID,
            publisher_principals=publisher,
            storefront_url=seller_url,
            settlement_options=[_OPTION.model_dump(mode="json")],
        )

        @contextmanager
        def registry_client(buyer_config: Any, identity: ResolvedBuyerIdentity) -> Iterator[Any]:
            assert buyer_config.registry_url == _REGISTRY_URL
            assert identity.principal == _BUYER.identity

            class Registry:
                def get_listing(self, listing_id: str) -> ListingSummary:
                    listing_reads.append(listing_id)
                    return listing

            yield Registry()

        def payment_approval(buyer_config: Any) -> PaymentApproval:
            return PaymentApproval(
                buyer_config.arkhai_payments,
                buyer_config.payer_account,
                client_for_owner=payments,
            )

        def no_fresh_identity() -> ResolvedBuyerIdentity:
            raise AssertionError("recovery resolved a fresh identity")

        recovered_runs: list[str] = []

        def recovery_identity(run_id: str) -> ResolvedBuyerIdentity:
            recovered_runs.append(run_id)
            return _identity("recovery")

        monkeypatch.setattr(cli, "fresh_identity", lambda: _identity("fresh"))
        monkeypatch.setattr(cli, "registry_client", registry_client)
        monkeypatch.setattr(cli, "payment_approval", payment_approval)
        monkeypatch.setattr(cli, "recovery_identity", no_fresh_identity)

        bought = CliRunner().invoke(cli.bare_metal_app, [
            "buy", _LISTING_ID, "--option-id", _OPTION.option_id,
            # A placeholder key, never a credential.
            "--ssh-public-key", "ssh-ed25519 AAAAPLACEHOLDER",
            "--duration-seconds", "3600", "--payment-timeout-seconds", "5",
            "--config", str(config),
        ])
        assert bought.exit_code == 0, bought.output
        purchase = json.loads(bought.output.strip().splitlines()[-1])
        run_id = purchase["run_id"]
        assert purchase["transaction_id"] == seller.transaction_id
        assert payments.count("approve") == 1

        monkeypatch.setattr(cli, "fresh_identity", no_fresh_identity)
        monkeypatch.setattr(cli, "recovery_identity", recovery_identity)
        reads_before_recovery = len(listing_reads)

        deal, identity, trust = cli._recovered_deal(run_id, str(config))

        # Recovery checks the recorded publisher against the registry's current
        # listing before it trusts it.
        assert listing_reads[reads_before_recovery:] == [_LISTING_ID]
        assert recovered_runs == [run_id]
        assert identity.source == "recovery"
        assert deal.buyer_principal == _BUYER.identity
        assert deal.publisher_principals == publisher
        assert deal.publisher_id == str(_PUBLISHER_ID)
        assert deal.source_registry_url == _REGISTRY_URL
        assert deal.source_registry_authority == _REGISTRY_AUTHORITY
        assert deal.seller_url == seller_url
        assert deal.listing_id == _LISTING_ID
        assert deal.negotiation_id == _NEGOTIATION_ID
        assert trust() == publisher
        # The registry's current trust equals what buy recorded, so recovery
        # records no refreshed trust.
        events = read_run(run_id, signer=_BUYER, profile_id=_PROFILE_ID)
        assert "publisher_trust_refreshed" not in {event["event"] for event in events}
        # What a completed purchase records, in order, and how its run ends: the
        # real-host bare-metal deal reads exactly these from the log buy wrote.
        assert [event["event"] for event in events] == [
            "run_started",
            "agreement_accepted",
            "payment_approved",
            "run_ended",
        ]
        assert events[-1]["status"] == "agreed"

        accessed = CliRunner().invoke(cli.bare_metal_app, [
            "access", "--run-id", run_id, "--config", str(config),
        ])
        assert accessed.exit_code == 0, accessed.output
        assert json.loads(accessed.output.strip().splitlines()[-1]) == _ACCESS

    assert seller.refusals == []
    assert seller.requests == [
        ("POST", "/api/v1/negotiate/new"),
        ("POST", f"/api/v1/settle/{_NEGOTIATION_ID}"),
        ("GET", f"/api/v1/fulfillments/{_NEGOTIATION_ID}/access"),
    ]
