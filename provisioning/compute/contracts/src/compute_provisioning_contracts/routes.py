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


class ProvisioningRouteResolutionError(ValueError):
    """A request resolved to no route contract, naming the case that failed.

    Each case carries the status and headers of its answer. The answer is
    unsigned: a response proof binds an operation and resource the client
    verifies against its own, and the server knows no operation for an
    unknown path or a refused method, and no resource for an unbound body.
    """

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @property
    def headers(self) -> dict[str, str]:
        return {}


class ProvisioningRouteNotFound(ProvisioningRouteResolutionError):
    """No contract names the request's path."""

    status_code = 404


class ProvisioningRouteMethodNotAllowed(ProvisioningRouteResolutionError):
    """A contract names the path, under other methods only."""

    status_code = 405

    def __init__(self, detail: str, *, allowed_methods: tuple[str, ...]) -> None:
        super().__init__(detail)
        self.allowed_methods = allowed_methods

    @property
    def headers(self) -> dict[str, str]:
        return {"Allow": ", ".join(self.allowed_methods)}


class ProvisioningRouteResourceUnbound(ProvisioningRouteResolutionError):
    """The route matches, but its body does not name the resource it binds."""

    status_code = 400

    def __init__(self, detail: str, *, field: str) -> None:
        super().__init__(detail)
        self.field = field


# A route pattern is a sequence of path segments, each a literal, a ``[^/]+``
# named capture, or a finite alternation of literals, optionally ended by
# ``/?``. Kept this small so two contracts can be compared for overlap segment
# by segment; a route that needs more is a reason to adopt an established
# path-template grammar and its matcher, not to widen this one.
_LITERAL = r"[A-Za-z0-9_~-]+"
_SEGMENT = re.compile(
    r"/(?:"
    r"(?P<capture>\(\?P<[A-Za-z_][A-Za-z0-9_]*>\[\^/\]\+\))"
    rf"|(?P<alternation>\((?:\?P<[A-Za-z_][A-Za-z0-9_]*>|\?:)"
    rf"(?P<options>{_LITERAL}(?:\|{_LITERAL})+)\))"
    rf"|(?P<literal>{_LITERAL})"
    r")"
)
_OPTIONAL_SLASH = "/?"
# A pattern compiled with a flag, such as ignoring case, matches paths its
# text does not say, so the comparison over that text would miss an overlap.
_DEFAULT_FLAGS = re.compile("").flags


@dataclass(frozen=True, slots=True)
class _Segment:
    """One path segment a pattern matches: its literals, or ``None`` for any
    non-empty value, as a ``[^/]+`` capture matches."""

    literals: frozenset[str] | None = None

    def meets(self, other: _Segment) -> bool:
        """Whether one value can match both segments."""
        mine, theirs = self.literals, other.literals
        if mine is None:
            return theirs is None or any(theirs)
        if theirs is None:
            return any(mine)
        return not mine.isdisjoint(theirs)


_TRAILING_SLASH = _Segment(frozenset({""}))


def _path_forms(operation: str, pattern: str) -> tuple[tuple[_Segment, ...], ...]:
    """The segment sequences a pattern matches, refusing one outside the grammar.

    A pattern ending in ``/?`` matches two: without the slash, and with it as an
    empty last segment.
    """

    optional = pattern.endswith(_OPTIONAL_SLASH)
    body = pattern[: -len(_OPTIONAL_SLASH)] if optional else pattern
    segments: list[_Segment] = []
    position = 0
    while position < len(body):
        matched = _SEGMENT.match(body, position)
        if matched is None:
            raise ValueError(
                f"route {operation!r} pattern {pattern!r} is outside the route "
                "grammar: literal segments, [^/]+ named captures, finite "
                "alternations of literals, and a terminal /?"
            )
        if matched.group("capture") is not None:
            segments.append(_Segment())
        elif matched.group("alternation") is not None:
            segments.append(_Segment(frozenset(matched.group("options").split("|"))))
        else:
            segments.append(_Segment(frozenset({matched.group("literal")})))
        position = matched.end()
    if not segments:
        raise ValueError(f"route {operation!r} pattern {pattern!r} names no path")
    forms = (tuple(segments),)
    if optional:
        forms += (tuple(segments) + (_TRAILING_SLASH,),)
    return forms


