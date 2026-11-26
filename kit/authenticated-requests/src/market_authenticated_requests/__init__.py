"""The admission core every authority authenticates its requests through.

An authority builds one :class:`AdmissionCore` over its signer, its trust, and a
replay store bound to its own database (:func:`sqlite_replay_store`, or
``market_authenticated_requests.sqlalchemy_support.sqlalchemy_replay_store`` with
the ``sqlalchemy`` extra), and wraps its application with :func:`install`. In the
middleware form it passes its route table; in the dependency form each route takes
a :class:`RouteAdmission`. Its migration chain composes the replay table's
migration, and its lifespan :meth:`AdmissionCore.sweeping`. Its settings compose
:class:`AuthenticatedRequestsSettings` as ``authenticated_requests``.
"""

from market_authenticated_requests.application import AuthenticatedApplication
from market_authenticated_requests.core import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_SKEW_SECONDS,
    ROUTE_FAILURE_DETAIL,
    Admitted,
    AdmissionCore,
    Answer,
    SignedOutcome,
)
from market_authenticated_requests.dependency import RouteAdmission
from market_authenticated_requests.inventory import RouteInventoryError, install, undeclared_routes
from market_authenticated_requests.migrations import (
    REPLAY_TABLE,
    REPLAY_TABLE_MIGRATION_ID,
    SQLITE_REPLAY_TABLE_MIGRATION,
    replay_table_statements,
    sqlite_replay_store,
)
from market_authenticated_requests.routes import (
    DOCUMENTATION_PATHS,
    ResourceUnbound,
    RouteBinding,
    RouteNotServed,
    RouteTable,
    Unauthenticated,
    fixed_resource,
    path_resource,
)
from market_authenticated_requests.settings import AuthenticatedRequestsSettings

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_SKEW_SECONDS",
    "DOCUMENTATION_PATHS",
    "REPLAY_TABLE",
    "REPLAY_TABLE_MIGRATION_ID",
    "ROUTE_FAILURE_DETAIL",
    "SQLITE_REPLAY_TABLE_MIGRATION",
    "Admitted",
    "AdmissionCore",
    "Answer",
    "AuthenticatedApplication",
    "AuthenticatedRequestsSettings",
    "ResourceUnbound",
    "RouteAdmission",
    "RouteBinding",
    "RouteInventoryError",
    "RouteNotServed",
    "RouteTable",
    "SignedOutcome",
    "Unauthenticated",
    "fixed_resource",
    "install",
    "path_resource",
    "replay_table_statements",
    "sqlite_replay_store",
    "undeclared_routes",
]
