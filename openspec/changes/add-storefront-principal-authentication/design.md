## Context

`StorefrontAuthMiddleware` (`provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py`) currently compares one presented `X-Admin-Key` header against one configured `admin_api_key`. There is no per-request caller identity: the gate answers "is this my storefront" as a single yes/no, not "which storefront is this." Every durable record the provisioning service holds (capacity reservations, settlement records) is consequently ownerless in the schema — access control is entirely at the network/transport layer, not the record layer.

Two other in-flight changes need a caller identity this model doesn't provide:

- `pools-7-storefront-fulfillment-cutover` Section 8 wanted a per-caller ownership check on `get_fulfillment_status`/`get_fulfillment_result` (originally task 8.5). Discussion on 2026-07-25 concluded that check is currently unimplementable as a real ownership check and narrowed Section 8 to an existence-only check pending this change.
- `provisioning-result-push-delivery`'s own `design.md` lists "where storefront-owner binding is created and rotated, and which service is authoritative for its public destination" as an open question it explicitly does not resolve.

A reverted `dev`-branch merge (recorded in `pools-7-storefront-fulfillment-cutover/dev-branch-migration-notes.md`) sketched a candidate shape for exactly this: `configured_storefront_principals` (principal → secret bindings, the existing key preserved as a `legacy-admin` principal), `request.state.storefront_principal` set per request, an `owner_principal` column on `SettlementRecord`, and a per-call check in every fulfillment operation (`get_status`, `get_result`, `begin_fulfillment`, `begin_teardown`). That code was reverted along with unrelated conflicts and an incompatible `FulfillmentProvider` contract, and is recorded only as candidate material — nothing here is inherited without re-evaluation.

## Goals / Non-Goals

**Goals:**
- Give the provisioning service real per-request caller identity, additive to the existing single-shared-key deployment (no forced migration).
- Make `pools-7-storefront-fulfillment-cutover` Section 8's ownership check meaningful without redesigning its endpoint shape.
- Resolve the identity/ownership half of what `provisioning-result-push-delivery` needs, without taking on its transport half.

**Non-Goals:**
- Select `provisioning-result-push-delivery`'s reverse-transport authentication mechanism (mTLS, signed request, rotated token). That remains open there.
- Enforce ownership on every provisioning-service endpoint. Scope to what Section 8 needs now; extend later under separate proposals.
- Multi-site-per-storefront routing (the storefront side of a many-to-many topology). Flagged in `dev-branch-migration-notes.md` as its own bigger commitment.

## Decisions

### Extend the existing middleware rather than add a second auth mechanism

`StorefrontAuthMiddleware` already sits in the right place (every request, before routing) and already carries the right secret-comparison primitive. Multi-principal support is `configured_storefront_principals: dict[str, str]` (principal name → secret), checked the same way the single key is today, with the existing `admin_api_key` config value continuing to work unchanged as one implicit principal. This avoids a second parallel gate with its own failure modes.

### `owner_principal` is written once, at record creation, not retrofitted

Following the pattern `pools-7-storefront-fulfillment-cutover` Section 4 already established for `schedule_resource`'s one-transaction boundary, `owner_principal` is set on `SettlementRecord` in the same transaction that creates the row, from the authenticated request's principal — never inferred later from a caller-supplied value, and never mutable after creation (matching the existing immutable-identity-fields rule already documented for `market`/scheduling identity).

### One shared ownership-check helper, not per-endpoint comparisons

A single callable (exact shape TBD — likely `require_owner(record, principal)` or similar) that every ownership-sensitive endpoint calls, rather than each handler writing its own `record.owner_principal == principal` comparison. Keeps future endpoints (site-capacity reads, teardown) consistent if they opt in later.

## Risks / Trade-offs

- **[Legacy/null-owner rows]** — Records created before this change has an `owner_principal` to write have none. Treating a null owner as "owned by the legacy default principal" avoids breaking existing single-tenant deployments, but needs an explicit decision (see Open Questions) rather than an implicit default that surprises a later multi-tenant deployment.
- **[Static shared secrets don't scale to real rotation]** — Extending the existing model keeps the same secret-comparison mechanism (a static string compared with `secrets.compare_digest`), which is simple but has no rotation story of its own. Acceptable for the identity/ownership problem this change solves; a stronger mechanism can replace the comparison later without touching the `owner_principal` schema decision.
- **[Scope creep into every endpoint]** — The dev-branch candidate touched `get_status`, `get_result`, `begin_fulfillment`, and `begin_teardown` uniformly. This change deliberately ships the identity primitive and the check helper first, and lets each endpoint's own change (Section 8 for reads; a future change for `begin_fulfillment`/`begin_teardown` if needed) decide whether and how it adopts it.

## Open Questions

- How are per-storefront principal secrets provisioned and rotated operationally (Compose/Helm), and is a static shared secret per principal an acceptable long-term answer, or does this need real rotation support of its own (distinct from — and unrelated to — the VM-tenant-credential rotation question already resolved as out-of-band and out of scope elsewhere)?
- What is the accepted behavior for `SettlementRecord` rows that predate this change and have no `owner_principal`: implicitly owned by whichever principal represents the legacy shared key, or explicitly backfilled/migrated? This needs a decision before task 8.5's existence check can safely become a real ownership check.
- Where should the shared ownership-check helper live — `kit/fulfillment` (alongside the aggregate it checks) or the compute provisioning service's controller layer? `kit/fulfillment` has stayed domain/provider-neutral so far; "principal"/"storefront" is a business-relationship concept it hasn't previously encoded, so this may argue for keeping the check itself at the service layer even though the column lives on the kit-owned model.
- Does `pools-7-storefront-fulfillment-cutover` Section 8 stay unblocked (ship with the existence-only check, adopt real enforcement in a later pass) or should Section 8 implementation wait for this change to land first? Recorded here as a sequencing question for whoever plans Section 8 next, not resolved by this change.

## Permanent Documentation Promotion

Accepted multi-principal request-identity behavior belongs in `openspec/specs/physical-provisioning/spec.md` (and its `architecture.md` companion for rationale/trade-offs). The `owner_principal` column, its immutability, and the shared ownership-check contract belong in `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`. No `docs/development/ARCHITECTURE.md` change is anticipated unless the Open Questions above conclude the repository-wide auth vocabulary needs a new term.
