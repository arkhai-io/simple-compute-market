"""The run's dispute authority, for the payment scenarios' case stages and buyers.

A run names its mediation target in MEDIATION.SERVICE_URL, the origin of the
dispute authority the registries recommend, which the case stages reach through
the authority their Agreement pins. A lane that runs its own target, the
mediation lane double, also sets MEDIATION.LANE_OWNED: an unready target is then
the lane's own failure and fails setup by name, where an external target that
is not ready, or none at all, blocks the stages that need it. A live
verification scenario refuses a lane-owned target outright (``live_mediation``):
a double yields no live evidence.

The buyer's mediation token is a setting, MEDIATION.BUYER_API_KEY, never a
variable of the runner's environment: the harness writes the buyer's
``[[DisputeCredential]]`` naming the variable MEDIATION.API_KEY_ENV names, and
hands the token to each ``market`` process under that variable, as the buyer's
own credential resolves it. The credential is bound to the authority's identity,
MEDIATION.ACCOUNT and MEDIATION.RECORD_KEY at the target's origin, and trusts
MEDIATION.CA_BUNDLE_PATH alone when one is set.

A target whose origin resolves only inside its topology is reached through
MEDIATION.PROXY_URL, an HTTP proxy the run can reach, such as a forward to one in
the topology. The harness's own requests to the target go through it. The buyer
processes it starts receive it as their HTTPS_PROXY, in both cases, with
loopback excluded, so every HTTPS request they make outside loopback goes
through it; the forwards the harness gives them are on loopback. The origin, and
the certificate verified against it, stay the target's own.

No buyer command files a case on a deal still delivering, so where a scenario
needs one the harness files as the buyer itself (``file_as_buyer``): through the
mediation kit's dispute adapter over its typed client, as the buyer's lifecycle
submits a filing, never a hand-built request. A scenario reads what the
authority recorded the same way, as the buyer through that client
(``read_record``), each entry verified against the record key the Agreement pins.
"""

from __future__ import annotations

import asyncio
import hashlib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import injected_time
import pytest
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import wire
from market_arkhai_mediation.models import ReadAfter
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, submit_dispute,
)
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_deal_lifecycle_contracts.models import LifecycleCommand, LifecycleOutcome, Rejected
from market_identity import canonical_json
from pydantic import SecretStr

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import _toml_quote
from tests.e2e.roles.helpers.payments import target_ready

#: The interface every authority the harness files with serves.
INTERFACE = "arkhai.mediation.v1"
_TARGET_KEY = "SERVICE_URL"
# What a configured target needs, whoever runs it: the identity the buyer's
# credential binds to and the variable its token is handed over under.
_REQUIRED_KEYS = ("ACCOUNT", "RECORD_KEY", "API_KEY_ENV")
# What a lane-owned target, a double with controls, needs besides.
_LANE_OWNED_KEYS = ("CONTROL_TOKEN",)


@dataclass(frozen=True)
class MediationTarget:
    """The run's mediation target, as its settings name it."""

    service_url: str
    account: str
    record_key: str
    api_key_env: str
    lane_owned: bool
    ca_bundle_path: str | None = None
    buyer_api_key: str | None = None
    control_token: str | None = None
    proxy_url: str | None = None


def mediation_setting(name: str, default: object = "") -> object:
    """Read MEDIATION.<name> from the E2E settings."""
    value = settings.get(f"MEDIATION.{name}", default)
    return default if value is None or (isinstance(value, str) and not value.strip()) else value


