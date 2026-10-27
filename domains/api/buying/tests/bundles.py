"""A neutral domain's buying bundle, so no real domain's values enter these tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_api.purchase import provision_terms_model

from arkhai_api_buying.contributions import BuyingContributions, ListingRendering

TERMS = provision_terms_model("example.v1")


def _resource(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


CONTRIBUTIONS = BuyingContributions(
    schema_id="example",
    provision_terms=TERMS,
    command="example",
    command_help="Example market.",
    noun="example",
    resource_query_example="product=alpha",
    rendering=ListingRendering(
        resource=_resource,
        summary_header="Product",
        summary=lambda resource: str(resource.get("product") or "-"),
    ),
)
