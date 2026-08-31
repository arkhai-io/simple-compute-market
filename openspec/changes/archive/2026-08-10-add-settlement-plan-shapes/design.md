## Context

Settlement plans carry N directional obligations and tests cover bond shape, while runtime materialization emits one buyer escrow and VM claim construction selects `obligations[0]`. Seller servicing persists condition/collection state; reclaim remains a buyer command. Heartbeats are stored but not used as claim evidence, and oracle operation is manual.

## Goals / Non-Goals

**Goals:** durable per-obligation lifecycle; both payer directions; interval escrow and seller bond policies; restart/idempotency evidence.

**Non-Goals:** heartbeat adjudication, automated oracle deployment, or fiat settlement.

## Decisions

- Assign stable obligation identity derived from plan/agreement and index/type; persist materialization, condition, collection, reclaim, attempt, and receipt state independently.
- Execute lifecycle through mechanism adapters with idempotency keys and resumable claims; one obligation failure does not erase completed sibling state.
- Generate interval escrows deterministically from accepted total/duration/schedule and seller-funded bonds from explicit penalty terms.
- Preserve buyer reclaim compatibility while moving authoritative reclaim scheduling/recording into servicing.
- Defer heartbeat gating until evidence freshness, neutral arbiter, disputed cases, and splitter/oracle contract are selected.

### Runtime inventory

- `core/src/market_core/schemas.py` already carries an ordered list of
  directional obligations; identity is not present in the wire carrier.
- `kit/alkahest/src/market_alkahest/plans.py` converts every Alkahest
  obligation, but its proposal materializer still documents the generated
  policy as single-obligation.
- VM and API-credit `claims_runtime.py` each select `plan.obligations[0]`
  when reconstructing a claim. Their submission path uses the escrow UID as
  both the mechanism reference and the claim id.
- `core_storefront.settlement_lifecycle` persists and services one submitted
  claimant-side record idempotently, but has no materialization/reclaim
  operations, no work lease or compare-and-swap transition, and no aggregate
  plan view.
- `SQLiteClient.settlement_claims` stores condition/collection retry state.
  Existing rows have no plan or obligation index and must remain readable.
- Buyer reclaim commands act directly on one run-log escrow UID. They do not
  enumerate a plan or persist an authoritative reclaim result.

### Identity, state, and compatibility

- Wire plans remain unchanged. The authoritative repository derives
  `obligation_ref` as lowercase SHA-256 over compact sorted JSON containing
  protocol tag `arkhai.settlement-obligation.v1`, the stable agreement
  reference, the zero-based obligation index, and the validated obligation
  dump. Reusing an agreement/index with different obligation bytes is a
  conflict.
- Every mechanism mutation uses
  `arkhai:settlement:<obligation_ref>:<operation>` as its stable idempotency
  key, where operation is `materialize`, `collect`, or `reclaim`. Condition
  checks are read-only attempts under the same obligation identity.
- One `settlement_obligations` row owns the immutable obligation snapshot and
  independent materialization, condition, collection, and reclaim states.
  External effects cross a compare-and-swap reservation
  (`pending|retry -> <operation>_in_progress`) before I/O. A persisted
  operation request hash, attempt count, uncertain-acknowledgement marker,
  mechanism reference, receipt, lease owner, and lease deadline make restart
  recovery explicit.
- Materialization is `pending|in_progress|materialized|manual_required`;
  condition is `pending|ready|failed|manual_required`; collection and reclaim
  are each `pending|in_progress|succeeded|manual_required`. Collection and
  reclaim success are mutually exclusive. A claimant services collection;
  the payer services reclaim, independent of list position.
- Aggregate status is derived, never separately authoritative:
  `complete` only when every obligation has one successful terminal effect,
  `manual_required` when any obligation requires repair, `partial` when some
  siblings are terminal and others are not, and `active` otherwise. Operator
  output always includes every obligation and its independent states.
- Legacy `settlement_claims` rows are imported as one obligation at index zero
  when no new row exists. The original claim row remains the compatibility
  projection during the cutover; reads prefer the new row and fall back to
  the legacy row. Conflicting immutable snapshots fail closed rather than
  choosing one. Buyer run-log reclaim remains a compatibility caller but
  records through the same authoritative operation before invoking the
  mechanism.

## Risks / Trade-offs

- **[Partial plan completion]** → Persist each obligation and expose aggregate plus per-obligation repair state.
- **[Rounding changes value]** → Define deterministic remainder allocation and conservation tests.
- **[Seller bond direction is mishandled]** → Test payer/claimant direction at carrier, materialization, claim, and reclaim layers.

## Migration Plan

Add per-obligation records alongside current single-obligation state, backfill existing agreements as one obligation, dual-read during compatibility, then remove first-obligation assumptions after parity. Rollback retains old single-obligation agreements and leaves new multi-obligation state readable/repairable.

## Permanent Documentation Promotion

Lifecycle and policy behavior belongs in `openspec/specs/settlement-servicing/spec.md`; rationale/limitations in `architecture.md`. Deferred heartbeat/oracle decisions are not promoted as current behavior.

Heartbeat-gated adjudication and automated oracle operation remain excluded.
The repository persists authenticated heartbeat evidence, but no current
policy treats cadence, missed heartbeats, or operator arbitration as an
automatic condition decision.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Stable per-obligation identity, operation journals, uncertain acknowledgement, and collect/reclaim exclusion | `openspec/specs/settlement-servicing/spec.md#durable-independent-obligation-lifecycle` |
| Separate lifecycle state and derived aggregate rationale | `openspec/specs/settlement-servicing/architecture.md#obligation-identity-and-competing-terminal-effects` |
| Deterministic interval conservation and seller-funded bond direction | `openspec/specs/settlement-servicing/spec.md#deterministic-interval-and-penalty-bond-policy` |
| Interval allocation and bond-as-obligation rationale | `openspec/specs/settlement-servicing/architecture.md#interval-and-bond-policy` |
| Heartbeat/oracle exclusions | `openspec/specs/settlement-servicing/architecture.md#current-limits` |
| Goal 4 prerequisite state and remaining kit extraction gap | `docs/development/ROADMAP.md#goal-4--make-a-domain-a-composition-of-kit` |
