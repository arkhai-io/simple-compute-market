# Design — repair-multi-storefront-scenario

## Why skip rather than delete or xfail

Three options, and the choice matters because this scenario has already been
invisible once.

Deleting the stages would remove the only end-to-end statement of a property
the roadmap treats as a goal. It would also lose the scenario's *working*
coverage by association: only four of its stages need a second served
storefront, and the rest — Alice publishing to registry-A, her absence from
registry-B, fan-in returning two unique listings, resilience to a dead registry
— are the scenario's actual subject and are unaffected.

`xfail` would report an eventual pass as "unexpectedly passing", which reads as
a problem rather than as the capability arriving. It also quietly tolerates the
stage failing for a *different* reason than the one recorded, which is how a
known limitation becomes cover for an unrelated defect.

A skip with the reason at the call site says what is missing, names the roadmap
goal and the owning change, and reports every run. It is the option that cannot
be mistaken for either health or breakage.

## Why the stages were not already skipped

They were, in effect, and that is the more interesting failure. `ALICE.*` was
absent from the e2e configuration, and `_require_setting` calls `pytest.skip`
on an empty value — so every Alice stage skipped for want of a setting, with no
statement anywhere that the scenario could not run. A reader of the Aug 15
green run saw "99 passed, 12 skipped" and no reason to look further.

An incidental skip and a declared one are indistinguishable in a summary line
and opposite in meaning. This change replaces the remaining incidental skips
with declared ones, and the configuration stays: reverting it would restore the
silence.

## Accepted topology and unblocking

Alice and Bob are separate storefronts. Give each a separate provisioning
service instance with its own authority identity, configured storefront
counterparty, callback destination, and inventory. Alice must consume her
authority's projections and stop using local-table listing derivation.

This preserves the topology in `service-identity-signing` and
`replace-polling-with-authenticated-push`: each site uses its own credential,
distinct from the storefront's, and each authority serves one storefront.
Neither change needs a topology amendment for this repair.

Rotation overlap accepts credential generations of the same counterparty;
it must not be used to introduce an independent storefront. The earlier
proposal to configure several sellers on one authority is rejected.

Acceptance proves registry isolation, fan-in, and distinct negotiations across
two projection-backed storefronts, not shared-site storefront substitution.
The explicit blocked-stage skips are `06b` and `06c`; verify the actual runtime
skip set rather than relying on the earlier four-stage estimate.

During planning, identify the exact compose, identity, configuration, seeding,
and test files needed for Alice's separate authority and isolated service state.

## Deliberately not addressed

Multiple storefronts per site, shared-authority ownership and routing, new
authentication protocols, general push delivery, and expanding this scenario
to multiple sites per storefront are out of scope.
