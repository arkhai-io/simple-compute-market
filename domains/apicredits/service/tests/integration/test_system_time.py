"""The credits service's time: its setting, its signed time route and status.

The real `main.app`, composed fresh from configuration written for each test,
as `test_signed_authority` composes it, with ``time.source`` stated through the
loader's override layer: an injected composition mounts the time route, a wall
one mounts none. Every request goes through the storefront's credits client,
signed as the operator's `admin` or as another role. The client and the service
read this process's one time source, so a setting moves both, and the answer,
signed at the instant set, verifies.

Keys and principals are deterministic development fixtures, never used on a
public network.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import injected_time
import pytest
from arkhai_apicredits.settlement.credits_client import (
    ADMIN_ROLE,
    SYSTEM_STATUS_OPERATION,
    SYSTEM_TIME_OPERATION,
    CreditsServiceClient,
    CreditsServiceError,
)
from injected_time import InjectedTime
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    canonical_json,
    sign_request,
)

from .test_signed_authority import (
    _MODULES,
    AUTHORITY_SEED,
    GATED_SIGNER,
    OPERATOR_SIGNER,
    _load_app,
)

T = 1794822300
AUTHORITY = TrustedIdentitySet(identities=(Ed25519Signer(AUTHORITY_SEED).identity,))


@pytest.fixture
def composed(tmp_path: Path, monkeypatch):
    """Compose the service under ``time.source``, restoring the process source."""
    before = injected_time.installed()

    def compose(source: str | None) -> Any:
        if source is None:
            monkeypatch.delenv("APICREDITS_TIME__SOURCE", raising=False)
        else:
            monkeypatch.setenv("APICREDITS_TIME__SOURCE", source)
        return _load_app(tmp_path, monkeypatch, with_identity=True)

    yield compose
    for name in _MODULES:
        sys.modules.pop(name, None)
    injected_time.install(before)


def _client(app, *, signer, role: str) -> CreditsServiceClient:
    return CreditsServiceClient(
        "http://credits-service",
        transport=httpx.ASGITransport(app=app),
        signer=signer,
        expected_authorities=AUTHORITY,
        caller_role=role,
    )


async def test_an_injected_service_is_set_by_its_administrator_and_reports_it(composed):
    """`api-credits`' "The lane sets the credits service's time"."""
    main = composed("injected")
    # The composition installed an injected source frozen at the wall instant
    # it started and mounted the route; the scenario's own source, at T,
    # replaces it, read by the route and the client alike.
    injected_time.install(InjectedTime(start=T))
    admin = _client(main.app, signer=OPERATOR_SIGNER, role=ADMIN_ROLE)

    before = await admin.get_system_status()
    answer = await admin.set_time(T + 900)
    after = await admin.get_system_status()
    with pytest.raises(CreditsServiceError) as backward:
        await admin.set_time(T)
    with pytest.raises(CreditsServiceError) as invalid:
        await admin.set_time(True)  # type: ignore[arg-type]
    held = await admin.get_system_status()

    assert before == {"time": {"source": "injected", "now": T}}
    assert answer == {"source": "injected", "now": T + 900}
    assert after == {"time": {"source": "injected", "now": T + 900}}
    assert (backward.value.status_code, backward.value.reason) == (409, "time_moves_forward")
    assert (invalid.value.status_code, invalid.value.reason) == (422, "invalid_time")
    assert held == {"time": {"source": "injected", "now": T + 900}}


async def test_a_gated_service_cannot_set_the_time(composed):
    """`api-credits`' "A gated service tries to set the time"."""
    main = composed("injected")
    injected_time.install(InjectedTime(start=T))
    gated = _client(main.app, signer=GATED_SIGNER, role="service")

    with pytest.raises(CreditsServiceError) as refused:
        await gated.set_time(T + 900)
    with pytest.raises(CreditsServiceError) as unread:
        await gated.get_system_status()

    assert refused.value.status_code == 403
    assert unread.value.status_code == 403
    assert injected_time.now() == T


def _skewed_admin_request(operation: str, body: Any, at: int) -> dict[str, Any]:
    """A request signed by the operator at ``at``, as a harness that has moved
    its own source signs it: the canonical client signs at this process's
    instant, the service's own, and cannot sign at another."""
    authenticated = sign_request(
        signer=OPERATOR_SIGNER,
        envelope=RequestEnvelope(
            role=ADMIN_ROLE,
            principal=OPERATOR_SIGNER.identity,
            method="POST" if body is not EMPTY_BODY else "GET",
            operation=operation,
            resource="",
            request_id=uuid.uuid4().hex,
            timestamp=at,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": authenticated.protocol,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }


async def test_the_composed_service_admits_the_time_setting_alone_outside_the_skew(
    composed,
):
    """D14 as the composition wires it: a setting signed 900 s ahead of the
    service is admitted and moves it; a status read signed there is refused.
    Raw requests, as a rejection-path test's are, asserting statuses only."""
    main = composed("injected")
    injected_time.install(InjectedTime(start=T))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://credits-service"
    ) as raw:
        status = await raw.get(
            "/api/v1/system/status",
            headers=_skewed_admin_request(SYSTEM_STATUS_OPERATION, EMPTY_BODY, T + 900),
        )
        setting = await raw.post(
            "/api/v1/system/time",
            content=canonical_json({"now": T + 900}),
            headers={
                "Content-Type": "application/json",
                **_skewed_admin_request(SYSTEM_TIME_OPERATION, {"now": T + 900}, T + 900),
            },
        )

    assert status.status_code == 403
    assert setting.status_code == 200
    assert injected_time.now() == T + 900


async def test_a_wall_time_service_serves_no_time_route_and_reports_wall(composed):
    main = composed(None)
    admin = _client(main.app, signer=OPERATOR_SIGNER, role=ADMIN_ROLE)

    status = await admin.get_system_status()
    with pytest.raises(CreditsServiceError) as missing:
        await admin.set_time(T)

    assert status == {"time": {"source": "wall"}}
    assert missing.value.status_code == 404


async def test_an_injected_service_announces_its_time_at_startup(composed, caplog):
    main = composed("injected")
    with caplog.at_level(logging.INFO, logger=main.logger.name):
        async with main.app.router.lifespan_context(main.app):
            pass

    assert any(
        "time.source" in record.getMessage() and "injected" in record.getMessage()
        for record in caplog.records
    ), [record.getMessage() for record in caplog.records]


def test_a_service_started_with_a_misspelled_source_refuses_naming_it():
    """The composition root itself, started in a process of its own with
    ``time.source`` set through the loader's override layer."""
    started = subprocess.run(
        [sys.executable, "-c", "import apicredits_service.main"],
        env={**os.environ, "APICREDITS_TIME__SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource: time.source is \"wall\" or \"injected\", not 'injectd'" in (
        started.stderr
    )
