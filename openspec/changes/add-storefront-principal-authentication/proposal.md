## Why

`StorefrontAuthMiddleware` (`provisioning/compute/service`) gates the whole compute provisioning API behind one shared `admin_api_key`. By its own docstring, "the provisioning service is an internal dependency of a single storefront" — there is no per-request caller identity today, only "this request carries the one secret my storefront knows." That is fine as a network-crossing gate, but it means no endpoint can express "does this caller own this record," because there is no second identity to compare against.

Two changes now need exactly that. `pools-7-storefront-fulfillment-cutover` Section 8 (`get_fulfillment_status`/`get_fulfillment_result`) originally scoped a per-caller ownership check as task 8.5; discussion on 2026-07-25 concluded that check can't mean anything under the current model and moved it here rather than fake it. `provisioning-result-push-delivery` separately lists "where storefront-owner binding is created and rotated" as an open question it cannot resolve on its own, since its own scope is the *transport* half (an authenticated provisioning→storefront delivery channel), not the *identity* half. Building the identity model once, here, avoids the pull direction and the push direction inventing two different notions of "which storefront is this."

## What Changes

- Extend `StorefrontAuthMiddleware` from a single shared `admin_api_key` to `configured_storefront_principals`: named principal → secret bindings. The existing shared key remains valid as one built-in default principal, so a single-tenant deployment needs no configuration change to keep working.
- Set an authenticated principal identity on every admitted request (`request.state.storefront_principal` or equivalent), available to any downstream handler that needs it.
- Add an `owner_principal` column to `SettlementRecord` (`kit/fulfillment`), populated at the point a reservation's settlement record is first created on behalf of a caller, not backfilled after the fact.
- Provide one shared "does this principal own this record" check, callable by any provisioning-service endpoint that needs per-caller ownership enforcement, rather than a bespoke comparison per endpoint.
- State: **New prerequisite capability. Not yet planned — see `design.md`'s Open Questions before task planning begins.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: multi-principal authentication and per-request caller identity, replacing the single shared admin key as the only identity primitive.
- `fulfillment`: `owner_principal` on the durable settlement aggregate and the shared ownership-check contract consumed by pull status/result queries.

## Non-Goals

- Do not implement provisioning→storefront (reverse/push) transport authentication. That remains `provisioning-result-push-delivery`'s own scope; it depends on this change for identity, not the other way around, and its reverse-transport mechanism (mTLS, signed request, rotated token, or otherwise) is a separate open decision this change does not make.
- Do not implement per-caller ownership enforcement everywhere a caller identity could theoretically apply (reservation creation, scheduling, site-capacity reads). Scope enforcement to what `pools-7-storefront-fulfillment-cutover` Section 8 needs; extend to other endpoints only under a separately proposed change if a real caller needs it.
- Do not add multi-site-per-storefront routing (the storefront resolving several provisioning-service base URLs/keys, sketched as `provisioning_sites.py` in `pools-7-storefront-fulfillment-cutover/dev-branch-migration-notes.md`). That is flagged there as "a bigger architectural commitment than it looks" and is not part of this change.
- Do not replace the single-shared-key deployment as the supported default; multi-principal configuration is additive, not required.
- Do not select a credential-rotation mechanism for principal secrets themselves before the deployment/operator story is discussed (see `design.md` Open Questions).

## Dependencies and Related Changes

- `pools-7-storefront-fulfillment-cutover` Section 8 depends on this change for real per-caller ownership enforcement on `get_fulfillment_status`/`get_fulfillment_result`. Section 8 ships first against an existence-only check (task 8.5, narrowed 2026-07-25) and adopts the `owner_principal` comparison once this change lands, without reshaping the endpoint.
- `provisioning-result-push-delivery` hard-depends on this change's identity/ownership model for its own "operator-trusted owner/site credential bindings" goal; its reverse-transport authentication mechanism remains its own, separate, still-open decision.
- Candidate starting shape: `pools-7-storefront-fulfillment-cutover/dev-branch-migration-notes.md`, "Flagged as new, unscoped, cross-cutting work: Multi-principal storefront authentication and per-record ownership" — `configured_storefront_principals`, `request.state.storefront_principal`, `owner_principal` column, per-call principal check on every fulfillment operation. That note explicitly says this needs its own discuss phase before adoption; this change is that discuss phase.

## Impact

- Provisioning services gain named per-storefront credentials instead of one shared secret; existing single-key deployments are unaffected unless they opt in.
- `SettlementRecord` gains a durable column and a migration.
- Deployment/operator configuration gains an optional set of per-storefront principal secrets to provision (Compose/Helm), on top of the existing single key.

## Permanent documentation impact

- [ ] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` (auth model, multi-principal request identity)
- [ ] Existing subsystem specification: `openspec/specs/fulfillment/spec.md` (`owner_principal`, shared ownership-check contract)
- [ ] No `ARCHITECTURE.md` change anticipated unless the design phase concludes repository-wide auth vocabulary needs updating

### Knowledge to promote

- <to be completed once the design phase resolves the Open Questions in `design.md`>
