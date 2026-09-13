"""Fixtures for the full-deal e2e scenario tests.

All fixtures are ``module``-scoped so the ``DealState`` object persists
across the 16 sequential tests in ``test_full_deal.py``.  Each test reads
from and writes to ``DealState``; later tests skip automatically if an
earlier required field was never populated (indicating the earlier test
failed).

Clients
-------
* ``storefront_client``        — canonical ``SyncStorefrontClient``, buyer key
* ``storefront_admin_client``  — same, seller key + admin key
* ``registry_client``          — ``SyncRegistryClient`` from the registry-client wheel
* ``provisioning_client``      — ``SyncProvisioningClient`` signing as the
  provisioning admin principal
* ``provisioning_test_client`` — thin sync wrapper over ``/test/*`` endpoints

Settings access uses the ``settings.SECTION.KEY`` attribute pattern
(uppercase, dot-separated) consistent with the rest of the project's conftest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import pytest

import uuid
from datetime import datetime, timezone

from market_identity import (
    EMPTY_BODY,
    Identity,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    create_signer,
    sign_request,
)
from src.settings import settings
from src.provisioning_test_client import ProvisioningTestClient
from tests.e2e.roles.helpers.domain_deal import DomainDealState, require_state

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DealState — mutable carrier shared across all tests in the module
# ---------------------------------------------------------------------------

@dataclass
class DealState(DomainDealState):
    """VM-specific observations layered over the shared deal lifecycle."""
    domain_identity: str = "vms.compute"
    # Phase 0 — service readiness
    _storefront_healthy: bool = False
    _registry_reachable: bool = False
    _provisioning_healthy: bool = False
    _provisioning_mock_mode: bool = False
    _negotiation_strategy_viable: bool = False
    _resources_seeded: bool = False
    _alkahest_configured: bool = False
    _provisioning_storefront_ok: bool = False
    # Phase 2 — listing creation (paused)
    seller_listing_id: Optional[str] = None
    # Phase 3 — registry publication
    _registry_validate_passed: bool = False
    resume_confirmed: bool = False
    # Phase 5 — negotiation
    _evaluate_negotiate_passed: bool = False
    negotiation_id: Optional[str] = None
    negotiation_terminal_state: Optional[str] = None
    agreed_amount: Optional[int] = None
    # Buyer-CLI run-log identity from `market negotiate`; consumed by
    # `market settle --from <run_id>` in phase 08. Sentinel for the
    # "negotiation produced a usable agreed outcome" precondition.
    buyer_run_id: Optional[str] = None
    # Phase 7 — provisioning gate (escrow created by `market settle`
    # in the buyer-CLI flow; created inline in the synthetic-buyer flow)
    provisioning_gate_armed: bool = False
    # Phase 8 — settle subprocess + on-chain escrow uid
    real_escrow_uid: Optional[str] = None
    # Buyer-CLI scenarios only: carries the background `market settle`
    # subprocess handle so phase 09b can wait for its clean exit and the
    # module teardown can terminate it if leftover. Unused by the
    # synthetic-buyer scenario.
    settle_run_handle: Optional[Any] = None
    # Synthetic-buyer (test_full_deal.py) only: 08a evaluate-settle
    # dry-run capture; the buyer-CLI scenario reads vm_host from the
    # lease instead (see below).
    _evaluate_settle_vm_host: Optional[str] = None
    _evaluate_settle_vm_target: Optional[str] = None
    _evaluate_settle_passed: bool = False
    # Synthetic-buyer only: phase 09a evaluate-provisioning-job dry-run
    _provision_job_evaluated: bool = False
    # Phase 8 — settlement
    settlement_submitted: bool = False
    # Phase 9 — provisioning completion
    provisioning_result_injected: bool = False
    lease_id: Optional[str] = None
    lease_status: Optional[str] = None
    # vm_host captured from the lease in 09c; used by 10a/11b to arm
    # the check-job mock rule (was previously sourced from the
    # 08a evaluate-settle dry-run, now dropped from this flow).
    vm_host: Optional[str] = None
    settlement_status: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    seller_listing_final_status: Optional[str] = None
    # Phase 10-11 — explicit interruption and fulfillment teardown lifecycle
    _termination_requested: bool = False
    # Durable fulfillment identity, captured at settlement (stage 08b) from
    # the settle-status response's ``fulfillment_id`` -- the buyer-facing
    # path no longer surfaces a raw Ansible ``provisioning_job_id`` (always
    # None for a fulfillment on the durable path; see
    # ``core_storefront.models.settle_models.SettleStatusResponse``).
    # Reused through phases 9-11 for status polling and teardown.
    fulfillment_id: Optional[str] = None
    # Reserved resource, captured at stage 09c from the admin-only
    # DealLease view (``get_capacity_reservation``), never from a
    # buyer-facing response -- ``resource_id``/``vm_host`` are
    # intentionally opaque across the ordinary reservation boundary (see
    # openspec/specs/site-capacity/spec.md's "Capacity accounting is
    # private to the site authority" requirement). Admin introspection is
    # a legitimate, separate channel from that opacity guarantee.
    reserved_resource_id: Optional[str] = None
    # Mode-agnostic lease view (DealLease) resolved in 09c: a vm_leases
    # row in embedded-capacity mode, a site-ledger reservation in remote
    # mode. Phases 10-11 drive the expiry lifecycle through it.
    deal_lease: Optional[Any] = None




def delete_mock_rules_if_present(provisioning_test_client, *rule_ids: str) -> None:
    """Best-effort cleanup for stateful provisioning mock rules.

    The mock-rule service preserves insertion order. When multiple e2e
    scenarios run in one pytest process against one compose stack, a stale
    broad ``{"vm_action": "create"}`` rule can match before the rule that the
    current scenario just armed. Delete known scenario rule ids before arming
    a new create rule so each scenario controls its own evaluation order.
    """
    for rule_id in rule_ids:
        try:
            provisioning_test_client.delete_mock_rule(rule_id)
        except Exception as exc:
            log.debug("[conftest] Could not delete mock rule %s: %s", rule_id, exc)


# ---------------------------------------------------------------------------
# Settings helpers — use attribute access, consistent with tests/conftest.py
# ---------------------------------------------------------------------------

def _require_setting(value: Any, name: str) -> str:
    """Return value as str, or skip if empty/missing."""
    if not value:
        pytest.skip(f"{name} not configured")
    return str(value)




def signed_listing_read_headers(listing_id: str) -> dict[str, str]:
    """v2 headers for a registry `GET /listings/{id}` as the buyer.

    The route authenticates and admits `buyer`, `seller`, or `service`; an
    unsigned read is refused with `context_mismatch` rather than answered. The
    reads below stay raw rather than going through the typed client because
    they assert on the status code itself — 200 against 404 is what
    distinguishes "published here" from "not published here", and the client
    raises instead of reporting it.

    The signed body must match what the route hashes, which for a query-less
    GET is an empty query list rather than an empty body.
    """
    signer = _signer(
        "eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"
    )
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="buyer",
            principal=signer.identity,
            method="GET",
            operation="listing.get",
            resource=listing_id,
            request_id=uuid.uuid4().hex,
            timestamp=int(datetime.now(timezone.utc).timestamp()),
            body_hash=canonical_body_hash({"query": []}),
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

def capacity_source_for(resource: dict[str, Any], *, site_id: str | None = None) -> dict[str, Any]:
    """Capacity provenance bound to the listing resource being published.

    The storefront refuses a listing whose declared source disagrees with its
    resource on pool, resource, or GPU count, so this is derived from the
    resource rather than restated alongside it — a hand-written copy is a
    second place that has to stay in sync.
    """
    source: dict[str, Any] = {
        "site_id": site_id or str(settings.SELLER.get("site_id", "default") or "default"),
        "gpu_count": resource.get("gpu_count", 1),
    }
    if resource.get("pool_id"):
        source["pool_id"] = resource["pool_id"]
    else:
        source["resource_id"] = resource["resource_id"]
    return source


# ---------------------------------------------------------------------------
# Identity helpers
#
# Every authenticated route resolves the caller's principal against the trust
# set bound to the role the request asserts, so a client carries exactly one
# role and the credential of the principal authorized to hold it. One client
# per role, named for the role, keeps that visible at the call site and in the
# service's request logs.
# ---------------------------------------------------------------------------

def _signer(scheme: Any, credential: Any, name: str):
    return create_signer(
        str(scheme or "eip191"),
        _require_setting(credential, name),
    )


def _trust(*identifiers: str, scheme: str = "eip191"):
    return TrustedIdentitySet(
        identities=tuple(
            Identity(scheme=scheme, identifier=str(i)) for i in identifiers
        )
    )


def _publisher_trust():
    """The storefront's publishing principal, pinned for response verification."""

    return _trust(
        _signer(
            settings.SELLER.get("admin_scheme", "eip191"),
            settings.SELLER.PRIVATE_KEY,
            "SELLER.PRIVATE_KEY",
        ).identity.identifier
    )



