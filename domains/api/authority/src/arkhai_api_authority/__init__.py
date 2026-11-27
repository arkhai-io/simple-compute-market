"""The api family's authority: keys, grants, consumption, and quota as capacity, composed by a service root."""

from arkhai_api_authority.database import (
    IncompatibleDatabase,
    check_database,
    create_db_engine,
    create_session_factory,
    migrate_database,
    require_migrated,
)
from arkhai_api_authority.declarations import site_route_contracts
from arkhai_api_authority.initialization import initialize, load_pool_directory
from arkhai_api_authority.keys_service import IssuanceError, KeysService, derive_key_id
from arkhai_api_authority.migrations import authority_chain
from arkhai_api_authority.profile import AuthorityConfig, CapacityProfile
from arkhai_api_authority.route_services import AuthorityRouteService, RouteRefusal, SystemRouteService

__all__ = [
    "AuthorityConfig",
    "AuthorityRouteService",
    "CapacityProfile",
    "IncompatibleDatabase",
    "IssuanceError",
    "KeysService",
    "RouteRefusal",
    "SystemRouteService",
    "authority_chain",
    "check_database",
    "create_db_engine",
    "create_session_factory",
    "derive_key_id",
    "initialize",
    "load_pool_directory",
    "migrate_database",
    "require_migrated",
    "site_route_contracts",
]
