"""Fixtures for the VM lane's deal scenarios.

All fixtures are ``module``-scoped so one ``DealState`` persists across a
scenario module's sequential stages. Each stage reads from and writes to
``DealState``; later stages skip automatically if an earlier required field was
never populated (indicating the earlier stage failed).

The typed-client deal (``test_full_deal.py``) runs the canonical compute deal's
shared stages, which request the fixtures every compute domain's conftest
provides under one set of names (see ``helpers/compute_deal_stages.py``), and
VM's ``deal_driver``.

Clients
-------
* ``storefront_client``        — canonical ``SyncStorefrontClient``, buyer key
* ``storefront_admin_client``  — same, seller key + admin key
* ``storefront_service_client`` — same, signed as the provisioning peer
* ``registry_client``          — ``SyncRegistryClient`` from the registry-client wheel
* ``provisioning_client``      — ``SyncComputeProvisioningClient`` signing as
  the provisioning admin principal
* ``vm_operator_client``       — VM's typed routes over that client's transport
* ``resource_pool_client``     — pool administration over that transport
* ``site_capacity``            — the site's capacity reads, signed as admin
* ``provisioning_test_client`` — thin sync wrapper over ``/test/*`` endpoints
* ``deal_driver``              — VM's part of the shared deal stages

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
    Identity,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    create_signer,
    sign_request,
)
from compute_provisioning_client import ComputeProvisioningError, SyncComputeProvisioningClient
from compute_provisioning_contracts import ConnectionSubmission, HostCreate
from market_resource_pools_client import SyncResourcePoolClient
from vm_provisioning_operator import SyncVmOperatorClient
from e2e_harness.settings import settings
from e2e_harness.provisioning_test_client import ProvisioningTestClient
from tests.e2e.roles.helpers.compute_deal import SiteCapacity, convergence_paused
from tests.e2e.roles.helpers.compute_deal_stages import ComputeDealState
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.vms.compute_deal_driver import VmComputeDealDriver

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DealState — mutable carrier shared across all tests in the module
# ---------------------------------------------------------------------------

@dataclass
class DealState(ComputeDealState):
    """VM's observations layered over the canonical compute deal's state.

    The typed-client deal uses `ComputeDealState`'s fields plus the few its own
    VM stages produce. The buyer-CLI deal and the one-shot buy declare their
    stages here rather than from the shared stages, so the fields they produce
    and consume stay declared here too.
    """
    domain_identity: str = "vms.compute"
    # VM's own stages of the typed-client deal: 00f imports the storefront
    # resource row 02b lists, and 03a validates the publish 03b performs.
    _resources_seeded: bool = False
    _registry_validate_passed: bool = False
    # The buyer-CLI and one-shot scenarios' own sentinels: the listing resumed
    # into publication, the executor host registered, and the capacity-event
    # loop stepped (`B4c` and the buyer-CLI deal's capacity-event stage).
    resume_confirmed: bool = False
    _executor_host_registered: bool = False
    _capacity_events_advanced: bool = False
    # Buyer-CLI run-log identity from `market negotiate`; consumed by
    # `market settle --from <run_id>` in phase 08. Sentinel for the
    # "negotiation produced a usable agreed outcome" precondition.
    buyer_run_id: Optional[str] = None
    # Buyer-CLI scenarios only: carries the background `market settle`
    # subprocess handle so phase 09b can wait for its clean exit and the
    # module teardown can terminate it if leftover.
    settle_run_handle: Optional[Any] = None
    # Buyer-CLI only: the host captured from the lease.
    host_id: Optional[str] = None
    # Buyer-CLI only: what its settlement and lease stages record.
    settlement_submitted: bool = False
    tenant_credentials: Optional[dict[str, Any]] = None
    seller_listing_final_status: Optional[str] = None
    lease_status: Optional[str] = None


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

def capacity_site_id() -> str:
    """The site the storefront publishes capacity against.

    Fulfillment callbacks are scoped to a site, and the value matches
    `[capacity.sites]` in the storefront config.
    """
    return str(settings.SELLER.get("site_id", "default") or "default")


def capacity_source_for(resource: dict[str, Any], *, site_id: str | None = None) -> dict[str, Any]:
    """Capacity provenance bound to the listing resource being published.

    The storefront refuses a listing whose declared source disagrees with its
    resource on pool or resource, or whose listing shape differs from what the
    resource publishes, so this is derived from the resource rather than
    restated alongside it — a hand-written copy is a second place that has to
    stay in sync.
    """
    shape: dict[str, dict[str, Any]] = {
        "gpu": {"count": resource.get("gpu_count", 1), "model": resource["gpu_model"]},
    }
    for family, field_name, published in (
        ("cpu", "count", "vcpu_count"),
        ("memory", "gib", "ram_gb"),
        ("storage", "gib", "disk_gb"),
    ):
        if resource.get(published) is not None:
            shape[family] = {field_name: resource[published]}
    source: dict[str, Any] = {
        "site_id": site_id or str(settings.SELLER.get("site_id", "default") or "default"),
        "listing_shape": shape,
    }
    # Both when the resource declares both: a `specific_resource` member is
    # pool-bound *and* resource-keyed, and the storefront compares the two
    # fields independently, so an either/or copy disagrees with the resource
    # it was derived from.
    if resource.get("pool_id"):
        source["pool_id"] = resource["pool_id"]
    if resource.get("resource_id"):
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


def one_site(report: dict) -> dict:
    """The single site in a lifecycle report, refusing an ambiguous one.

    These scenarios drive a storefront with one configured site. Picking the
    first of several would make an assertion about whichever site happened to
    be enumerated first.
    """
    sites = report.get("sites") or []
    assert len(sites) == 1, (
        f"expected exactly one configured capacity site, got "
        f"{[site.get('site') for site in sites]!r}"
    )
    return sites[0]


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
def storefront_service_client():
    """Service-role storefront client: the provisioning peer's callbacks.

    Fulfillment events -- usage started, capacity released, fulfillment failed
    -- are delivered by the provisioning service, not by an operator. The
    storefront authenticates them against its one configured service peer, so
    this signs as the provisioning service's own principal rather than as the
    administrator.

    A scenario that needs to drive one of those events stands in for the peer,
    and does it through the public typed methods. Reaching into the client's
    private `_post` and `_admin_headers` instead — which is what these
    scenarios used to do — bypasses the signed-request construction the client
    exists to own, so the call keeps working while the real path is broken.
    """
    from storefront_client import SyncStorefrontClient

    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    client = SyncStorefrontClient(
        url,
        _signer(
            settings.PROVISIONING.get("service_scheme", "eip191"),
            settings.PROVISIONING.get("service_credential", ""),
            "PROVISIONING.SERVICE_CREDENTIAL",
        ),
        caller_role="service",
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
    """Admin-signed SyncComputeProvisioningClient.

    Provisioning authenticates per caller: each request carries the caller's
    marketplace signature plus an asserted role, and the service verifies the
    principal against the durable trust set bound to that role.

    This suite drives provisioning as the **admin** principal, and that is not
    a preference: the client asserts the ``admin`` role, and the service
    resolves the trust set from the asserted role. Signing as the storefront
    principal would construct successfully and then be refused on
    authorisation, so the credential here must be the principal pinned as the
    provisioning admin identity.

    ``expected_authorities`` pins the service's own signing principal, which is
    a different identity again, so responses are verified as well as requests.
    """
    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    client = SyncComputeProvisioningClient(
        url, _provisioning_admin_signer(), "admin", _provisioning_authority_trust()
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def vm_operator_client(provisioning_client) -> SyncVmOperatorClient:
    """VM's operations, relays, and lease routes over the family client's transport."""
    return SyncVmOperatorClient(provisioning_client)


@pytest.fixture(scope="module")
def resource_pool_client(provisioning_client) -> SyncResourcePoolClient:
    """Pool administration over the family client's transport."""
    return SyncResourcePoolClient(provisioning_client)


