## Why

Two lifecycles are reimplemented per storefront over kit-owned state.

The seller's listing lifecycle — close, pause, reopen, and the carry-over of a seller's
close or pause onto a listing that succeeds another — is `ListingService` in the VM
storefront (1,166 lines plus `listing_identity_carryover` at 181), a 170-line service
in API credits, and route handlers inside bare metal's `api.py`. All three mutate the
common listing binding the capacity/publication kit owns and publish the result
through the same registry client; only the listing's domain payload differs.

Restart-safe fulfillment convergence — resuming accepted obligations after a process
restart, driving them to a terminal fulfillment state, and reconciling what the
executor reports with what the storefront recorded — is `fulfillment_resume_runtime`
(774) plus `fulfillment_service` (477) in VM, `hosted_lifecycle` (949) plus
`fulfillment_service` (527) in bare metal, and a 206-line service in API credits. The
convergence mechanism is the same in each; the executor payload and the result
decoding are the domain's.

The VM storefront also keeps `site_projection_cache` (270 lines) as its own view of
per-site projection state, while bare metal reaches the same state through the
capacity/publication kit's declaration reader and per-site hold.

## What Changes

- Move the seller listing lifecycle into `kit/capacity-publication`, over the common
  binding it already owns: close, pause, reopen, and successor carry-over, with the
  domain supplying its payload codec and its successor-identity rule.
- Move restart-safe fulfillment convergence into kit: obligation resumption after
  restart, terminal-state driving, executor-result reconciliation, and teardown
  independence, with the domain supplying the executor payload, result decoding, and
  effects.
- Replace the VM storefront's `site_projection_cache` with the capacity/publication
  kit's per-site projection state.
- Compose all three domains and remove every domain-local copy in this change.
- Record, per concern, where the copies diverged and which behavior was chosen.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: listing lifecycle and fulfillment convergence are kit-owned.
- `storefront-publication`: the seller listing lifecycle is one mechanism over the
  common binding.

## Non-Goals

- Do not extract the shell, authentication, or persistence residue — sibling changes.
- Do not change fulfillment semantics for any domain; a divergence between copies is
  recorded and one behavior chosen, not silently adopted.

## Impact

- Code: VM `services/listing_service.py`, `listing_identity_carryover.py`,
  `fulfillment_service.py`, `fulfillment_resume_runtime.py`, `site_projection_cache.py`;
  API-credit `listing_service.py`, `fulfillment_service.py`; bare-metal
  `fulfillment_service.py`, `hosted_lifecycle.py`, and the listing handlers in `api.py`.
  `kit/capacity-publication` and a fulfillment convergence kit gain the mechanisms.
- Tests: three domains' listing and fulfillment suites collapse into kit suites plus
  per-domain hook conformance.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — package layers.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`,
      `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification

### Knowledge to promote

- Listing lifecycle and fulfillment convergence are kit-owned; a domain supplies
  payload codecs, executor payloads, and effects —
  `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `kit-owned-storefront-shell`, whose shared routes dispatch to these
  lifecycles.
- Builds on `kit-owned-capacity-and-publication` (the common binding) and
  `kit-owned-settlement-runtime` (archived; the obligation journal fulfillment
  convergence reads).
- `bare-metal-mock-provisioned-deal`'s restart-recovery assertions exercise the
  convergence mechanism for bare metal.
