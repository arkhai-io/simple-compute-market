from market_schema_migrations import Floor
"""Test profiles, labels, and chain; nothing here names a deployed domain's values."""

from arkhai_api.labels import IssuanceLabel
from arkhai_api_authority import AuthorityConfig, CapacityProfile, authority_chain
from market_resource_pools_contracts import BACKED

LABEL = IssuanceLabel("example")
PROFILE = CapacityProfile(
    offering_mode="example",
    pool_provider="example",
    pool_id="default",
    pool_label="Default Pool",
    deliverable_modes=frozenset({"example"}),
    advertisable_modes=frozenset({"example"}),
    backing=BACKED,
)
COMMAND = "example-service-migrate"
CHAIN = authority_chain(service="the example service", command=COMMAND, floor=Floor("0.0.0"))
CONFIG = AuthorityConfig(
    label=LABEL, profile=PROFILE, database_url="sqlite:///:memory:", distribution="example-service",
    key_prefix="ak",
)


def config_for(offering_mode: str) -> AuthorityConfig:
    profile = CapacityProfile(
        offering_mode=offering_mode,
        pool_provider=offering_mode,
        pool_id="default",
        pool_label="Default Pool",
        deliverable_modes=frozenset({offering_mode}),
        advertisable_modes=frozenset({offering_mode}),
        backing=BACKED,
    )
    return AuthorityConfig(
        label=IssuanceLabel(offering_mode.replace("_", "-")), profile=profile,
        database_url="sqlite:///:memory:", distribution="example-service", key_prefix="ex",
    )
