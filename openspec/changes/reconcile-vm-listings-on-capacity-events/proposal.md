# Reconcile VM listings on capacity events

## Why

A capacity-backed VM listing is a finite standing offer. Exhaustion must close it in registry discovery; authoritative release must reopen the same ID when its full advertised shape fits again. Registry failure must neither fail settlement nor strand discovery until another capacity mutation.

The approved base is `integration/arkhai-payments` at `4881ca816`. It already has full-shape feasibility, closure provenance, per-registry convergence, same-ID reopen and a 30-second publication loop. The remaining gaps are fresh projection inputs before event decisions, serialization with publication, quiet-cycle recovery and missing delivery records.

## What Changes

- Refresh both site projection families before applying the existing fit decision, for `fungible` and `specific_resource` listings. Unavailable refreshes are unknown, not zero.
- Serialize capacity close/reopen and commercial publication over the same runtime boundary. Always reconsider current capacity rather than replaying event direction as desired state.
- Run convergence from the existing capacity lifecycle on startup and quiet cycles, using existing durable listing intent and per-registry records, including missing delivery records.
- Reuse persisted candidates and seller-closure guards; introduce no fit predicate, closure schema, outbox or settlement-side registry call.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: fresh, serialized capacity reconciliation and restart-safe registry convergence.

## Non-Goals

Negotiation probes, resizing, new shapes, multidimensional-publication policy, multi-unit checkout, last-slot arbitration, hold/release policy, other domain semantics, live hosted purchases and deployment pin changes.

## Impact

Runtime owners are the capacity-publication kit, core publication persistence and VM projection/capacity/publication adapters. No public API or database schema changes. Internal wheels must be rebuilt and explicitly reinstalled. Rollout requires a new storefront image digest and the corresponding infrastructure source pin; existing signer/writer credentials and the existing worker process suffice. This change neither deploys nor attests to live readiness.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — refreshed serialized event-to-registry flow outside settlement.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md` and companion `architecture.md`.
- [ ] New subsystem specification.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — capacity recovery cadence and existing auth prerequisites.

### Knowledge to promote

Fresh-known inputs, shared serialization, stable-ID and seller intent, durable per-registry quiet/restart recovery belong to storefront-publication. Cross-system settlement isolation belongs to repository architecture. Polling and process/credential prerequisites belong to deployment guidance.