def _provisioning_admin_signer():
    """Signer for the principal pinned as the provisioning admin identity."""

    return _signer(
        settings.PROVISIONING.get("admin_scheme", "eip191"),
        settings.PROVISIONING.get("admin_credential", ""),
        "PROVISIONING.ADMIN_CREDENTIAL",
    )


def _provisioning_authority_trust():
    """The provisioning service's own signing principal, for response checks."""

    return _trust(
        _require_setting(
            settings.PROVISIONING.get("authority_identifier", ""),
            "PROVISIONING.AUTHORITY_IDENTIFIER",
        ),
        scheme=str(settings.PROVISIONING.get("authority_scheme", "eip191") or "eip191"),
    )


@pytest.fixture(scope="module")
def site_capacity_admin_client():
    """Capacity-admin client for the provisioning site authority.

    The site ledger is a separate store from the host registry: `probe` and
    `reserve` match `CapacityBucket` rows, which only `register_resource`
    creates, and nothing derives one from a registered host. A scenario that
    reserves capacity has to put a resource there.

    Signs as the **storefront** principal, not the provisioning administrator.
    `SiteCapacityAdminClient` asserts the `seller` role, and provisioning binds
    that role to the storefront principal it is configured to serve; the
    administrator is trusted for `admin` and is refused here with
    `Invalid marketplace authentication`. Declaring sellable capacity is a
    seller's act, so the role and the principal agree with what the call means.

    The August fixture passed a shared admin key, under which the caller's
    identity did not matter. It does now, and the two principals are not
    interchangeable.
    """
    from market_site_client import SiteCapacityAdminClient

    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    return SiteCapacityAdminClient(
        url,
        _signer("eip191", settings.SELLER.PRIVATE_KEY, "SELLER.PRIVATE_KEY"),
        _provisioning_authority_trust(),
    )


