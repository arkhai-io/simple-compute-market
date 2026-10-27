"""The contracts' route declarations as the site kit's route contracts, in declaration order."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from arkhai_api_contracts.routes import AUTHORITY_ROUTES
from market_site.auth import SiteRouteContract


def site_route_contracts(
    declarations: Iterable[Mapping[str, Any]] = AUTHORITY_ROUTES,
) -> tuple[SiteRouteContract, ...]:
    """The table request authentication reads, from the declarations the client signs from."""

    return tuple(
        SiteRouteContract(
            method=declaration["method"],
            pattern=re.compile(declaration["path"]),
            operation=declaration["operation"],
            allowed_roles=frozenset(declaration["roles"]),
            path_resource=declaration.get("path_resource"),
            body_resource=declaration.get("body_resource"),
            optional_body_resource=declaration.get("optional_body_resource", False),
            exact_retry_safe=declaration.get("exact_retry_safe", True),
        )
        for declaration in declarations
    )
