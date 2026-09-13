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

## What unblocking requires

`ProvisioningIdentityContext` holds `storefront_principal: Identity` and
`SqlAlchemyProvisioningPrincipalAuthority` bootstraps the `seller` role from it.
The authority already supports multiple principals per role — rotation carries
an overlap window in which two are trusted — so the constraint is the single
configured identity rather than the trust model.

That suggests the smaller shape: configure a set of storefront principals
rather than one, and let each carry its own site binding, since
`storefront_site_id` is likewise singular today. Whether a storefront principal
should imply a site, or the two should be configured independently, is the open
question and belongs to this change rather than to a skip marker.

## Deliberately not addressed

Several provisioning services serving one storefront. That is the inverse
relation, has its own roadmap treatment, and shares none of this change's
mechanism.
