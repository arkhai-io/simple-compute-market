# repair-multi-storefront-scenario

## Why

The VM e2e suite carries a two-storefront scenario — Bob and Alice publishing
to overlapping registries — and four of its stages cannot pass. The provisioning
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

Nothing yet. The four blocked stages are skipped with the reason recorded at the
call site, and this change holds the work to unblock them:

- Let the provisioning service trust more than one storefront principal, so a
  second commercial front-end over the same hardware is a configuration rather
  than a rebuild.
- Confirm the remaining Alice stages — registry isolation and fan-in, which are
  the scenario's actual subject — pass once the suite next runs, and record any
  that do not as findings rather than assuming.

## Scope

One provisioning service serving several storefronts. The inverse — several
provisioning services serving one storefront — is separate work and is not
addressed here.

## Impact

Until this lands, the suite reports four skips where it previously reported four
silent absences. That is strictly more informative and is the only change to
current behaviour.

Alice's storefront derives its listings from local tables
(`storefront.alice.toml` sets `use_site_projection_for_listings = false`)
because provisioning does not trust her and she can load no projection.
`pools-9-retire-local-physical-authority` deletes that path, so its cutover and
its migration of `test_multi_registry.py` to provisioning-seeded inventory
depend on this change. Once provisioning trusts Alice, her inventory is seeded
through provisioning like Bob's and the opt-out goes.

When it lands, a storefront becomes substitutable in practice: the property
`docs/development/ROADMAP.md` Goal 1 names as the value of consolidating
physical authority in the provisioning service, and which nothing currently
demonstrates end to end.

## Permanent documentation impact

- [x] Roadmap goal state changes

### Knowledge to promote

Goal 1's open-gap table gains this gap and names this change as its owner. The
goal already argues that consolidating physical authority is what makes a
storefront replaceable "by a different commercial front-end over the same
hardware"; that the provisioning service cannot presently serve two is a
current-state fact the goal should carry rather than leave to a skip string.
