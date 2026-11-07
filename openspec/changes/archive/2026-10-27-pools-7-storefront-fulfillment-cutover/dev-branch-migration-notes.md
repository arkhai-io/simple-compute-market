# Dev-branch migration notes (reverted overnight merge)

This document exists because a `dev`-branch merge into this change's Section 5
branch was reverted in full (see this change's session history —
the merge had unresolved conflicts committed into production code, an
archived-and-renumbered copy of this entire change, and a redesigned
`FulfillmentProvider` contract incompatible with the one this change
accepted in Section 5).

None of the code referenced here is present in the codebase. It is recorded
solely as **candidate material for the design-review discuss phase of the
POOLS-7 sections it would have implemented**, so that work is not silently
lost, and so future design discussions can evaluate it deliberately rather
than inherit it by accident. Every item below needs to be re-evaluated
against, and refactored to, this change's actual accepted contracts
(notably `FulfillmentProvider.prepare_create`/`prepare_teardown` keeping the
`pool_config` parameter, and the Section 6 decisions already recorded in
`design.md`) before any of it is treated as a starting point for
implementation. Nothing here is an accepted decision.

## Candidate material for Section 6 (recovery and lifecycle convergence)

Dev's branch had a working, single-class recovery/convergence service
(`FulfillmentRecoveryService`, in `compute_provisioning_service/services/`)
that is largely consistent with the Section 6 discuss-phase decisions
already recorded in `design.md`: one asyncio loop, a short claim
transaction (`repository.claim_pending`/`clear_claim`) released before any
provider call, exponential backoff with jitter, no attempt-count exhaustion
auto-failure, and no separate abandonment-reconciliation handler. Worth
comparing against when Section 6 is actually planned and implemented —
particularly its `diagnostics()` method, which is a reasonable shape for
the stuck-claim/retry-age operator metrics task 6.5 already asks for.

It diverges from the accepted Section 6 discussion on one point flagged
during that discussion (design question 6): it populated
`ProvisionedResource` rows from a `provisioned_resource_refs` field added
directly onto `FulfillmentResult` (the `dispatch_create`/`dispatch_teardown`
return value), created at submission time rather than at confirmed-success
convergence time. The accepted resolution was a separate, pure
`resolve_provisioned_resources(provider_metadata)` method called only once
`get_status` reports `succeeded`. Re-derive from the accepted shape, not
from this file, if it's used as a reference.

## Candidate material for Section 7 (legacy fulfillment migration/backfill)

A domain-neutral `LegacyFulfillmentBackfillCompiler` protocol
(`kit/fulfillment/.../backfill.py`) plus a per-adapter compiler
(`compile_legacy_vm_fulfillment_backfill`, VM adapter) is a reasonable
shape for this section: given validated historical executor coordinates
(host, target, job IDs, playbook path, extra vars), it synthesizes a
`LegacyFulfillmentBackfillDraft` carrying `provider_metadata` *and* an
already-frozen `prepared_teardown_operation` — so a backfilled row is
recovery-ready immediately, without Section 6's convergence logic needing
to reconstruct a teardown command for data that predates this change. This
"freeze the teardown command at backfill time, not at first teardown
request" idea is worth keeping regardless of whether the rest of the file
is.

## Candidate material for Section 8 (pull-based fulfillment status/result and live credentials)

`FulfillmentService.get_result` (compute-provisioning-service) sketches a
live-credential-rotation flow that goes beyond a single get-status/get-result
split: a claim/lease on the settlement row (reusing the Section 6 claim
primitive) guards a call to a new provider method,
`get_live_credentials(capacity_reservation_id, resource, provider_metadata,
credential_generation=...)`, returning a `LiveCredentialResult` (new
`provider.py` dataclasses `LiveCredential`/`LiveCredentialResult`); on
`rotated=True` it advances a `credential_generation` counter via
`complete_credential_rotation`, otherwise it just clears the claim. This is
materially more than what task 8's current scope describes (which is a
pull-based status/result query, not credential lifecycle) — worth a
deliberate scope conversation before Section 8 is planned: is live
credential rotation in scope for this change at all, or a later one? If
it's in scope, this is a reasonable starting shape, refactored onto
whatever `ProviderStatus`/result contract Section 6/8 actually settle on.