def _overlap(
    first: ProvisioningRouteContract, second: ProvisioningRouteContract
) -> bool:
    """Whether one method and path can match both contracts."""

    if first.method != second.method:
        return False
    return any(
        len(left) == len(right)
        and all(a.meets(b) for a, b in zip(left, right))
        for left in _path_forms(first.operation, first.pattern.pattern)
        for right in _path_forms(second.operation, second.pattern.pattern)
    )


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
        """The bound resource, or ``None`` when the method or path differs.

        Raises :class:`ProvisioningRouteResourceUnbound` when the route matches
        but its body names no resource: the route is this one, so no later
        contract is tried.
        """
        if method.upper() != self.method:
            return None
        matched = self.pattern.fullmatch(path)
        if matched is None:
            return None
        if self.body_resource is not None:
            if not isinstance(body, dict):
                raise ProvisioningRouteResourceUnbound(
                    f"{self.operation} requires a JSON object request body "
                    f"naming body.{self.body_resource}",
                    field=self.body_resource,
                )
            resource = body.get(self.body_resource)
            if resource is None and self.optional_body_resource:
                return ""
            if not isinstance(resource, str) or not resource:
                raise ProvisioningRouteResourceUnbound(
                    f"{self.operation} requires body.{self.body_resource}",
                    field=self.body_resource,
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
    more of this one than this function's input: ``method``, ``path``,
    ``operation``, ``roles``, and optionally ``path_resource`` (a group name,
    or a list of them joined with ``/``), ``body_resource``, and
    ``optional_body_resource``. ``path`` is matched against the whole path and
    is written in the route grammar: ``/``-separated literal segments,
    ``(?P<name>[^/]+)`` captures, finite alternations of literal segments such
    as ``(?P<name>admin|seller)``, and optionally a terminal ``/?``. A pattern
    outside it is refused, naming the route. A declaration must name its
    roles, because the family's operation sets know no domain's routes, and
    every route the provisioning service serves admits the administrator.
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
    if contract.pattern.flags != _DEFAULT_FLAGS:
        raise ValueError(
            f"route {contract.operation!r} pattern {contract.pattern.pattern!r} "
            "is outside the route grammar: it is compiled with flags"
        )
    _path_forms(contract.operation, contract.pattern.pattern)
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
    them. Two contracts of different contributions that one method and path
    could both match are refused when the table is composed, before the
    service accepts traffic, because neither owner can say which signature
    such a request means; so no request is claimed by two contributions.
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
            for earlier in groups:
                for contract in group:
                    for claimed in earlier:
                        if _overlap(contract, claimed):
                            raise ValueError(
                                f"routes {claimed.operation!r} and "
                                f"{contract.operation!r} of different "
                                f"contributions both match {contract.method} "
                                f"{claimed.pattern.pattern} and "
                                f"{contract.pattern.pattern}"
                            )
            groups.append(group)
        self._contracts = tuple(contract for group in groups for contract in group)

    @property
    def contracts(self) -> tuple[ProvisioningRouteContract, ...]:
        return self._contracts

    def resolve(
        self, method: str, path: str, body: Any = EMPTY_BODY
    ) -> tuple[ProvisioningRouteContract, str]:
        """Return the exact authenticated route contract and bound resource.

        Raises the :class:`ProvisioningRouteResolutionError` naming why a
        request resolves to no contract: an unknown path, a path served only
        under other methods, or a body that does not name the route's resource.
        """

        allowed: set[str] = set()
        for contract in self.contracts:
            resource = contract.match(method, path, body)
            if resource is not None:
                return contract, resource
            if contract.pattern.fullmatch(path) is not None:
                allowed.add(contract.method)
        if allowed:
            raise ProvisioningRouteMethodNotAllowed(
                f"{method.upper()} is not served at {path}",
                allowed_methods=tuple(sorted(allowed)),
            )
        raise ProvisioningRouteNotFound(
            f"no authenticated provisioning contract for {method} {path}"
        )


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
