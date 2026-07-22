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

## Risks / Trade-offs

- **[Partial plan completion]** → Persist each obligation and expose aggregate plus per-obligation repair state.
- **[Rounding changes value]** → Define deterministic remainder allocation and conservation tests.
- **[Seller bond direction is mishandled]** → Test payer/claimant direction at carrier, materialization, claim, and reclaim layers.

## Migration Plan

Add per-obligation records alongside current single-obligation state, backfill existing agreements as one obligation, dual-read during compatibility, then remove first-obligation assumptions after parity. Rollback retains old single-obligation agreements and leaves new multi-obligation state readable/repairable.

## Permanent Documentation Promotion

Lifecycle and policy behavior belongs in `openspec/specs/settlement-servicing/spec.md`; rationale/limitations in `architecture.md`. Deferred heartbeat/oracle decisions are not promoted as current behavior.
