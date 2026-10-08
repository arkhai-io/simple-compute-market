"""The signed route contracts of the compute provisioning family.

Each contract names a route's method and path, the operation and resource a
request signs, and the caller roles it admits. The provisioning service's
request authentication and every typed client bind requests from these, so the
two cannot disagree. The family's own routes are ``PROVISIONING_ROUTE_CONTRACTS``;
a domain, an implementation, or another capability served by the same service
declares its routes as plain data in its own package, and the service assembles
every declaration into one ``ProvisioningRouteTable``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from market_identity import EMPTY_BODY

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


@dataclass(frozen=True, slots=True)
class ProvisioningRouteContract:
    method: str
    pattern: re.Pattern[str]
    operation: str
    body_resource: str | None = None
    optional_body_resource: bool = False
    path_resource: str | tuple[str, ...] | None = None
    # The caller roles the route admits, the required role first. Every
    # contract in a ``ProvisioningRouteTable`` carries them; a contract built
    # without them takes its roles from the family's operation sets.
    roles: tuple[str, ...] = ()

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
        return self.allowed_roles[0]

    @property
    def allowed_roles(self) -> tuple[str, ...]:
        return self.roles or _family_roles(self.operation)


PROVISIONING_ROUTE_CONTRACTS = (
    ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/contract/leases"),
        "provisioning_lease_list",
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
            r"/api/v1/contract/leases/(?P<reservation_id>[^/]+)/release-oversight"
        ),
        "provisioning_lease_release_oversight",
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
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/check-leases"), "provisioning_check_leases"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/fulfillment-convergence/run-cycle"), "provisioning_fulfillment_convergence"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/fulfillment-convergence/advance-cycle"), "provisioning_fulfillment_convergence_advance"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/fulfillment-convergence/pause"), "provisioning_fulfillment_convergence_pause"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/fulfillment-convergence/resume"), "provisioning_fulfillment_convergence_resume"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/lease-watchdog/pause"), "provisioning_lease_watchdog_pause"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/system/lease-watchdog/resume"), "provisioning_lease_watchdog_resume"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/?"), "provisioning_jobs_list"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)"), "provisioning_job_status", path_resource="job_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/credentials"), "provisioning_job_credentials_admin", path_resource="job_id"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/logs"), "provisioning_job_logs", path_resource="job_id"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/jobs/(?P<job_id>[^/]+)/cancel"), "provisioning_job_cancel_admin", path_resource="job_id"),
    # Host registry administration.
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/?"), "provisioning_hosts_list"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/?"), "provisioning_host_create"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)"), "provisioning_host_get", path_resource="host"),
    ProvisioningRouteContract("PUT", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)"), "provisioning_host_update", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/enable"), "provisioning_host_enable", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/disable"), "provisioning_host_disable", path_resource="host"),
    ProvisioningRouteContract("GET", re.compile(r"/api/v1/hosts/(?P<host>[^/]+)/connectivity"), "provisioning_host_connectivity", path_resource="host"),
    ProvisioningRouteContract("POST", re.compile(r"/api/v1/fulfillment/validate"), "provisioning_fulfillment_validate", body_resource="capacity_reservation_id"),
    # Shared mock-profile job controls remain authenticated when mounted.
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/summary"), "provisioning_test_jobs_summary"),
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/drain"), "provisioning_test_jobs_drain"),
    ProvisioningRouteContract("GET", re.compile(r"/test/jobs/(?P<job_id>[^/]+)/wait"), "provisioning_test_job_wait", path_resource="job_id"),

)

# Operations only the administrator may call. Every other family route admits
# the seller and the administrator: the administrator can do everything on this
# service. A storefront addresses its own leases by reservation id, so the lease
# list, which shows every storefront's leases, and the operator's release
# controls are the administrator's alone.
ADMIN_PROVISIONING_OPERATIONS = frozenset(
    {
        "provisioning_lease_list",
        "provisioning_lease_release_oversight",
        "provisioning_lease_retry_release",
        "provisioning_lease_force_release",
        "provisioning_system_status",
        "provisioning_system_health",
        "provisioning_system_version",
        "provisioning_check_leases",
        "provisioning_fulfillment_convergence",
        "provisioning_fulfillment_convergence_advance",
        "provisioning_fulfillment_convergence_pause",
        "provisioning_fulfillment_convergence_resume",
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
        "provisioning_host_get",
        "provisioning_host_update",
        "provisioning_host_enable",
        "provisioning_host_disable",
        "provisioning_host_connectivity",
        "provisioning_test_jobs_summary",
        "provisioning_test_jobs_drain",
        "provisioning_test_job_wait",
    }
)

PROVISIONING_ROLES = frozenset({"seller", "admin"})


def _family_roles(operation: str) -> tuple[str, ...]:
    """The roles of one of the family's own routes, from its operation sets."""

    if operation in ADMIN_PROVISIONING_OPERATIONS:
        return ("admin",)
    return ("seller", "admin")


# The family's own routes, each carrying its roles as every contract in a
# table does. A compute domain declares the routes it mounts in its own package.
PROVISIONING_ROUTE_CONTRACTS = tuple(
    replace(contract, roles=_family_roles(contract.operation))
    for contract in PROVISIONING_ROUTE_CONTRACTS
)

_DECLARATION_KEYS = frozenset(
    {
        "method",
        "path",
        "operation",
        "roles",
        "body_resource",
        "optional_body_resource",
        "path_resource",
    }
)