def _flag(name: str) -> bool:
    """MEDIATION.<name> as a strict boolean; a settings file may hold "false"."""
    value = mediation_setting(name, False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return text == "true"
    pytest.fail(f"MEDIATION.{name} must be true or false, not {value!r}")


def mediation_if_configured(
    *, ready: Callable[[str], bool] | None = None,
) -> MediationTarget | None:
    """The run's mediation target, or None when the run names none and claims
    none as its own.

    With a target named, a missing setting the run supplies itself fails,
    naming it, before the target is asked whether it is ready; then an unready
    target blocks the caller, unless it is the lane's own, which fails it,
    naming the target. Readiness is the target's ``/health`` under its CA
    bundle unless ``ready`` is given.
    """
    lane_owned = _flag("LANE_OWNED")
    if not mediation_setting(_TARGET_KEY):
        if lane_owned:
            pytest.fail(f"MEDIATION.LANE_OWNED is set but MEDIATION.{_TARGET_KEY} is not configured")
        return None
    required = _REQUIRED_KEYS + (_LANE_OWNED_KEYS if lane_owned else ())
    missing = [key for key in required if not mediation_setting(key)]
    if missing:
        pytest.fail(f"MEDIATION.{', MEDIATION.'.join(missing)} not configured")
    target = MediationTarget(
        service_url=str(mediation_setting(_TARGET_KEY)).strip().rstrip("/"),
        account=str(mediation_setting("ACCOUNT")),
        record_key=str(mediation_setting("RECORD_KEY")),
        api_key_env=str(mediation_setting("API_KEY_ENV")),
        lane_owned=lane_owned,
        ca_bundle_path=str(mediation_setting("CA_BUNDLE_PATH")) or None,
        buyer_api_key=str(mediation_setting("BUYER_API_KEY")) or None,
        control_token=str(mediation_setting("CONTROL_TOKEN")) or None,
        proxy_url=str(mediation_setting("PROXY_URL")).strip() or None,
    )
    if ready is None:
        ready = partial(target_ready, ca_bundle=target.ca_bundle_path, proxy=target.proxy_url)
    if not ready(target.service_url):
        # A stopped forward or a wrong proxy reads as an unready target; name the path.
        where = target.service_url + (f" through {target.proxy_url}" if target.proxy_url else "")
        if lane_owned:
            pytest.fail(f"the lane's own mediation service at {where} is not ready")
        pytest.skip(f"blocked: mediation service at {where} is not ready")
    return target


def configured_mediation(*, ready: Callable[[str], bool] | None = None) -> MediationTarget:
    """The run's mediation target for a stage that files with it: a blocked
    skip naming the setting when the run names none."""
    target = mediation_if_configured(ready=ready)
    if target is None:
        pytest.skip(f"blocked: MEDIATION.{_TARGET_KEY} not configured")
    return target


def live_mediation(*, ready: Callable[[str], bool] | None = None) -> MediationTarget:
    """The mediation target of a live verification scenario that files a case,
    as ``configured_mediation`` gives it, unless it is a lane's own.

    A lane-owned target (MEDIATION.LANE_OWNED) is a mediation double, which
    yields no live evidence, so the scenario is a blocked skip naming it
    before anything else is read. A live dispute scenario reads the
    authority's record as the buyer, so a run stating no buyer token fails
    naming MEDIATION.BUYER_API_KEY before anything is bought.
    """
    if _flag("LANE_OWNED"):
        target = mediation_setting(_TARGET_KEY) or "(none named)"
        pytest.skip(f"blocked: the mediation target {target} is a lane's own double "
                    "(MEDIATION.LANE_OWNED), which yields no live evidence")
    target = configured_mediation(ready=ready)
    if not target.buyer_api_key:
        pytest.fail("MEDIATION.BUYER_API_KEY not configured: a live dispute scenario reads "
                    "the authority's record as the buyer")
    return target


def pinned_authority_difference(target: MediationTarget,
                                agreement: Mapping[str, Any]) -> str | None:
    """How the dispute authority the accepted Agreement pins differs from the
    run's target, or None when it is the target's. The buyer's credential and
    the record reads are bound to the target's identity, so an Agreement
    pinning another authority — one the buyer's registry recommended instead —
    is read by no client the harness holds. An accepted Agreement naming no
    dispute authority at all is the market's failure, not the topology's, and
    fails here."""
    terms = decode_terms(agreement["settlement"]["lifecycle"])
    assert terms is not None, "the accepted Agreement names no dispute authority"
    pinned = terms.adjudication.dispute.identity
    ours = (INTERFACE, target.service_url, target.account, target.record_key)
    if pinned == ours:
        return None
    return f"the Agreement pins the dispute authority {pinned}, not the run's target {ours}"


#: The hosts a buyer process reaches directly when the run names a proxy: the
#: forwards the harness gives it on loopback.
_LOOPBACK = "127.0.0.1,localhost,::1"


def buyer_mediation_environment(target: MediationTarget | None) -> dict[str, str]:
    """For the buyer processes the harness runs: the buyer's mediation token
    under the variable its credential names, and with MEDIATION.PROXY_URL the
    proxy their HTTP client sends every HTTPS request outside loopback through;
    empty when the run names no target. Both cases of each proxy variable are
    set, since an inherited lowercase one would otherwise win."""
    if target is None:
        return {}
    environment = {target.api_key_env: target.buyer_api_key} if target.buyer_api_key else {}
    if target.proxy_url:
        environment |= {"HTTPS_PROXY": target.proxy_url, "https_proxy": target.proxy_url,
                        "NO_PROXY": _LOOPBACK, "no_proxy": _LOOPBACK}
    return environment


def buyer_dispute_credential_toml(target: MediationTarget | None) -> tuple[str, ...]:
    """The buyer's ``[[DisputeCredential]]`` for the target's authority, naming
    its token's variable rather than stating it; nothing when the run names no
    target."""
    if target is None:
        return ()
    lines = (
        "[[DisputeCredential]]",
        f"interface = {_toml_quote(INTERFACE)}",
        f"origin = {_toml_quote(target.service_url)}",
        f"account = {_toml_quote(target.account)}",
        f"record_key = {_toml_quote(target.record_key)}",
        f"api_key_env = {_toml_quote(target.api_key_env)}",
    )
    if target.ca_bundle_path:
        lines += (f"ca_bundle_path = {_toml_quote(target.ca_bundle_path)}",)
    return lines


def _buyer_credential(target: MediationTarget) -> MediationCredential:
    """The buyer's credential at the target, bound to the target's identity."""
    if not target.buyer_api_key:
        pytest.fail("MEDIATION.BUYER_API_KEY not configured")
    return MediationCredential(
        (INTERFACE, target.service_url, target.account, target.record_key),
        token=SecretStr(target.buyer_api_key),
    )


def target_transport(
    target: MediationTarget, transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncBaseTransport | None:
    """The transport the harness's mediation client uses: ``transport`` when a
    test gives one; through MEDIATION.PROXY_URL when the run names one,
    verifying the target's certificate under its CA bundle alone, as the client
    would; otherwise none, the client's own."""
    if transport is not None or not target.proxy_url:
        return transport
    verify: ssl.SSLContext | bool = (
        ssl.create_default_context(cafile=target.ca_bundle_path) if target.ca_bundle_path else True
    )
    return httpx.AsyncHTTPTransport(proxy=target.proxy_url, verify=verify)


def read_record(
    target: MediationTarget, *, negotiation_id: str, transaction: str,
    agreement: Mapping[str, Any], page_size: int = 1000,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Every entry of the Agreement's signed record, read as the buyer; the
    entries as JSON, in sequence.

    The read is the mediation kit's public client's, the one either party's
    adapter reads with, page by page from the start, each page asking for up to
    ``page_size`` entries: each entry is verified against the authority's record
    key the Agreement pins and against its place in the sequence before it is
    returned, and an entry failing it raises the kit's record verification error.
    ``transport`` replaces the network, for a test.
    """
    terms = decode_terms(agreement["settlement"]["lifecycle"])
    assert terms is not None, f"the accepted Agreement of {negotiation_id} names no dispute authority"
    authority = terms.adjudication.dispute
    digest = hashlib.sha256(canonical_json(dict(agreement))).hexdigest()

    async def read() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        async with MediationClient(authority, _buyer_credential(target),
                                   transport=target_transport(target, transport),
                                   ca_bundle=target.ca_bundle_path) as client:
            after = 0
            while True:
                page = await client.read_record(ReadAfter.model_validate({
                    "agreement": digest, "after": after, "limit": page_size,
                }), transaction=transaction)
                entries.extend(wire(signed)["entry"] for signed in page.entries)
                if not page.has_more:
                    return entries
                after = page.next_after

    return asyncio.run(read())


def file_as_buyer(
    target: MediationTarget, *, negotiation_id: str, transaction: str,
    agreement: Mapping[str, Any], store: Path, ended_at: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LifecycleOutcome:
    """File a delivery-end claim as the buyer on the accepted deal; the dispute
    adapter's lifecycle outcome.

    The claim is the one the buyer's ``market end`` sends: delivery ended now,
    delivered, caused by the payer. The client is bound to the target's
    identity, so an Agreement pinning another authority fails here before
    anything is sent, and authenticates with the buyer's token, trusting the
    target's CA bundle alone. The adapter takes its single-writer check and
    idempotency keys from a buyer evidence store over ``store``, a directory of
    the caller's own, as the buyer's lifecycle supplies one. An accepted outcome's
    filing answer carries the case reference and each part's hold. ``transport``
    replaces the network, for a test.
    """
    credential = _buyer_credential(target)
    terms = decode_terms(agreement["settlement"]["lifecycle"])
    assert terms is not None, f"the accepted Agreement of {negotiation_id} names no dispute authority"
    binding = DisputeBinding(negotiation_id, transaction, terms.adjudication.dispute)
    intent = DeliveryEndIntent(
        ended_at=injected_time.now() if ended_at is None else ended_at, delivered=True,
        cause="payer",
    )

    async def file() -> LifecycleOutcome:
        async with MediationClient(binding.authority, credential,
                                   transport=target_transport(target, transport),
                                   ca_bundle=target.ca_bundle_path) as client:
            adapter = MediationAdapter(binding, dict(agreement), client)
            request = adapter.build_request(intent)
            if isinstance(request, Rejected):
                return request
            command = LifecycleCommand(
                negotiation_id=negotiation_id, kind="dispute",
                # The harness files at most once per deal, so the key names the deal.
                operation_key=hashlib.sha256(canonical_json(
                    {"harness": "buyer filing", "negotiation_id": negotiation_id},
                )).hexdigest(),
                payload=request.model_dump(mode="json"),
            )
            return await submit_dispute(
                command, binding, DisputeAdapterTable([(INTERFACE, lambda _: adapter)]),
                FileEvidenceStore(store),
            )

    return asyncio.run(file())
