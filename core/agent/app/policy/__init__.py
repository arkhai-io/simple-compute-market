"""Provider-side compute-domain policy seeding.

The domain-agnostic engine lives in `market_policy`; this package
holds only the provider's compute-domain seeder
(`ComputePolicySeeder`), which wires up default policies for the
local triggers the storefront reacts to (ORDER_CREATE, ORDER_CLOSE,
RESOURCE_IMBALANCE).
"""
