"""One double in process over the payments kit's engine, the kit's clients, and the control client.

The payments peer is the payments kit's ``FakePaymentsClient``, acting as the
authority's account over its shared ``PaymentsAuthority`` engine, and one injected
wall clock under the double's perceived clock is both the double's time and the
engine's. The kit's real ``MediationClient`` sends through an ASGI transport to the
app; ``ControlClient`` through Starlette's test client, which an httpx mock
transport forwards to, so both send exactly the requests they send over the
network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lane_double_controls import ControlClient
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.models import Filing
from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle.terms import DisputeAuthority
from market_identity import Ed25519Signer

from mediation_lane_double.app import create_app
from mediation_lane_double.authority import AuthorityFixture, parse_authority

from conftest import Clock, committed_authority

T0 = 1_800_000_000
DAY = 86_400
# Loopback, so a client builds its connection without reading proxy settings from
# the environment, which would mount a proxy ahead of the in-process transport.
ORIGIN = "https://127.0.0.1:8443"
# The payments signer of this suite's receipts and snapshots: a public test seed,
# never for a public network.
PAYMENTS_SIGNER = Ed25519Signer(bytes([7]) * 32)
# A caller this suite adds to the committed fixture, a party to no transaction; a
# public test value, never for a public network.
STRANGER = ("00000000-0000-4000-8000-0000000000e1", "mediation-double-suite-stranger-token")
AGREEMENT = {"listing": "mediation-double-suite", "price": "1000"}

_Result = TypeVar("_Result")


def suite_authority() -> AuthorityFixture:
    document = committed_authority()
    document["accounts"]["stranger"] = {"account": STRANGER[0], "token": STRANGER[1]}
    return parse_authority(document)


def run(awaitable: Awaitable[_Result]) -> _Result:
    async def wrapped() -> _Result:
        return await awaitable
    return asyncio.run(wrapped())


class Lane:
    """One app over a fresh engine, its payments peer, and a client for each caller.

    ``wrap`` stands between the double and the engine's client, for a test that
    has payments fail one particular call.
    """

    def __init__(self, wrap: Callable[[FakePaymentsClient], Any] | None = None) -> None:
        self.wall = Clock(T0)
        self.authority = suite_authority()
        self.payments = FakePaymentsClient(signer=PAYMENTS_SIGNER)
        # Every event the double submits is the authority account's.
        self.payments(self.authority.account)
        peer = wrap(self.payments) if wrap is not None else self.payments
        self.app = create_app(self.authority, peer, clock=self.wall)
        self.payments.engine.clock = self.app.state.clock
        self.http = TestClient(self.app, base_url=ORIGIN)
        self.dispute = DisputeAuthority.model_validate({
            "interface": self.authority.interface, "origin": ORIGIN,
            "account": self.authority.account, "record_key": self.authority.record_key,
            "params": {}})

    def account(self, role: str) -> str:
        return next(account for token, account in self.authority.tokens.items()
                    if token == self.token(role))

    def token(self, role: str) -> str:
        if role == "stranger":
            return STRANGER[1]
        document = committed_authority()
        token: str = document["accounts"][role]["token"]
        return token

    def client(self, role: str) -> MediationClient:
        identity = self.dispute.identity
        return MediationClient(
            self.dispute, MediationCredential(identity, token=SecretStr(self.token(role))),
            transport=httpx.ASGITransport(app=self.app))

    def controls(self, token: str | None = None) -> ControlClient:
        def forward(request: httpx.Request) -> httpx.Response:
            answer = self.http.request(request.method, str(request.url),
                                       headers=request.headers, content=request.content)
            return httpx.Response(answer.status_code, headers=answer.headers,
                                  content=answer.content)
        return ControlClient(ORIGIN, token=token or self.authority.control_token,
                             transport=httpx.MockTransport(forward))

    def approve(self, *, parts: int = 1, amount: str = "1000", nonce: str = "suite-1",
                extend: list[str] | None = None) -> str:
        """Approve a once-only payment of ``parts`` parts; the transaction's id."""

        buyer, seller = self.account("buyer"), self.account("seller")
        authority = [self.authority.account] if extend is None else extend
        mandate = {
            "from": buyer, "to": seller,
            "parts": [{"kind": "once", "asset": "USD/6", "amount": amount,
                       "hold": {"for": "P7D"},
                       "authorities": {"stop": [], "reverse": [seller, self.authority.account],
                                       "extend": authority},
                       "maxHoldExtension": None} for _ in range(parts)],
            "deal": agreement_hash(AGREEMENT), "fee": {"bps": 250}, "nonce": nonce,
            "expires": T0 + DAY,
        }
        receipt = self.payments.approve(mandate)
        return receipt.receipt.transaction.root

    def part(self, transaction: str, index: int = 0) -> dict[str, Any]:
        snapshot = self.payments.engine.snapshot(transaction).model_dump(
            mode="json", by_alias=True, exclude_unset=True)
        part: dict[str, Any] = snapshot["snapshot"]["parts"][index]
        return part

    def events(self, transaction: str, kind: str) -> list[dict[str, Any]]:
        snapshot = self.payments.engine.snapshot(transaction).model_dump(
            mode="json", by_alias=True, exclude_unset=True)
        return [event for event in snapshot["snapshot"]["events"]
                if event["event"]["kind"] == kind]


class Failing:
    """The payments peer, failing once each call ``fail`` picks.

    ``fail`` is given the call's name, ``get_transaction`` or ``submit_event``, and
    its request id, or for a read its number counting from one, and returns the
    error to raise or ``None``.
    With ``after_commit``, a submitted event reaches payments first and its answer
    is lost, as a response dropped after commit is.
    """

    def __init__(self, peer: Any, fail: Callable[[str, str], Exception | None], *,
                 after_commit: bool = False) -> None:
        self.peer = peer
        self.fail = fail
        self.after_commit = after_commit
        self.failed: set[tuple[str, str]] = set()
        self.reads = 0

    def _failure(self, call: str, request_id: str) -> Exception | None:
        error = self.fail(call, request_id)
        key = (call, request_id)
        if error is None or key in self.failed:
            return None
        self.failed.add(key)
        return error

    def get_transaction(self, transaction: str) -> Any:
        self.reads += 1
        error = self._failure("get_transaction", str(self.reads))
        if error is not None:
            raise error
        return self.peer.get_transaction(transaction)

    def submit_event(self, transaction: str, event: Mapping[str, Any], *,
                     request_id: str) -> Any:
        error = self._failure("submit_event", request_id)
        if error is not None and self.after_commit:
            self.peer.submit_event(transaction, event, request_id=request_id)
        if error is not None:
            raise error
        return self.peer.submit_event(transaction, event, request_id=request_id)


def filing(transaction: str, *, cause: str = "payee", delivered: bool = False,
           agreement: Mapping[str, Any] = AGREEMENT) -> Filing:
    return Filing.model_validate({
        "transaction": transaction, "agreement": dict(agreement),
        "request": {"kind": "delivery_end", "ended_at": T0, "delivered": delivered,
                    "cause": cause},
        "claim": "delivery ended", "items": [],
    })