def route_contract_from_declaration(
    declaration: ProvisioningRouteContract | Mapping[str, Any],
) -> ProvisioningRouteContract:
    """Build a route contract from a domain's plain-data declaration.

    A contribution declares its routes as mappings, so its package needs no
    more of this one than this function's input: ``method``, ``path`` (a regular expression the
    whole path must match), ``operation``, ``roles``, and optionally
    ``path_resource`` (a group name, or a list of them joined with ``/``),
    ``body_resource``, and ``optional_body_resource``. A declaration must name
    its roles, because the family's operation sets know no domain's routes,
    and every route the provisioning service serves admits the administrator.
    """

    if isinstance(declaration, ProvisioningRouteContract):
        contract = declaration
    else:
        unknown = sorted(set(declaration) - _DECLARATION_KEYS)
        if unknown:
            raise ValueError(f"route declaration has unknown keys: {unknown}")
        path_resource = declaration.get("path_resource")
        if isinstance(path_resource, (list, tuple)):
            path_resource = tuple(str(name) for name in path_resource)
        contract = ProvisioningRouteContract(
            str(declaration["method"]).upper(),
            re.compile(str(declaration["path"])),
            str(declaration["operation"]),
            body_resource=declaration.get("body_resource"),
            optional_body_resource=bool(
                declaration.get("optional_body_resource", False)
            ),
            path_resource=path_resource,
            roles=tuple(declaration.get("roles") or ()),
        )
    roles = contract.roles
    if (
        not roles
        or len(set(roles)) != len(roles)
        or not set(roles) <= PROVISIONING_ROLES
    ):
        raise ValueError(
            f"route {contract.operation!r} must name its roles from "
            f"{sorted(PROVISIONING_ROLES)} without repetition"
        )
    if "admin" not in roles:
        raise ValueError(
            f"route {contract.operation!r} must admit admin: every route the "
            "provisioning service serves admits the administrator"
        )
    return contract


class ProvisioningRouteTable:
    """The route contracts one provisioning service authenticates.

    Assembled from the family's routes and each contribution's declarations. Every
    operation and every ``(method, path)`` route appears once. Within one
    contribution the first matching contract decides, as its owner ordered
    them; a path matched by contracts of two contributions is refused, because
    neither owner can say which signature it means.
    """

    def __init__(
        self,
        *contributions: Iterable[ProvisioningRouteContract | Mapping[str, Any]],
    ) -> None:
        groups: list[tuple[ProvisioningRouteContract, ...]] = []
        operations: set[str] = set()
        routes: set[tuple[str, str]] = set()
        for contribution in contributions:
            group = tuple(route_contract_from_declaration(item) for item in contribution)
            for contract in group:
                if contract.operation in operations:
                    raise ValueError(f"duplicate route operation {contract.operation!r}")
                route = (contract.method, contract.pattern.pattern)
                if route in routes:
                    raise ValueError(f"duplicate route {route[0]} {route[1]}")
                operations.add(contract.operation)
                routes.add(route)
            groups.append(group)
        self._groups = tuple(groups)

    @property
    def contracts(self) -> tuple[ProvisioningRouteContract, ...]:
        return tuple(contract for group in self._groups for contract in group)

    def resolve(
        self, method: str, path: str, body: Any = EMPTY_BODY
    ) -> tuple[ProvisioningRouteContract, str]:
        """Return the exact authenticated route contract and bound resource."""

        found: list[tuple[ProvisioningRouteContract, str]] = []
        for group in self._groups:
            for contract in group:
                resource = contract.match(method, path, body)
                if resource is not None:
                    found.append((contract, resource))
                    break
        if not found:
            raise ValueError(f"no authenticated provisioning contract for {method} {path}")
        if len(found) > 1:
            names = ", ".join(repr(contract.operation) for contract, _ in found)
            raise ValueError(f"{method} {path} is claimed by more than one route: {names}")
        return found[0]


PROVISIONING_ROUTE_TABLE = ProvisioningRouteTable(PROVISIONING_ROUTE_CONTRACTS)


def assemble_provisioning_route_table(
    *declarations: Iterable[ProvisioningRouteContract | Mapping[str, Any]],
) -> ProvisioningRouteTable:
    """The family's routes plus each contribution's declared routes."""

    return ProvisioningRouteTable(PROVISIONING_ROUTE_CONTRACTS, *declarations)


def canonical_provisioning_request_body(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
    *,
    query: Mapping[str, Any] | None = None,
) -> Any:
    """Build the canonical v2 body, including behavior-affecting query input.

    A request's query is signed with its body, so a caller cannot change what a
    read selects without invalidating the signature. This is the family's own
    form; a route another capability declares is canonicalized by that
    capability's rule.
    """

    values = dict(query or {})
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
    *,
    table: ProvisioningRouteTable | None = None,
) -> tuple[ProvisioningRouteContract, str]:
    """Return the exact authenticated route contract and bound resource.

    ``table`` defaults to the family's own routes; a caller reaching another
    owner's routes passes a table assembled with that owner's declarations.
    """

    return (table or PROVISIONING_ROUTE_TABLE).resolve(method, path, body)


def resolve_provisioning_route(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
    *,
    table: ProvisioningRouteTable | None = None,
) -> tuple[str, str]:
    """Return the authority-owned semantic operation and resource."""

    contract, resource = resolve_provisioning_route_contract(
        method, path, body, table=table
    )
    return contract.operation, resource
