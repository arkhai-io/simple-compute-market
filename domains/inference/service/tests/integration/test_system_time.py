"""The inference service's time: its setting, its signed time route and status.

The real `main.app`, composed under ``time.source``, driven through the family's
authority client signed as the operator's `admin` or as the gateway. The client
and the service read this process's one time source, so a setting moves both.
"""

from __future__ import annotations

import os
import subprocess
import sys

import httpx
import injected_time
import pytest
from arkhai_api_client import AuthorityClient, AuthorityError
from arkhai_api_contracts import operations
from arkhai_api_contracts.routes import ADMIN_ROLE, SERVICE_ROLE
from arkhai_inference.label import INFERENCE_LABEL
from injected_time import InjectedTime
from market_identity import EMPTY_BODY, TrustedIdentitySet, canonical_json

from tests.integration.signed_service import (
    AUTHORITY,
    GATEWAY_SIGNER,
    OPERATOR_SIGNER,
    load_signed_app,
    signed_headers,
    unload_service_modules,
)

T = 1794822300


@pytest.fixture
def composed(tmp_path, monkeypatch):
    """Compose the service under ``time.source``, restoring the process source."""
    before = injected_time.installed()

    def compose(source: str | None):
        if source is None:
            monkeypatch.delenv("INFERENCE_TIME__SOURCE", raising=False)
        else:
            monkeypatch.setenv("INFERENCE_TIME__SOURCE", source)
        return load_signed_app(tmp_path, monkeypatch)

    yield compose
    unload_service_modules()
    injected_time.install(before)


def _client(app, *, signer, role: str) -> AuthorityClient:
    return AuthorityClient(
        "http://inference-service",
        label=INFERENCE_LABEL,
        transport=httpx.ASGITransport(app=app),
        signer=signer,
        expected_authorities=TrustedIdentitySet(identities=(AUTHORITY.identity,)),
        caller_role=role,
    )


async def test_an_injected_service_is_set_by_its_administrator_and_reports_it(composed):
    app = composed("injected")
    injected_time.install(InjectedTime(start=T))
    admin = _client(app, signer=OPERATOR_SIGNER, role=ADMIN_ROLE)

    before = await admin.get_system_status()
    answer = await admin.set_time(T + 900)
    with pytest.raises(AuthorityError) as backward:
        await admin.set_time(T)

    assert before == {"time": {"source": "injected", "now": T}}
    assert answer == {"source": "injected", "now": T + 900}
    assert (backward.value.status_code, backward.value.reason) == (409, "time_moves_forward")
    assert await admin.get_system_status() == {"time": {"source": "injected", "now": T + 900}}


async def test_the_gateway_cannot_set_or_read_the_time(composed):
    app = composed("injected")
    injected_time.install(InjectedTime(start=T))
    gateway = _client(app, signer=GATEWAY_SIGNER, role=SERVICE_ROLE)

    with pytest.raises(AuthorityError) as refused:
        await gateway.set_time(T + 900)
    with pytest.raises(AuthorityError) as unread:
        await gateway.get_system_status()

    assert (refused.value.status_code, unread.value.status_code) == (403, 403)
    assert injected_time.now() == T


async def test_the_composed_service_admits_the_time_setting_alone_outside_the_skew(composed):
    """A setting signed 900 s ahead of the service is admitted and moves it; a
    status read signed there is refused. Raw requests, since the typed client
    signs at this process's instant, the service's own."""
    app = composed("injected")
    injected_time.install(InjectedTime(start=T))

    def ahead(method: str, operation: str, body=EMPTY_BODY) -> dict[str, str]:
        return signed_headers(
            signer=OPERATOR_SIGNER, role=ADMIN_ROLE, method=method, operation=operation,
            resource="", body=body, timestamp=T + 900,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inference-service"
    ) as raw:
        status = await raw.get(
            "/api/v1/system/status", headers=ahead("GET", operations.SYSTEM_STATUS)
        )
        setting = await raw.post(
            "/api/v1/system/time",
            content=canonical_json({"now": T + 900}),
            headers={
                "Content-Type": "application/json",
                **ahead("POST", operations.SYSTEM_TIME, {"now": T + 900}),
            },
        )

    assert status.status_code == 403
    assert setting.status_code == 200
    assert injected_time.now() == T + 900


async def test_a_wall_time_service_serves_no_time_route_and_reports_wall(composed):
    admin = _client(composed(None), signer=OPERATOR_SIGNER, role=ADMIN_ROLE)

    assert await admin.get_system_status() == {"time": {"source": "wall"}}
    with pytest.raises(AuthorityError) as missing:
        await admin.set_time(T)
    assert missing.value.status_code == 404


def test_a_service_started_with_a_misspelled_source_refuses_naming_it():
    started = subprocess.run(
        [sys.executable, "-c", "import inference_service.main"],
        env={**os.environ, "INFERENCE_TIME__SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource: time.source is \"wall\" or \"injected\", not 'injectd'" in (
        started.stderr
    )
