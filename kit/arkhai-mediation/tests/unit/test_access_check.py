"""The mediation access check reports access, or the first step that failed.

Unit: the real check, client and credential over an injected HTTP transport. The
authority is the kit's ``MediationContractFake``, answering the contract's
respondent listing, except where a case needs an answer the fake never gives (a
refused connection, a body outside the contract). No case reaches a network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from market_deal_lifecycle.configuration import DisputeCredential
from market_deal_lifecycle.terms import DisputeAuthority

from market_arkhai_mediation.access_check import (
    authority_origin,
    check_configured_mediation_access,
    check_mediation_access,
)
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing

# The fake's public development tokens; never use them on a public network.
PAYEE_TOKEN = "fixture-payee"
PAYER_TOKEN = "fixture-payer"
TOKEN_ENV = "SELLER_MEDIATION_TOKEN"


class Recording:
    """The fake authority, or a stand-in answer, recording each request."""

    def __init__(self, fake: MediationContractFake, answer=None):
        self.fake = fake
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.fake.handle(request) if self.answer is None else self.answer(request)

        return httpx.MockTransport(handle)


def credential(fake: MediationContractFake, **fields) -> DisputeCredential:
    identity = {key: fake.authority[key] for key in ("interface", "origin", "account", "record_key")}
    form = {"api_key": SecretStr(PAYEE_TOKEN)} if "api_key_env" not in fields else {}
    return DisputeCredential(**(identity | form | fields))


def origin(fake: MediationContractFake) -> str:
    return fake.authority["origin"]


def test_an_empty_respondent_listing_is_access():
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake)], origin(fake),
                                     transport=authority.transport())

    assert outcome.ok
    assert json.loads(outcome.json_line()) == {
        "check": "mediation", "outcome": "ok", "origin": origin(fake),
    }
    assert [(r.method, r.url.path, r.headers["Authorization"]) for r in authority.requests] == [
        ("GET", "/respondent", f"Bearer {PAYEE_TOKEN}")
    ]


def test_a_full_respondent_listing_is_access_too():
    fake = MediationContractFake()
    asyncio.run(_file_as_payer(fake))
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake)], origin(fake),
                                     transport=authority.transport())

    assert outcome.ok
    listed = authority.requests[0]
    assert fake.handle(listed).json()["cases"], "the listing the check read holds a case"


def test_the_token_is_read_from_the_variable_the_credential_names():
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access(
        [credential(fake, api_key_env=TOKEN_ENV)], origin(fake),
        environment={TOKEN_ENV: PAYEE_TOKEN}, transport=authority.transport(),
    )

    assert outcome.ok
    assert authority.requests[0].headers["Authorization"] == f"Bearer {PAYEE_TOKEN}"


def test_no_credential_for_the_origin_is_a_configuration_failure():
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake)], "https://other-authority.example",
                                     transport=authority.transport())

    assert (outcome.outcome, outcome.step) == ("failed", "configuration")
    assert outcome.origin == "https://other-authority.example"
    assert authority.requests == []


def test_two_credentials_for_the_origin_are_a_configuration_failure():
    fake = MediationContractFake()
    authority = Recording(fake)
    other_account = credential(fake, account="33333333-3333-4333-8333-333333333333")

    outcome = check_mediation_access([credential(fake), other_account], origin(fake),
                                     transport=authority.transport())

    assert outcome.step == "configuration"
    assert authority.requests == []


def test_a_credential_for_another_interface_is_not_the_origins_mediation_credential():
    fake = MediationContractFake()
    authority = Recording(fake)
    other_interface = credential(fake, interface="example.dispute.v1")

    alone = check_mediation_access([other_interface], origin(fake),
                                   transport=authority.transport())
    beside = check_mediation_access([other_interface, credential(fake)], origin(fake),
                                    transport=authority.transport())

    assert alone.step == "configuration"
    assert alone.detail == "no arkhai.mediation.v1 dispute credential names the origin"
    assert beside.ok
    assert len(authority.requests) == 1


def test_an_identity_the_contract_refuses_is_a_configuration_failure():
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake, account="not-an-account")],
                                     origin(fake), transport=authority.transport())

    assert outcome.step == "configuration"
    assert authority.requests == []


def test_plain_http_outside_loopback_is_a_configuration_failure():
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake, origin="http://mediation.example")],
                                     "http://mediation.example", transport=authority.transport())

    assert outcome.step == "configuration"
    assert authority.requests == []


@pytest.mark.parametrize("bundle", ["missing", "unreadable", "malformed"])
def test_a_ca_bundle_that_cannot_be_loaded_fails_configuration_before_any_request(
    tmp_path: Path, bundle: str
):
    fake = MediationContractFake()
    authority = Recording(fake)
    path = tmp_path / "lane-ca.pem"
    if bundle == "malformed":
        path.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    elif bundle == "unreadable":
        # A directory cannot be read as a file whoever runs the test.
        path.mkdir()

    outcome = check_mediation_access([credential(fake, ca_bundle_path=str(path))], origin(fake),
                                     transport=authority.transport())

    assert outcome.step == "configuration"
    assert outcome.detail == "the CA bundle ca_bundle_path names could not be loaded"
    assert authority.requests == []


@pytest.mark.parametrize("environment", [{}, {TOKEN_ENV: ""}, {TOKEN_ENV: " padded "}],
                         ids=["unset", "empty", "padded"])
def test_an_unresolvable_token_is_a_credential_failure_before_any_request(environment):
    fake = MediationContractFake()
    authority = Recording(fake)

    outcome = check_mediation_access([credential(fake, api_key_env=TOKEN_ENV)], origin(fake),
                                     environment=environment, transport=authority.transport())

    assert outcome.step == "credential"
    assert TOKEN_ENV in (outcome.detail or "")
    assert authority.requests == []


def test_an_unreachable_or_untrusted_authority_is_a_transport_failure():
    fake = MediationContractFake()

    def untrusted(request: httpx.Request) -> httpx.Response:
        # What httpx raises when the origin's certificate is not trusted; the
        # text carries the token to show it never reaches the outcome.
        raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] {PAYEE_TOKEN}",
                                 request=request)

    outcome = check_mediation_access([credential(fake)], origin(fake),
                                     transport=Recording(fake, untrusted).transport())

    assert outcome.step == "transport"
    assert PAYEE_TOKEN not in outcome.json_line()


def test_an_answer_outside_the_contract_is_a_transport_failure():
    fake = MediationContractFake()

    def off_contract(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"cases": "not a list"})

    outcome = check_mediation_access([credential(fake)], origin(fake),
                                     transport=Recording(fake, off_contract).transport())

    assert outcome.step == "transport"
    assert outcome.detail == "mediation authority answered outside its published contract"


def test_a_refused_token_is_reported_with_the_authoritys_code():
    fake = MediationContractFake()
    refused = credential(fake, api_key=SecretStr("token-the-authority-does-not-know"))

    outcome = check_mediation_access([refused], origin(fake),
                                     transport=Recording(fake).transport())

    assert (outcome.step, outcome.code) == ("refused", "authentication_required")
    body = json.loads(outcome.json_line())
    assert body["code"] == "authentication_required"
    assert "token-the-authority-does-not-know" not in outcome.json_line()


def test_no_outcome_carries_a_token(tmp_path: Path):
    fake = MediationContractFake()
    padded = "  padded-token-canary  "
    unknown = "unknown-token-canary"

    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused {PAYEE_TOKEN}", request=request)

    outcomes = [
        check_mediation_access([credential(fake)], origin(fake),
                               transport=Recording(fake).transport()),
        check_mediation_access([credential(fake, ca_bundle_path=str(tmp_path / "none.pem"))],
                               origin(fake), transport=Recording(fake).transport()),
        check_mediation_access([credential(fake, api_key_env=TOKEN_ENV)], origin(fake),
                               environment={TOKEN_ENV: padded},
                               transport=Recording(fake).transport()),
        check_mediation_access([credential(fake)], origin(fake),
                               transport=Recording(fake, lost).transport()),
        check_mediation_access([credential(fake, api_key=SecretStr(unknown))], origin(fake),
                               transport=Recording(fake).transport()),
    ]

    assert [outcome.step for outcome in outcomes] == [
        None, "configuration", "credential", "transport", "refused",
    ]
    for line in (outcome.json_line() for outcome in outcomes):
        assert PAYEE_TOKEN not in line
        assert padded.strip() not in line
        assert unknown not in line


@pytest.mark.parametrize("value", ["mediation.example", "https://mediation.example/cases",
                                   "https://user@mediation.example", "https://", ""])
def test_a_malformed_origin_is_the_callers_error(value):
    fake = MediationContractFake()

    with pytest.raises(ValueError):
        check_mediation_access([credential(fake)], value)
    with pytest.raises(ValueError):
        authority_origin(value)


def test_an_unreadable_configuration_is_a_configuration_failure():
    fake = MediationContractFake()

    def unreadable() -> list[DisputeCredential]:
        raise ValueError(f"DisputeCredential is invalid near {PAYEE_TOKEN}")

    outcome = check_configured_mediation_access(unreadable, origin(fake))

    assert outcome.step == "configuration"
    assert PAYEE_TOKEN not in outcome.json_line()


def test_the_origin_is_validated_before_the_configuration_is_read():
    read: list[bool] = []

    def credentials() -> list[DisputeCredential]:
        read.append(True)
        return []

    with pytest.raises(ValueError):
        check_configured_mediation_access(credentials, "not an origin")
    assert read == []


async def _file_as_payer(fake: MediationContractFake) -> None:
    authority = DisputeAuthority.model_validate(fake.authority)
    payer = MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr(PAYER_TOKEN)),
        transport=fake.transport(),
    )
    async with payer:
        await payer.file(Filing.model_validate(fake.data["filing"]["request"]),
                         idempotency_key="access-check-filing")