@pytest.fixture(scope="module")
def site_capacity() -> SiteCapacity:
    """The VM site's capacity reads and lease truncation, signed as its admin."""
    return SiteCapacity(
        _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL"),
        _provisioning_admin_signer(),
        _provisioning_authority_trust(),
    )


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
    host_name = "kvm1"

    try:
        provisioning_client.get_host(host_name)
    except ComputeProvisioningError as exc:
        if exc.status_code != 404:
            pytest.skip(f"Could not probe provisioning host {host_name!r}: {exc}")
    else:
        log.info("[conftest] Provisioning host %r already registered", host_name)
        return

    body = HostCreate(
        host_id=host_name,
        connection=ConnectionSubmission(
            kind="ssh",
            public={"ssh_host": "127.0.0.1", "ssh_user": "stub", "key_path": "/tmp/stub-e2e-key"},
        ),
        gpu_count=1,
        enabled=True,
    )
    try:
        provisioning_client.register_host(body)
    except ComputeProvisioningError as exc:
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


@pytest.fixture(scope="module")
def buyer_principal():
    """The buyer's marketplace principal, as the buyer clients sign it."""
    return _signer(
        "eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"
    ).identity


@pytest.fixture(scope="module")
def deal_driver(
    provisioning_client,
    provisioning_test_client,
    storefront_client,
    storefront_admin_client,
    storefront_service_client,
    site_capacity_admin_client,
    site_capacity,
    buyer_config,
) -> VmComputeDealDriver:
    """VM's part of the canonical compute deal's shared stages."""
    return VmComputeDealDriver(
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client,
        site_capacity=site_capacity,
        buyer_config=buyer_config,
        site_id=capacity_site_id(),
    )


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


@pytest.fixture(scope="module")
def convergence_advanced_explicitly(provisioning_client):
    """This module drives fulfillment convergence; the timer does not.

    Opt-in, via ``pytest.mark.usefixtures`` on the modules that actually drive
    convergence; see `convergence_paused` for why it is not autouse and why the
    timer is resumed in the finaliser.
    """
    yield from convergence_paused(provisioning_client)


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
