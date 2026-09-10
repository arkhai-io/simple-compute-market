# Design

## Decisions

- `contactDeclarations` uses the same reference vocabulary as `contactOffers`;
  the schema reuses that shape, not the Python declaration carrier.
- The general hook's `configMap` and `registry.apiKeySecret` must be addressable:
  a DNS-subdomain object name and a ConfigMap/Secret data key. The schema reuses
  the strict reference definition already applied to delivery configuration, now
  named `resourceDataReference` because it constrains ConfigMap references too.
  A ConfigMap/Secret data key is projected as a file name, so Kubernetes also
  reserves `.` and any key starting with `..`. Those characters are otherwise legal,
  so the general hook adds a `projectableDataKey` overlay on top of the shared
  definition rather than a second key pattern; JSON Schema `not`/`const` and an
  anchored `^\.\.` pattern express the rule without a lookahead, which Helm's
  validator does not support. A single leading dot and embedded double dots stay
  valid, so this is a reserved-prefix rule, not a dot ban.
  Neither constraint is applied to `contactOffers`, delivery configuration or other
  historical references, which keep their existing checks; tightening them would
  refuse manifests that render today, which is outside this amendment.
- Exactly one publication mode may be configured. Both null retain default-off
  behavior. Conflicting objects fail schema validation and template rendering.
- Both modes use the existing read-only `contact-offers` volume and
  `/etc/arkhai/contact-offers/offers.json` projection. Only the general mode emits
  `BARE_METAL_STOREFRONT_CONTACT_DECLARATIONS_PATH`; historical mode retains
  `BARE_METAL_STOREFRONT_CONTACT_OFFERS_PATH` and its exact rendered bytes.
- Shared publication selection governs registry inputs, site exclusion, mounts
  and startup probe allowance. Delivery Secret projection is independent.
- Private settlement, own routes, shareable text and SMTP remain role-owned Secret
  inputs. Helm checks references; installed Python owns file/profile validation.

## Alternatives and compatibility

Reinterpreting `contactOffers` by file version would widen the historical hook and
hide enrollment. Duplicating the general carrier in Helm would create competing
validation authorities. Retroactively validating historical reference names would
change existing acceptance rather than add a hook. All three are rejected. No
migration or wheel rebuild is needed: Python package contents must compare
byte-for-byte with installed qualified wheels.
Default physical, runtime-only, historical publication, delivery and persistent-claim
permutations are compared as complete render bytes against pre-amendment source.

## Validation boundary

Focused Helm validation covers reference rejection, conflicting modes, public/private
separation and mounted path agreement. A rendered-environment startup test drives the
installed server's actual loaders and preparation with disposable files/database and
an external registry boundary double, never a copied declaration implementation.
Local checks establish neither release provenance nor actual registry/SMTP activation.

## Design promotion record

| Accepted decision | Permanent location | Status |
|---|---|---|
| Reference-only exclusive chart hooks, strict general references and unchanged defaults | `openspec/specs/storefront-publication/spec.md` | Promoted and validated |
| Shared mounts and runtime validation authority | `openspec/specs/storefront-publication/architecture.md` | Promoted |
| Values, environment and private delivery inputs; reference syntax versus resource existence | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Promoted |
| Amendment status/index placement | `openspec/changes/README.md` | Reconciled at archival |

No repository-wide architecture, capability index or roadmap goal changes are
required. There are no unresolved product decisions in this bounded amendment.

Independent review found no remaining issues after the general-reference corrections.
Post-promotion checks passed 158 focused chart/startup/publication tests, all 20
historical full-render byte comparisons, Helm lint and the owning render target.
Ninety-four relevant packaged files still match source, wheels and installed files;
all 22 qualified wheel hashes are unchanged. Scoped change and owning-spec validation,
comment/import review and documentation links passed. Repository-wide OpenSpec's
12 pre-existing failures and the unrun full-system/typing/release checks remain
disclosed. This amendment does not rerun or supersede the archived full exchange
qualification. The CLI/chart enrollment gap is recorded in `docs/frictions.md`.