def advance_storefront(storefront_admin_client, loop: str) -> dict:
    """Run one cycle of a paused storefront loop and return what it reports.

    `loop` is the loop's route name: `claims`, `fulfillment-resume`, or
    `site-projections`. Each calls the operation the timer was already
    invoking, so a stage advances production behaviour rather than a test-only
    path.

    This is the other half of `pause_storefront`. Pausing without advancing
    just stops the system; the pair is what makes ordering assertable -- a
    stage asks for the work it is about to assert on, instead of racing a timer
    that may or may not have run.
    """
    result = storefront_admin_client.admin_run_lifecycle_cycle(loop)
    log.info("[lifecycle] advanced %s: %s", loop, result)
    return result


def pause_storefront(storefront_admin_client) -> bool:
    """Hold the storefront's timer loops idle, and prove they are.

    Pauses the loops only -- trading stays open, so a scenario can pause at its
    readiness stage and still agree a deal.

    Called from a scenario's own stage rather than an autouse fixture: a
    scenario should name the state it depends on, and pausing a service is a
    dependency as much as registering a host is. It also keeps the pause with
    the scenario that wants it -- the API-credits scenario shares this module
    and drives a different storefront, which has no such control.

    Every side effect a scenario asserts on should be one the scenario asked
    for. While the timer loops run, a stage's observation races them: a listing
    reconciled a second later reads differently than one reconciled a second
    earlier. Waiting for the system to settle instead is what
    `docs/development/TESTING.md` forbids, and it cannot establish ordering
    even when it passes.

    Trading is untouched: this holds the loops only, so a scenario can pause
    at its readiness stage and still agree a deal. The response names each
    loop's gate state, which is what lets this assert that the loop a scenario
    depends on actually reached its gate rather than merely that a pause was
    requested.
    """
    result = storefront_admin_client.admin_pause_lifecycle_loops()
    assert result.get("paused") is True, (
        f"storefront did not report its loops paused: {result!r}. An "
        "assertion made now would race the timer loops it was meant to hold."
    )
    loops = result.get("loops") or {}
    not_at_gate = {
        name: state for name, state in loops.items() if state != "paused"
    }
    assert loops and not not_at_gate, (
        f"these loops had not reached a gate when the pause returned: "
        f"{not_at_gate or 'none registered'}. `running` means a cycle that "
        "began before the request is still going, so an assertion made now "
        "would race it."
    )
    log.info("[lifecycle] storefront loops paused; loops=%s", loops)
    return True


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def deal_state() -> DealState:
    return DealState()


