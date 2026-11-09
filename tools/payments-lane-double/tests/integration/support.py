"""One double in process, the kit's client for each account, and the control client.

The double runs behind Starlette's test client, which an httpx mock transport
forwards to, so ``PaymentsClient`` and ``ControlClient`` send exactly the requests
they send over the network. The wall clock is injected; the double's perceived
clock adds the offset the clock controls move.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from lane_double_controls import ControlClient
from market_arkhai_payments import PaymentsAPIError, PaymentsClient
from market_arkhai_payments.canonical import agreement_hash

from payments_lane_double.accounts import AccountDirectory, parse_accounts
from payments_lane_double.app import create_app

from conftest import Clock, committed_accounts

T0 = 1_800_000_000
HOUR = 3_600
DAY = 86_400
# Loopback, so the client builds its connection without reading proxy settings
# from the environment, which would mount a proxy ahead of the in-process transport.
ORIGIN = "https://127.0.0.1:8443"
# Public development tokens and accounts this suite adds to the committed
# directory; never use them on a public network. The stranger is no party to any
# mandate here; the watcher is named only in a part's authorities; the authority
# holds a part's extend authority; the payer is a second payer funded with little.
STRANGER = ("00000000-0000-4000-8000-0000000000e1", "lane-double-suite-stranger-token")
WATCHER = ("00000000-0000-4000-8000-0000000000e2", "lane-double-suite-watcher-token")
AUTHORITY = ("00000000-0000-4000-8000-0000000000e3", "lane-double-suite-authority-token")
PAYER = ("00000000-0000-4000-8000-0000000000e4", "lane-double-suite-payer-token")
# A well-formed account the directory does not hold; a public test value, never
# for a public network.
UNKNOWN = "99999999-9999-4999-8999-999999999999"
AGREEMENT = {"listing": "lane-double-suite", "price": "1000000"}


def suite_directory() -> AccountDirectory:
    document = committed_accounts()
    for role, (account, token) in (("stranger", STRANGER), ("watcher", WATCHER),
                                   ("authority", AUTHORITY), ("payer", PAYER)):
        document["accounts"][role] = {"account": account, "token": token}
    return parse_accounts(document)


class Lane:
    """One app over a fresh engine, and the kit's client for each account."""

    def __init__(self) -> None:
        self.clock = Clock(T0)
        self.directory = suite_directory()
        self.app = create_app(self.directory, clock=self.clock)
        self.http = TestClient(self.app, base_url=ORIGIN)

    def transport(self) -> httpx.MockTransport:
        def forward(request: httpx.Request) -> httpx.Response:
            answer = self.http.request(request.method, str(request.url),
                                       headers=request.headers, content=request.content)
            return httpx.Response(answer.status_code, headers=answer.headers,
                                  content=answer.content)
        return httpx.MockTransport(forward)

    def client(self, role: str) -> PaymentsClient:
        token = self.directory.role(role).token
        assert token is not None
        return self.token_client(token)

    def token_client(self, token: str) -> PaymentsClient:
        return PaymentsClient(ORIGIN, api_key=token, transport=self.transport())

    def controls(self, token: str | None = None) -> ControlClient:
        return ControlClient(ORIGIN, token=token or self.directory.control_token,
                             transport=self.transport())

    def account(self, role: str) -> str:
        return self.directory.role(role).account

    def funding(self) -> int:
        return self.directory.role("buyer").funding


def mandate(lane: Lane, *, amount: str = "1000000", nonce: str = "suite-1",
            agreement: dict[str, Any] = AGREEMENT, **changes: Any) -> dict[str, Any]:
    terms: dict[str, Any] = {
        "from": lane.account("buyer"), "to": lane.account("seller"),
        "parts": [{
            "kind": "once", "asset": "USD/6", "amount": amount, "hold": {"for": "P7D"},
            "authorities": {"stop": [], "reverse": [lane.account("seller")],
                            "extend": [lane.account("dispute_authority")]},
            "maxHoldExtension": None,
        }],
        "deal": agreement_hash(agreement), "fee": {"bps": 250}, "nonce": nonce,
        "expires": T0 + DAY,
    }
    terms.update(changes)
    return terms


def refusal(call: Any, *args: Any, **kwargs: Any) -> tuple[int, str]:
    with pytest.raises(PaymentsAPIError) as refused:
        call(*args, **kwargs)
    return refused.value.status_code, refused.value.code


def available(lane: Lane, role: str) -> dict[str, str]:
    balance = lane.client(role).get_balance(lane.account(role))
    return {asset: value.root for asset, value in balance.available.items()}