## Candidate material for Section 9 (storefront orchestration cutover)

Three pieces, all replacing the old synchronous `vm_fulfillment_service.py`/
`provisioning_orchestration_service.py` create-and-wait orchestration:

- `StorefrontFulfillmentReconciler` — a storefront-side, claim/lease-based
  reconciler (its own worker id, its own claim/release cycle) driving a new
  `fulfillment_workflow_store` table through phases against the durable
  provisioning-side fulfillment API, instead of blocking on an in-process
  create-and-wait call. The restart-safety argument for doing this on the
  storefront side too (not just provisioning-side) is worth evaluating on
  its own merits when Section 9 is planned.
- `fulfillment_requests.py`'s `build_vm_fulfillment_requests` — a focused,
  single-purpose translation from an accepted VM listing/order into a
  `FulfillmentScheduleRequest`/`FulfillmentBeginRequest` pair. Small and
  probably close to directly reusable regardless of the rest.
- `provisioning_sites.py` — resolves operator-configured, potentially
  *multiple* provisioning-service base URLs/admin keys keyed by site ID,
  rather than the single hardcoded provisioning URL the storefront uses
  today. Only relevant if multi-site provisioning is actually in scope
  anywhere in this change; flagging because it's a bigger architectural
  commitment than it looks and shouldn't be adopted implicitly.

## Candidate material for Section 10 (teardown and physical-resource reclamation)

`FulfillmentReleaseBridge.ensure_teardown` is a small, focused bridge
called from the existing lease-expiry path: given a `capacity_reservation_id`,
it looks up the settlement record and, if fulfillment owns an `active` or
`teardown_failed` resource, calls `FulfillmentService.begin_teardown`
instead of the old direct-release path. The return value (whether
fulfillment owns release at all) is the integration point `LeaseLifecycleService`
would need. Small enough to be close to directly usable as a starting point
once Section 10 is actually planned.

## Flagged as new, unscoped, cross-cutting work — needs its own discuss phase

**Multi-principal storefront authentication and per-record ownership.**
`StorefrontAuthMiddleware` was extended from a single shared `X-Admin-Key`
gate to `configured_storefront_principals`, a mapping of distinct
principal → secret bindings (with the old shared key preserved as one
named `legacy-admin` principal), setting `request.state.storefront_principal`
per request. `SettlementRecord` gained an `owner_principal` column, and
every fulfillment operation in `FulfillmentService` (`get_status`,
`get_result`, `begin_fulfillment`, `begin_teardown`) checks the caller's
principal against it before returning anything. This is a real, coherent
design for a provisioning service serving more than one storefront/tenant
— but it touches every fulfillment API surface, the settlement schema, and
site-capacity, and nothing in `proposal.md` scopes POOLS-7 to include it.
This needs an explicit decision — its own proposal/discuss phase, most
likely, rather than folding into whichever section happens to touch the
same files — before any of it is adopted.

**Bare-metal domain's parallel fulfillment cutover.** Dev's branch also
built a bare-metal-domain equivalent of this entire change: a bare-metal
`ansible_fulfillment_provider.py`/`fulfillment_model.py` (adapter side) and
new `site_capacity.py`/`site_config.py`/`site_routing.py` (storefront
side). `proposal.md` scopes this change to the VM storefront only. Whether
bare-metal gets its own POOLS-7-shaped change, and whether any of this is a
useful starting point for it, is a decision for whoever owns that domain
roadmap — noted here only so it isn't lost, not evaluated further.

## Not carried forward for re-evaluation

Adapter/module `README.md` additions and the corresponding new test files
for everything above are not separately summarized — they're bound to the
code they document/test, so they stand or fall with whichever section
above eventually revisits that code.