@pytest.fixture(scope="module")
def storefront_client():
    """Buyer-role storefront client: the buyer settling its own deal."""
    from storefront_client import SyncStorefrontClient

    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    client = SyncStorefrontClient(
        url,
        _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"),
        caller_role="buyer",
        expected_publishers=_publisher_trust(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def storefront_seller_client():
    """Seller-role storefront client: the principal that publishes listings.

    Separate from the administrator below. The seller signer must itself be a
    pinned publisher, which the client enforces at construction.
    """
    from storefront_client import SyncStorefrontClient

    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    client = SyncStorefrontClient(
        url,
        _signer("eip191", settings.SELLER.PRIVATE_KEY, "SELLER.PRIVATE_KEY"),
        caller_role="seller",
        expected_publishers=_publisher_trust(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def storefront_admin_client():
    """Admin-role storefront client: system controls outside a normal deal.

    The administrator is a distinct principal from the seller, pinned as
    ``Identity.administrators.operator`` in the storefront config. Signing
    these calls as the seller would authenticate as the wrong caller.
    """
    from storefront_client import SyncStorefrontClient

    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    client = SyncStorefrontClient(
        url,
        _signer(
            settings.SELLER.get("admin_scheme", "eip191"),
            settings.SELLER.get("admin_credential", ""),
            "SELLER.ADMIN_CREDENTIAL",
        ),
        caller_role="admin",
        expected_publishers=_publisher_trust(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def registry_client():
    """Buyer-role registry client: discovery reads, as a buyer performs them.

    The registry's vocabulary is ``buyer``, ``seller``, or ``service``; it has
    no administrator. Its reads here are unauthenticated, so the role does not
    gate them — it attributes them, which is why discovery is a buyer.
    """
    from registry_client import SyncRegistryClient

    url = _require_setting(settings.REGISTRY.API_URL, "REGISTRY.API_URL")
    client = SyncRegistryClient(
        url,
        signer=_signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"),
        caller_role="buyer",
        expected_registries=_trust(_require_setting(
            settings.REGISTRY.get("identifier", ""), "REGISTRY.IDENTIFIER"
        )),
        registry_authority=_require_setting(
            settings.REGISTRY.get("authority_id", ""), "REGISTRY.AUTHORITY_ID"
        ),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def registry_seller_client():
    """Seller-role registry client: validating a payload a seller would publish."""
    from registry_client import SyncRegistryClient

    url = _require_setting(settings.REGISTRY.API_URL, "REGISTRY.API_URL")
    client = SyncRegistryClient(
        url,
        signer=_signer("eip191", settings.SELLER.PRIVATE_KEY, "SELLER.PRIVATE_KEY"),
        caller_role="seller",
        expected_registries=_trust(_require_setting(
            settings.REGISTRY.get("identifier", ""), "REGISTRY.IDENTIFIER"
        )),
        registry_authority=_require_setting(
            settings.REGISTRY.get("authority_id", ""), "REGISTRY.AUTHORITY_ID"
        ),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def provisioning_client():
    """Admin-signed SyncProvisioningClient.

    Provisioning authenticates per caller: each request carries the caller's
    marketplace signature plus an asserted role, and the service verifies the
    principal against the durable trust set bound to that role.

    This suite drives provisioning as the **admin** principal, and that is not
    a preference. ``SyncProvisioningClient`` asserts ``admin`` on every request
    and exposes no way to override it, while the service resolves the trust set
    from the asserted role. Signing as the storefront principal would construct
    successfully and then be refused on authorisation, so the credential here
    must be the principal pinned as the provisioning admin identity.

    ``expected_authorities`` pins the service's own signing principal, which is
    a different identity again, so responses are verified as well as requests.
    """
    from vm_provisioning_operator import SyncProvisioningClient

    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    client = SyncProvisioningClient(
        url, _provisioning_admin_signer(), _provisioning_authority_trust()
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def provisioning_test_client():
    """ProvisioningTestClient for /test/* control endpoints.

    Only works when the provisioning service runs with ACTIVE_PROFILES=mock.
    """
    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    with ProvisioningTestClient(
        url,
        signer=_provisioning_admin_signer(),
        expected_authorities=_provisioning_authority_trust(),
        timeout=20.0,
    ) as client:
        yield client


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered(provisioning_client):
    """Idempotently register the e2e ``kvm1`` host in the provisioning service.

    The scenario's seeded resource row declares ``attribute.vm_host=kvm1``,
    so phase 08c's ``/test/evaluate-job`` lookup requires a matching row
    in the provisioning ``hosts`` table. Compose-launched provisioning
    starts with an empty inventory (no ``inventory_ini``/``inventory_path``
    configured); production deployments seed the table via Helm secret
    or a bind-mounted IaC inventory. Inserting the row here keeps the
    e2e scenario hermetic and idempotent across re-runs.

    The credentials are stub values (path-type, fake path) - mock
    provisioning never SSHes into the host, so they never get used.
    Real-host integration tests use a real key path; this fixture is
    only relevant when ``ACTIVE_PROFILES=mock``.
    """
    from vm_provisioning_operator import ProvisioningError
    from vm_provisioning_operator import HostCreate

    host_name = "kvm1"

    try:
        provisioning_client.get_host(host_name)
    except ProvisioningError as exc:
        if exc.status_code != 404:
            pytest.skip(f"Could not probe provisioning host {host_name!r}: {exc}")
    else:
        log.info("[conftest] Provisioning host %r already registered", host_name)
        return

    body = HostCreate(
        name=host_name,
        kvm_host="127.0.0.1",
        ssh_user="stub",
        ssh_key_type="path",
        ssh_key_value="/tmp/stub-e2e-key",
        gpu_count=1,
        enabled=True,
    )
    try:
        provisioning_client.register_host(body)
    except ProvisioningError as exc:
        pytest.skip(f"Could not register provisioning host {host_name!r}: {exc}")
    log.info("[conftest] Registered provisioning host %r", host_name)


@pytest.fixture(scope="module")
def buyer_config() -> dict[str, str]:
    """Buyer wallet credentials for signing negotiate/settle requests."""
    private_key = str(settings.BUYER.PRIVATE_KEY or "")
    wallet_address = str(settings.BUYER.WALLET_ADDRESS or "")
    if not private_key or not wallet_address:
        pytest.skip("BUYER.PRIVATE_KEY / BUYER.WALLET_ADDRESS not configured")
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None) or
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    # rpc_url for on-chain escrow creation (AlkahestClient — ws:// only).
    # Resolved from buyer.chain_rpc_url, then rpc.url, then a localhost default.
    # Local/docker profiles set buyer.chain_rpc_url explicitly to a WebSocket
    # endpoint; the helper coerces http(s) fallback values for staging profiles
    # that only define rpc.url.
    rpc_url = (
        str(settings.BUYER.CHAIN_RPC_URL or "").strip()
        or str(settings.RPC.URL or "").strip()
        or "ws://localhost:8545"
    )
    return {
        "private_key": private_key,
        "wallet_address": wallet_address,
        "ssh_public_key": ssh_public_key,
        "rpc_url": rpc_url,
    }


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    """Seller wallet address — passed as agent_wallet_address to create_order."""
    return _require_setting(settings.SELLER.WALLET_ADDRESS, "SELLER.WALLET_ADDRESS")


# ---------------------------------------------------------------------------
# Teardown — ensure global pause is cleared after each test module run
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def ensure_storefront_resumed(storefront_admin_client):
    """Yield to let the module run; then unconditionally clear global pause if set.

    Safety net in case an unexpected error leaves the storefront paused between
    runs. Admin pause/resume is no longer tested in this module (moved to the
    smoke suite), so this fixture should rarely need to act.
    """
    yield
    try:
        status = storefront_admin_client.get_system_status()
        if status.paused:
            storefront_admin_client.admin_resume()
            log.info("[teardown] Cleared residual global pause on storefront")
    except Exception as exc:
        log.warning("[teardown] Could not verify/clear global pause: %s", exc)


@pytest.fixture(scope="module", autouse=True)
def reap_buyer_settle_subprocess(deal_state: DealState):
    """Stop the buyer-CLI ``market settle`` subprocess if it outlived the test.

    The deal flow normally lets the subprocess exit cleanly at phase 09b
    once settlement is ready. If an earlier assertion failed and bailed
    out, the process is still polling the seller — terminate it so the
    module run doesn't leak a child.
    """
    yield
    run = deal_state.settle_run_handle
    if run is None:
        return
    try:
        run.terminate()
    except Exception as exc:
        log.warning("[teardown] could not terminate settle subprocess: %s", exc)


@pytest.fixture(scope="module", autouse=True)
def release_reserved_resources(storefront_admin_client):
    """Release any leftover reserved compute resources after the module runs.

    Stage 09 reserves a compute VM for the deal but mocked provisioning never
    expires the lease, so the resource stays in ``reserved`` state forever.
    Without this teardown, a second back-to-back e2e_deal run against the
    same stack hits ``no_matching_inventory`` at stage 05b.

    Production storefronts release reservations via ``resource_poller`` once
    the lease expires; this fixture is the test-only equivalent for the
    short-circuited mock flow.
    """
    yield
    try:
        result = storefront_admin_client.admin_release_reservations()
        if result.released_count:
            log.info(
                "[teardown] Released %d reserved resource(s): %s",
                result.released_count, result.resource_ids,
            )
    except Exception as exc:
        log.warning("[teardown] Could not release reserved resources: %s", exc)


# ---------------------------------------------------------------------------
# wait_for_stage_event helper — wraps storefront_admin_client.wait_for_stage_event
# ---------------------------------------------------------------------------

def wait_for_stage_event(
    client,
    stage: str,
    event: str,
    *,
    listing_id: str | None = None,
    negotiation_id: str | None = None,
    since_id: int = 0,
    timeout: float = 30.0,
):
    """Block until the matching stage event appears in /api/v1/system/events.

    Wraps ``SyncStorefrontClient.wait_for_stage_event`` with a friendlier
    pytest-style timeout error message.

    Parameters
    ----------
    client:
        A ``SyncStorefrontClient`` asserting the ``admin`` role.
    stage, event:
        Stage and event strings to match (e.g. ``"discovery"``, ``"order_published"``).
    listing_id, negotiation_id:
        Optional filters passed through to the events query.
    since_id:
        Ignore events older than this id. Use when waiting for the
        *next* event after triggering an action — snapshot the latest
        id via ``get_events`` first, then pass it here.
    timeout:
        Seconds to wait before raising AssertionError.
    """
    try:
        return client.wait_for_stage_event(
            stage, event,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
            since_id=since_id,
            timeout=timeout,
        )
    except TimeoutError as exc:
        pytest.fail(str(exc))


# ---------------------------------------------------------------------------
# Mode-agnostic deal-lease view (embedded vm_leases vs site-ledger reservation)
# ---------------------------------------------------------------------------

class DealLease:
    """One deal's lease: the temporal tail of its ledger reservation.

    The full-deal scenarios drive the expiry lifecycle through this
    view — resolve the reservation by escrow, read it back in lease
    vocabulary, back-date its end, and observe the watchdog release it
    in the ledger with a deal-scoped capacity-released event to the
    storefront.

    ``status`` and ``release_job_id`` come from the authoritative compute
    provisioning lease contract.  For VM release, ``release_job_id`` is the
    durable fulfillment id rather than an Ansible queue job id.
    """

    def __init__(self, provisioning_client, escrow_uid: str) -> None:
        self._client = provisioning_client
        self.escrow_uid = escrow_uid
        self.is_ledger = True
        reservations = (
            provisioning_client.list_capacity_reservations(escrow_uid=escrow_uid)
            .get("reservations") or []
        )
        live = [a for a in reservations if a.get("lease_end_utc")]
        assert live, (
            f"No ledger reservation with a lease tail for escrow "
            f"{escrow_uid!r} — was the lease registered after fulfillment?"
        )
        self.lease_id = str(live[0]["capacity_reservation_id"])

    def refresh(self) -> dict:
        """Current lease fields from the public compute lease contract."""
        lease = self._client.get_lease(self.lease_id)
        row = self._client.get_capacity_reservation(self.lease_id)
        data = lease.model_dump(mode="json") if hasattr(lease, "model_dump") else dict(lease)
        return {
            "id": data.get("capacity_reservation_id") or self.lease_id,
            "escrow_uid": row.get("escrow_uid"),
            "resource_id": row.get("resource_id"),
            "vm_host": row.get("vm_host"),
            "vm_target": row.get("vm_target"),
            "status": data.get("status"),
            "fulfillment_id": data.get("release_job_id"),
            "create_job_id": data.get("create_job_id"),
        }

    def backdate(self, lease_end_utc: str) -> dict:
        """Move the lease end into the past so the next watchdog cycle fires.

        Uses PATCH /api/v1/leases/{id} (update_lease) to update the ledger
        reservation's lease_end_utc directly.  Returns the refreshed normalized
        lease view.
        """
        self._client.update_lease(self.lease_id, lease_end_utc=lease_end_utc)
        return self.refresh()

    def resource_consumed(self, storefront_admin_client, resource_id: str) -> bool:
        """Whether the deal's capacity is still held, per the ledger."""
        for row in self._client.capacity_snapshot():
            if str(row.get("resource_id")) == resource_id:
                total = int(row.get("value") or 0)
                return int(row.get("available_units") or 0) < total
        pytest.fail(
            f"Resource {resource_id!r} not found in site capacity snapshot"
        )

    @property
    def released_stage_event(self) -> tuple[str, str]:
        """(stage, event) the storefront emits when this lease releases."""
        return ("fulfillment", "capacity_released")
