"""HTTP clients for the versioned compute provisioning contract."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Protocol

import httpx
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    RotationRequest,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

from .contracts import (
    CredentialEnvelope,
    ExecutorActionEnvelope,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    JobAccepted,
    LeaseForceRelease,
    LeaseRegistration,
    LeaseRetryRelease,
    LeaseTermination,
    LeaseView,
    ProvisioningJob,
)
from market_fulfillment import VersionedEnvelope


class ComputeProvisioningError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ComputeProvisioningJobError(ComputeProvisioningError):
    pass


class ComputeProvisioningTimeoutError(ComputeProvisioningError):
    pass

class ComputeProvisioningAuthenticationError(ComputeProvisioningError):
    pass


SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


def _unix_time() -> int:
    return int(time.time())


@dataclass(frozen=True, slots=True)
class ProvisioningRouteContract:
    method: str
    pattern: re.Pattern[str]
    operation: str
    body_resource: str | None = None
    optional_body_resource: bool = False
    path_resource: str | tuple[str, ...] | None = None

    def match(self, method: str, path: str, body: Any) -> str | None:
        if method.upper() != self.method:
            return None
        matched = self.pattern.fullmatch(path)
        if matched is None:
            return None
        if self.body_resource is not None:
            if not isinstance(body, dict):
                raise ValueError(
                    f"{self.operation} requires a JSON object request body"
                )
            resource = body.get(self.body_resource)
            if resource is None and self.optional_body_resource:
                return ""
            if not isinstance(resource, str) or not resource:
                raise ValueError(
                    f"{self.operation} requires body.{self.body_resource}"
                )
            return resource
        if isinstance(self.path_resource, tuple):
            return "/".join(matched.group(name) for name in self.path_resource)
        if self.path_resource is not None:
            return matched.group(self.path_resource)
        return ""

    @property
    def required_role(self) -> str:
        return (
            "admin"
            if self.operation in ADMIN_PROVISIONING_OPERATIONS
            else "seller"
        )

    @property
    def allowed_roles(self) -> tuple[str, ...]:
        if self.operation in DUAL_ROLE_PROVISIONING_OPERATIONS:
            return ("seller", "admin")
        return (self.required_role,)


PROVISIONING_ROUTE_CONTRACTS = (
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/actions"),
        "provisioning_action_submit",
        body_resource="capacity_reservation_id",
    ),
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/contract"),
        "provisioning_job_get",
        path_resource="job_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/contract/cancel"),
        "provisioning_job_cancel",
        path_resource="job_id",
    ),
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/contract/credentials"),
        "provisioning_job_credentials",
        path_resource="job_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/contract/leases"),
        "provisioning_lease_register",
        body_resource="capacity_reservation_id",
    ),
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/contract/leases/(?P<reservation_id>[^/]+)"),
        "provisioning_lease_get",
        path_resource="reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(
            r"/api/v1/contract/leases/(?P<reservation_id>[^/]+)/terminate"
        ),
        "provisioning_lease_terminate",
        path_resource="reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(
            r"/api/v1/contract/leases/(?P<reservation_id>[^/]+)/retry-release"
        ),
        "provisioning_lease_retry_release",
        path_resource="reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(
            r"/api/v1/contract/leases/(?P<reservation_id>[^/]+)/force-release"
        ),
        "provisioning_lease_force_release",
        path_resource="reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/fulfillment/schedule"),
        "provisioning_fulfillment_schedule",
        body_resource="capacity_reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/fulfillment/begin"),
        "provisioning_fulfillment_begin",
        body_resource="capacity_reservation_id",
    ),
    ProvisioningRouteContract(
        "POST",
        re.compile(
            r"/api/v1/fulfillment/(?P<fulfillment_id>[^/]+)/begin-teardown"
        ),
        "provisioning_fulfillment_teardown",
        path_resource="fulfillment_id",
    ),
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/fulfillment/(?P<fulfillment_id>[^/]+)/status"),
        "provisioning_fulfillment_status",
        path_resource="fulfillment_id",
    ),
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/fulfillment/(?P<fulfillment_id>[^/]+)/result"),
        "provisioning_fulfillment_result",
        path_resource="fulfillment_id",
    ),
    # Site capacity authority.
    ProvisioningRouteContract("PUT", re.compile(r"/api/v1/capacity/resources/(?P<resource_id>[^/]+)"), "capacity_resource_put", path_resource="resource_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/resources"), "capacity_resources_list"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/site-resource-pools/version"), "capacity_resource_pools_version"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/site-resource-pools"), "capacity_resource_pools_get"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/site-capacity-buckets/version"), "capacity_buckets_version"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/site-capacity-buckets"), "capacity_buckets_get"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/snapshot"), "capacity_snapshot"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/capacity/probe"), "capacity_probe"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/capacity/reservations"), "capacity_reserve"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/commit"), "capacity_commit", path_resource="reservation_id"),
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/capacity/releases"),
        "capacity_release",
        body_resource="capacity_reservation_id",
        optional_body_resource=True,
    ),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/truncate-lease"), "capacity_truncate_lease", path_resource="reservation_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/reservations"), "capacity_reservations_list"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)"), "capacity_reservation_get", path_resource="reservation_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/capacity/events"), "capacity_events"),
    # System and job administration.
    ProvisioningRouteContract(
        "POST",
        re.compile(r"/api/v1/identity/rotations/(?P<trust_role>admin|seller)"),
        "provisioning_identity_rotate",
        path_resource="trust_role",
    ),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/system/status"), "provisioning_system_status"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/system/health"), "provisioning_system_health"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/system/version"), "provisioning_system_version"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/system/ansible/readiness"), "provisioning_ansible_readiness"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/check-leases"), "provisioning_check_leases"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/fulfillment-convergence/run-cycle"), "provisioning_fulfillment_convergence"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/lease-watchdog/pause"), "provisioning_lease_watchdog_pause"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/lease-watchdog/resume"), "provisioning_lease_watchdog_resume"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/?"), "provisioning_jobs_list"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)"), "provisioning_job_status", path_resource="job_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/credentials"), "provisioning_job_credentials_admin", path_resource="job_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/logs"), "provisioning_job_logs", path_resource="job_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/cancel"), "provisioning_job_cancel_admin", path_resource="job_id"),
    # Host, VM, and lease administration.
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/?"), "provisioning_hosts_list"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/?"), "provisioning_host_create"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/import"), "provisioning_hosts_import"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)"), "provisioning_host_get", path_resource="host"),
    ProvisioningRouteContract("PUT", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)"), "provisioning_host_update", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/enable"), "provisioning_host_enable", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/disable"), "provisioning_host_disable", path_resource="host"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/capacity"), "provisioning_host_capacity", path_resource="host"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/connectivity"), "provisioning_host_connectivity", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/?"), "provisioning_vm_create", path_resource="host"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/?"), "provisioning_vm_list", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/start"), "provisioning_vm_start", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/shutdown"), "provisioning_vm_shutdown", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/reboot"), "provisioning_vm_reboot", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/destroy"), "provisioning_vm_destroy", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/undefine"), "provisioning_vm_undefine", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/monitor"), "provisioning_vm_monitor", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/reset-password"), "provisioning_vm_reset_password", path_resource=("host", "vm_name")),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/leases/?"), "provisioning_leases_list"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/leases/?"), "provisioning_lease_create"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/leases/by-escrow/(?P<escrow_uid>[^/]+)"), "provisioning_lease_by_escrow", path_resource="escrow_uid"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/leases/(?P<lease_id>[^/]+)"), "provisioning_lease_admin_get", path_resource="lease_id"),
    ProvisioningRouteContract("PATCH", re.compile(r"/api/v1/leases/(?P<lease_id>[^/]+)"), "provisioning_lease_update", path_resource="lease_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/leases/(?P<lease_id>[^/]+)/terminate"), "provisioning_lease_admin_terminate", path_resource="lease_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/leases/(?P<lease_id>[^/]+)/release-oversight"), "provisioning_lease_release_oversight", path_resource="lease_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/admin/leases/(?P<lease_id>[^/]+)/retry-release"), "provisioning_lease_admin_retry_release", path_resource="lease_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/admin/leases/(?P<lease_id>[^/]+)/force-release"), "provisioning_lease_admin_force_release", path_resource="lease_id"),
    # Bare-metal and pool administration.
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/bare-metal/leases/?"), "provisioning_bare_metal_leases_list"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/bare-metal/leases/?"), "provisioning_bare_metal_lease_create"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/bare-metal/leases/by-escrow/(?P<escrow_uid>[^/]+)"), "provisioning_bare_metal_lease_by_escrow", path_resource="escrow_uid"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/bare-metal/leases/(?P<lease_id>[^/]+)"), "provisioning_bare_metal_lease_get", path_resource="lease_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/pools/?"), "provisioning_pools_list"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/pools/export"), "provisioning_pools_export"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/pools/(?P<pool_id>[^/]+)"), "provisioning_pool_get", path_resource="pool_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/pools/?"), "provisioning_pool_create"),
    ProvisioningRouteContract("PUT", re.compile(r"/api/v1/pools/(?P<pool_id>[^/]+)"), "provisioning_pool_replace", path_resource="pool_id"),
    ProvisioningRouteContract("PATCH", re.compile(r"/api/v1/pools/(?P<pool_id>[^/]+)"), "provisioning_pool_update", path_resource="pool_id"),
    ProvisioningRouteContract("DELETE", re.compile(r"/api/v1/pools/(?P<pool_id>[^/]+)"), "provisioning_pool_disable", path_resource="pool_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/pools/import"), "provisioning_pools_import"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/pools/validate"), "provisioning_pools_validate"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/fulfillment/validate"), "provisioning_fulfillment_validate", body_resource="capacity_reservation_id"),
    # Mock-profile control routes remain authenticated when mounted.
    ProvisioningRouteContract("POST", re.compile(r"/test/mock-rules"), "provisioning_test_rule_add"),
    ProvisioningRouteContract("GET", re.compile(r"/test/mock-rules"), "provisioning_test_rules_list"),
    ProvisioningRouteContract("DELETE", re.compile(r"/test/mock-rules/(?P<rule_id>[^/]+)"), "provisioning_test_rule_delete", path_resource="rule_id"),
    ProvisioningRouteContract("POST", re.compile(r"/test/mock-rules/(?P<rule_id>[^/]+)/resume"), "provisioning_test_rule_resume", path_resource="rule_id"),
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/summary"), "provisioning_test_jobs_summary"),
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/drain"), "provisioning_test_jobs_drain"),
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/(?P<job_id>[^/]+)/wait"), "provisioning_test_job_wait", path_resource="job_id"),
    ProvisioningRouteContract("POST", re.compile(r"/test/evaluate-job"), "provisioning_test_job_evaluate"),
)

DUAL_ROLE_PROVISIONING_OPERATIONS = frozenset(
    {
        "capacity_snapshot",
        "capacity_reservations_list",
        "capacity_reservation_get",
        "capacity_truncate_lease",
    }
)


ADMIN_PROVISIONING_OPERATIONS = frozenset(
    {
        "provisioning_system_status",
        "provisioning_system_health",
        "provisioning_system_version",
        "provisioning_ansible_readiness",
        "provisioning_check_leases",
        "provisioning_fulfillment_convergence",
        "provisioning_lease_watchdog_pause",
        "provisioning_identity_rotate",
        "provisioning_lease_watchdog_resume",
        "provisioning_jobs_list",
        "provisioning_job_status",
        "provisioning_job_credentials_admin",
        "provisioning_job_logs",
        "provisioning_job_cancel_admin",
        "provisioning_hosts_list",
        "provisioning_host_create",
        "provisioning_hosts_import",
        "provisioning_host_get",
        "provisioning_host_update",
        "provisioning_host_enable",
        "provisioning_host_disable",
        "provisioning_host_capacity",
        "provisioning_host_connectivity",
        "provisioning_vm_create",
        "provisioning_vm_list",
        "provisioning_vm_start",
        "provisioning_vm_shutdown",
        "provisioning_vm_reboot",
        "provisioning_vm_destroy",
        "provisioning_vm_undefine",
        "provisioning_vm_monitor",
        "provisioning_vm_reset_password",
        "provisioning_leases_list",
        "provisioning_lease_create",
        "provisioning_lease_by_escrow",
        "provisioning_lease_admin_get",
        "provisioning_lease_update",
        "provisioning_lease_admin_terminate",
        "provisioning_lease_release_oversight",
        "provisioning_lease_admin_retry_release",
        "provisioning_lease_admin_force_release",
        "provisioning_bare_metal_leases_list",
        "provisioning_bare_metal_lease_create",
        "provisioning_bare_metal_lease_by_escrow",
        "provisioning_bare_metal_lease_get",
        "provisioning_pools_list",
        "provisioning_pools_export",
        "provisioning_pool_get",
        "provisioning_pool_create",
        "provisioning_pool_replace",
        "provisioning_pool_update",
        "provisioning_pool_disable",
        "provisioning_pools_import",
        "provisioning_pools_validate",
        "provisioning_test_rule_add",
        "provisioning_test_rules_list",
        "provisioning_test_rule_delete",
        "provisioning_test_rule_resume",
        "provisioning_test_jobs_summary",
        "provisioning_test_jobs_drain",
        "provisioning_test_job_wait",
        "provisioning_test_job_evaluate",
    }
)

def canonical_provisioning_request_body(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
    *,
    query: Mapping[str, Any] | None = None,
) -> Any:
    """Build the canonical v2 body, including behavior-affecting query input."""

    values = dict(query or {})
    if method.upper() == "GET" and path == "/api/v1/capacity/reservations":
        return {
            name: values[name]
            for name in ("state", "escrow_uid")
            if name in values and values[name] is not None
        }
    if method.upper() == "GET" and path == "/api/v1/capacity/events":
        return {
            "after": int(values.get("after", 0)),
            "limit": int(values.get("limit", 500)),
        }
    if not values:
        return body
    canonical_query = {
        key: values[key]
        for key in sorted(values)
        if values[key] is not None
    }
    if body is EMPTY_BODY:
        return {"query": canonical_query}
    return {"body": body, "query": canonical_query}



def resolve_provisioning_route_contract(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
) -> tuple[ProvisioningRouteContract, str]:
    """Return the exact authenticated route contract and bound resource."""

    for contract in PROVISIONING_ROUTE_CONTRACTS:
        resource = contract.match(method, path, body)
        if resource is not None:
            return contract, resource
    raise ValueError(f"no authenticated provisioning contract for {method} {path}")


def resolve_provisioning_route(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
) -> tuple[str, str]:
    """Return the authority-owned semantic operation and resource."""

    contract, resource = resolve_provisioning_route_contract(method, path, body)
    return contract.operation, resource

class ComputeProvisioningClientProtocol(Protocol):
    async def submit_action(
        self,
        envelope: ExecutorActionEnvelope,
        *,
        request_id: str | None = None,
    ) -> JobAccepted: ...
    async def get_job(
        self, job_id: str, *, request_id: str | None = None
    ) -> ProvisioningJob: ...
    async def cancel_job(
        self, job_id: str, *, request_id: str | None = None
    ) -> ProvisioningJob: ...
    async def get_job_credentials(
        self, job_id: str, *, request_id: str | None = None
    ) -> list[CredentialEnvelope]: ...
    async def register_lease(
        self,
        registration: LeaseRegistration,
        *,
        request_id: str | None = None,
    ) -> LeaseView: ...
    async def get_lease(
        self,
        capacity_reservation_id: str,
        *,
        request_id: str | None = None,
    ) -> LeaseView: ...
    async def terminate_lease(
        self,
        capacity_reservation_id: str,
        request: LeaseTermination,
        *,
        request_id: str | None = None,
    ) -> LeaseView: ...
    async def retry_lease_release(
        self,
        capacity_reservation_id: str,
        request: LeaseRetryRelease,
        *,
        request_id: str | None = None,
    ) -> LeaseView: ...
    async def force_release_lease(
        self,
        capacity_reservation_id: str,
        request: LeaseForceRelease,
        *,
        request_id: str | None = None,
    ) -> LeaseView: ...
    async def rotate_trusted_principal(
        self,
        role: str,
        rotation: RotationRequest,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...
    async def schedule_resource(
        self,
        request: FulfillmentScheduleRequest,
        *,
        request_id: str | None = None,
    ) -> FulfillmentScheduleResponse: ...
    async def begin_fulfillment(
        self,
        body: FulfillmentRequestBody,
        *,
        request_id: str | None = None,
    ) -> FulfillmentAcceptanceResponse: ...
    async def begin_fulfillment_teardown(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> FulfillmentAcceptanceResponse: ...
    async def get_fulfillment_status(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> FulfillmentStatusResponse: ...
    async def get_fulfillment_result(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> VersionedEnvelope[dict[str, Any]]: ...


class ComputeProvisioningClient:
    def __init__(
        self,
        base_url: str,
        signer: Signer,
        caller_role: str,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_timestamp_skew: int = 300,
    ) -> None:
        if not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if caller_role not in {"seller", "admin"}:
            raise ValueError("caller_role must be 'seller' or 'admin'")
        if not isinstance(expected_authorities, TrustedIdentitySet):
            raise TypeError(
                "expected_authorities must be a market_identity.TrustedIdentitySet"
            )
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must not be negative")
        self._signer = signer
        self._caller_role = caller_role
        self._expected_authorities = expected_authorities
        self._max_timestamp_skew = max_timestamp_skew
        self._request_contexts: dict[
            str, tuple[str, str, str, str]
        ] = {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> "ComputeProvisioningClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _raise(response: httpx.Response, body: Any) -> None:
        if response.is_success:
            return
        detail = body.get("detail", response.text) if isinstance(body, dict) else body
        raise ComputeProvisioningError(
            str(detail),
            status_code=response.status_code,
        )

    def _request_headers(
        self,
        *,
        method: str,
        operation: str,
        resource: str,
        body: Any,
        request_id: str,
    ) -> dict[str, str]:
        context = (
            method.upper(),
            operation,
            resource,
            canonical_body_hash(body),
        )
        existing = self._request_contexts.get(request_id)
        if existing is not None and existing != context:
            raise ValueError(
                "request_id was reused with changed request content"
            )
        authenticated = sign_request(
            signer=self._signer,
            envelope=RequestEnvelope(
                role=self._caller_role,
                principal=self._signer.identity,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                timestamp=_unix_time(),
                body_hash=canonical_body_hash(body),
            ),
        )
        headers = {
            SIGNATURE_VERSION_HEADER: authenticated.protocol,
            IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
            ROLE_HEADER: authenticated.role,
            REQUEST_ID_HEADER: authenticated.request_id,
            TIMESTAMP_HEADER: str(authenticated.timestamp),
            SIGNATURE_HEADER: authenticated.proof.value,
        }
        self._request_contexts[request_id] = context
        return dict(headers)

    def _verify_response(
        self,
        response: httpx.Response,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
        body: Any,
    ) -> None:
        try:
            principal = Identity(
                scheme=response.headers[IDENTITY_SCHEME_HEADER],
                identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
            )
            authenticated = AuthenticatedResponse(
                protocol=response.headers[SIGNATURE_VERSION_HEADER],
                role=response.headers[ROLE_HEADER],
                principal=principal,
                method=method,
                operation=operation,
                resource=resource,
                request_id=response.headers[REQUEST_ID_HEADER],
                timestamp=int(response.headers[TIMESTAMP_HEADER]),
                status=response.status_code,
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(
                    scheme=principal.scheme,
                    value=response.headers[SIGNATURE_HEADER],
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ComputeProvisioningAuthenticationError(
                "missing or malformed provisioning response authentication",
                status_code=response.status_code,
            ) from exc
        result = verify_response(
            authenticated,
            body=body,
            now=_unix_time(),
            max_skew=self._max_timestamp_skew,
            expected_role="service",
            expected_principals=self._expected_authorities,
            expected_method=method,
            expected_operation=operation,
            expected_resource=resource,
            expected_request_id=request_id,
        )
        if not result.verified:
            raise ComputeProvisioningAuthenticationError(
                f"provisioning response authentication failed: {result.code.value}",
                status_code=response.status_code,
            )

    async def _request(
        self,
        method: str,
        path: str,
        body: Any = EMPTY_BODY,
        *,
        request_id: str | None = None,
    ) -> Any:
        payload = (
            body.model_dump(mode="json", exclude_none=True)
            if hasattr(body, "model_dump")
            else body
        )
        authenticated_body = canonical_provisioning_request_body(
            method,
            path,
            payload,
        )
        route, resource = resolve_provisioning_route_contract(
            method,
            path,
            authenticated_body,
        )
        operation = route.operation
        if self._caller_role not in route.allowed_roles:
            raise ComputeProvisioningAuthenticationError(
                f"{method} {path} permits caller roles {route.allowed_roles}"
            )
        resolved_request_id = request_id or uuid.uuid4().hex
        headers = self._request_headers(
            method=method,
            operation=operation,
            resource=resource,
            body=authenticated_body,
            request_id=resolved_request_id,
        )
        kwargs = {"json": payload} if payload is not EMPTY_BODY else {}
        response = await self._client.request(
            method,
            path,
            headers=headers,
            **kwargs,
        )
        if response.content:
            try:
                response_body: Any = response.json()
            except ValueError:
                response_body = response.text
        else:
            response_body = EMPTY_BODY
        self._verify_response(
            response,
            method=method,
            operation=operation,
            resource=resource,
            request_id=resolved_request_id,
            body=response_body,
        )
        self._raise(response, response_body)
        return response_body

    async def submit_action(
        self,
        envelope: ExecutorActionEnvelope,
        *,
        request_id: str | None = None,
    ) -> JobAccepted:
        return JobAccepted.model_validate(
            await self._request(
                "POST",
                "/api/v1/actions",
                envelope,
                request_id=request_id,
            )
        )

    async def get_job(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
    ) -> ProvisioningJob:
        return ProvisioningJob.model_validate(
            await self._request(
                "GET",
                f"/api/v1/jobs/{job_id}/contract",
                request_id=request_id,
            )
        )

    async def cancel_job(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
    ) -> ProvisioningJob:
        return ProvisioningJob.model_validate(
            await self._request(
                "POST",
                f"/api/v1/jobs/{job_id}/contract/cancel",
                {},
                request_id=request_id,
            )
        )

    async def get_job_credentials(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
    ) -> list[CredentialEnvelope]:
        payload = await self._request(
            "GET",
            f"/api/v1/jobs/{job_id}/contract/credentials",
            request_id=request_id,
        )
        return [
            CredentialEnvelope.model_validate(item)
            for item in payload.get("credentials", [])
        ]

    async def poll_until_complete(
        self,
        job_id: str,
        *,
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ) -> ProvisioningJob:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            job = await self.get_job(job_id)
            if job.status.value == "succeeded":
                return job
            if job.status.value in {"failed", "cancelled"}:
                message = (
                    job.error.message
                    if job.error
                    else f"job {job_id} {job.status.value}"
                )
                raise ComputeProvisioningJobError(message)
            if loop.time() >= deadline:
                raise ComputeProvisioningTimeoutError(
                    f"job {job_id} did not finish within {timeout}s"
                )
            await asyncio.sleep(poll_interval)

    async def register_lease(
        self,
        registration: LeaseRegistration,
        *,
        request_id: str | None = None,
    ) -> LeaseView:
        return LeaseView.model_validate(
            await self._request(
                "POST",
                "/api/v1/contract/leases",
                registration,
                request_id=request_id,
            )
        )

    async def get_lease(
        self,
        capacity_reservation_id: str,
        *,
        request_id: str | None = None,
    ) -> LeaseView:
        return LeaseView.model_validate(
            await self._request(
                "GET",
                f"/api/v1/contract/leases/{capacity_reservation_id}",
                request_id=request_id,
            )
        )

    async def terminate_lease(
        self,
        capacity_reservation_id: str,
        request: LeaseTermination,
        *,
        request_id: str | None = None,
    ) -> LeaseView:
        return LeaseView.model_validate(
            await self._request(
                "POST",
                f"/api/v1/contract/leases/{capacity_reservation_id}/terminate",
                request,
                request_id=request_id,
            )
        )

    async def retry_lease_release(
        self,
        capacity_reservation_id: str,
        request: LeaseRetryRelease,
        *,
        request_id: str | None = None,
    ) -> LeaseView:
        return LeaseView.model_validate(
            await self._request(
                "POST",
                f"/api/v1/contract/leases/{capacity_reservation_id}/retry-release",
                request,
                request_id=request_id,
            )
        )

    async def force_release_lease(
        self,
        capacity_reservation_id: str,
        request: LeaseForceRelease,
        *,
        request_id: str | None = None,
    ) -> LeaseView:
        return LeaseView.model_validate(
            await self._request(
                "POST",
                f"/api/v1/contract/leases/{capacity_reservation_id}/force-release",
                request,
                request_id=request_id,
            )
        )

    async def rotate_trusted_principal(
        self,
        role: str,
        rotation: RotationRequest,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if role not in {"admin", "seller"}:
            raise ValueError("role must be 'admin' or 'seller'")
        result = await self._request(
            "POST",
            f"/api/v1/identity/rotations/{role}",
            rotation,
            request_id=request_id,
        )
        if not isinstance(result, dict):
            raise ComputeProvisioningError("rotation response must be an object")
        return result

    async def schedule_resource(
        self,
        request: FulfillmentScheduleRequest,
        *,
        request_id: str | None = None,
    ) -> FulfillmentScheduleResponse:
        return FulfillmentScheduleResponse.model_validate(
            await self._request(
                "POST",
                "/api/v1/fulfillment/schedule",
                request,
                request_id=request_id,
            )
        )

    async def begin_fulfillment(
        self,
        body: FulfillmentRequestBody,
        *,
        request_id: str | None = None,
    ) -> FulfillmentAcceptanceResponse:
        return FulfillmentAcceptanceResponse.model_validate(
            await self._request(
                "POST",
                "/api/v1/fulfillment/begin",
                body,
                request_id=request_id,
            )
        )

    async def begin_fulfillment_teardown(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> FulfillmentAcceptanceResponse:
        return FulfillmentAcceptanceResponse.model_validate(
            await self._request(
                "POST",
                f"/api/v1/fulfillment/{fulfillment_id}/begin-teardown",
                {},
                request_id=request_id,
            )
        )

    async def get_fulfillment_status(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> FulfillmentStatusResponse:
        return FulfillmentStatusResponse.model_validate(
            await self._request(
                "GET",
                f"/api/v1/fulfillment/{fulfillment_id}/status",
                request_id=request_id,
            )
        )

    async def get_fulfillment_result(
        self,
        fulfillment_id: str,
        *,
        request_id: str | None = None,
    ) -> VersionedEnvelope[dict[str, Any]]:
        return VersionedEnvelope[dict[str, Any]].model_validate(
            await self._request(
                "GET",
                f"/api/v1/fulfillment/{fulfillment_id}/result",
                request_id=request_id,
            )
        )
