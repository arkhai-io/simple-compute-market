"""Test profiles and labels; nothing here names a deployed domain's values."""

from arkhai_api.labels import IssuanceLabel
from arkhai_api_authority import AuthorityConfig, CapacityProfile
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
    resource_type="example.units",
)
CONFIG = AuthorityConfig(
    label=LABEL, profile=PROFILE, database_url="sqlite:///:memory:", distribution="example-service",
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
        resource_type="example.units",
    )
    return AuthorityConfig(
        label=IssuanceLabel(offering_mode.replace("_", "-")), profile=profile,
        database_url="sqlite:///:memory:", distribution="example-service",
    )
