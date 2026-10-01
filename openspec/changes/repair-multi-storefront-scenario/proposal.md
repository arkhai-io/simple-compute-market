# repair-multi-storefront-scenario

## Why

The VM e2e suite carries a two-storefront scenario — Bob and Alice publishing
to overlapping registries — and its Alice negotiation stages cannot pass. The provisioning
service serves one storefront: `ProvisioningIdentityContext.storefront_principal`
is a single `Identity` and the seller role bootstraps one principal, so Alice is
not a trusted caller. Her capacity poller reports `Invalid marketplace
authentication` every cycle, never loads a projection, and a negotiation against
her listing is refused `offer_unfulfillable` for inventory she cannot see.

This is not a regression. The Aug 15 run that was green skipped every Alice
stage, and the skip was incidental rather than declared: `ALICE.*` was absent
from the e2e configuration and `_require_setting` skips on an empty value. So
the scenario was written and then never exercised, and nothing said so.

`repair-storefront-alkahest-configuration` configured Alice while repairing the
suite's identity plumbing, which turned those silent skips into real runs and
made the gap visible. Its scope ends at the fixtures; this one owns the gap.

## What changes

Give Alice a separate provisioning service while Bob retains his own. Configure
each authority with its own service identity and one storefront counterparty.
Seed Alice's inventory through her authority and remove her local derivation
opt-out. Remove the explicit negotiation skips (`06b` and `06c`) and demonstrate
the complete registry scenario passing. Check the actual runtime skip set;
the earlier four-stage estimate is not the acceptance boundary.

## Scope

Two storefronts, each backed by its own provisioning authority. Multiple
storefronts per site are explicitly out of scope. Reuse the identity topology
in `service-identity-signing` and preserve the one-recipient assumption in
`replace-polling-with-authenticated-push`. No new authentication or shared-site
ownership model is introduced.

## Impact

Development topology, service identities, storefront configuration, and e2e
inventory seeding must support two separate authorities. This repair remains a
prerequisite for `pools-9-retire-local-physical-authority`, which removes Alice's
current local derivation path. Both storefronts must consume provisioning
projections and the scenario must pass before that retirement proceeds.

## Permanent documentation impact

- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — separate development authorities.
- [x] `docs/development/TESTING.md` — scenario setup and coverage boundary.
- [x] `docs/development/ROADMAP.md` — reconcile the gap with this accepted scope.

### Knowledge to promote

Alice and Bob each use their own provisioning authority. The scenario proves
registry isolation, fan-in, and distinct negotiations with projection-backed
listings. It does not demonstrate multiple storefronts sharing a site or
shared-hardware storefront substitution.
