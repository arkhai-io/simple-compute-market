# Design

## Context

Re-verified 2026-08-10 after `add-settlement-plan-shapes` landed:

| Concern | VM | API credits | Bare metal |
|---|---:|---:|---:|
| `settlement_jobs.py` | 392 lines | 290 lines | verified-only service, 203 lines |
| `claims_runtime.py` | 230 lines | 131 lines | none |
| `failure_policy.py` | 392 lines | 182 lines | none |

The landed `core_storefront.settlement_runtime.SettlementRuntime` already provides stable
obligation refs, deterministic operation refs, atomic work leases, uncertain
acknowledgements, payer/claimant authorization, collect/reclaim exclusion, and aggregate
status. It has no production composition. Production still runs `ClaimsEngine`, keyed by
`escrow_uid`; `SQLiteClient.upsert_claim` also projects that legacy record into the new
obligation table. The projection makes two state machines authoritative for one effect.

`kit-storefront-composition-seam` is not implemented in this checkout: its tasks are
unchecked, domain-local watchdog/Alkahest-service copies remain, and no kit storefront
runtime package exists. This change therefore defines the settlement-specific seam it
needs rather than waiting or adding a parallel temporary runtime.

## Goals / Non-Goals

**Goals:** one durable per-obligation lifecycle; kit-owned control flow; mechanism and
domain adapters injected from composition roots; VM/API-credit behavior preservation;
no fake bare-metal executor; a stable seam for `fiat.stripe.v1`.

**Non-Goals:** settlement wire changes, Alkahest economic changes, private fulfillment
payload generalization, physical provisioning extraction, or hosted fiat implementation.

## Decisions

### The landed obligation runtime is canonical

Move and complete the existing models/runtime; do not wrap the legacy claims engine as a
second API. `obligation_ref` derives from agreement identity, obligation index, and the
immutable obligation snapshot. Every materialize/status/check/collect/reclaim attempt uses
its deterministic operation identity and the same operation journal.

The clean cutover removes `ClaimRecord`, `ClaimsEngine`, `settlement_claims` runtime
writes, escrow-UID claim identity, minimal-obligation fallback, and legacy dual-write
projection. A migration may read old claims once, but no production code may continue to
write both models.

### Package boundary

Create foundation kit `kit/settlement-runtime`, distribution
`arkhai-kit-settlement-runtime`, import `market_settlement_runtime`. It is stdlib/Pydantic
plus core carrier types only. It never imports a domain, deployed service, storefront
SQLite client, Alkahest, Stripe, capacity authority, credentials, or HTTP configuration.

Modules:

- `models`: obligation/operation records, canonical hashes/refs, aggregate status;
- `ports`: store and `ConditionalEscrowClient` protocols;
- `runtime`: register/adopt/materialize/status/check/collect/reclaim transitions;
- `jobs`: accepted-thread guards, exact obligation adoption, idempotent start, opaque
  domain fulfillment dispatch, fulfillment binding, and servicing wake-up;
- `servicing`: durable worker that binds immutable fulfillment, checks, backs off,
  collects, and emits manual/terminal outcomes;
- `policy`: ordered failure-action dispatch over injected handlers;
- `composition`: immutable dependency bundle used by role composition roots.

`core_storefront.SQLiteClient` remains the storefront repository adapter and migrations
remain at the owning database composition root. Role packages may depend downward on the
kit; the kit never imports the role package.

### Conditional-escrow port prepares the second mechanism

The port exposes `materialize`, `get_status`, `check`, `collect`, and `reclaim_expired`.
Results normalize only opaque mechanism refs, lifecycle state, optional buyer action,
condition anchor, receipt, and retry/manual classification. Domain fulfillment data and
provider secrets never enter this port.

An adoption transition records a pre-materialized escrow verified through the existing
seller route without calling materialize again. This is required to preserve the current
Alkahest buyer-funded flow while making the stable obligation record authoritative.

### Servicing is one worker over persisted obligation refs

The worker claims due operations through the SQLite adapter, reloads the exact accepted
obligation, and uses the bound immutable fulfillment ref for all checks/collections. It
never re-materializes a proposal to guess an obligation and never substitutes
`escrow_uid` for `obligation_ref`. Pending remains retryable; malformed/terminal remains
manual or failed; uncertain effects retain the same operation ref.

VM's claim-abandonment lease truncation is an injected terminal action. API credits has
no equivalent because quota was sold rather than leased.

### Settlement jobs retain domain preparation, not lifecycle authority

VM and API credits share accepted-thread guards, fail-closed verification, idempotent
start, status persistence, task retention, and servicing intake. Their domain composition
supplies:

- VM duration/start/resource/SSH preparation, site selection, provisioning, lease
  registration, and private VM result projection;
- API-credit persisted quantity/key policy, issuance, inline post-issuance rollback, and
  private credential projection.

The shared runtime records stable plan/obligation identity before fulfillment and binds
the fulfillment ref exactly once afterward. Existing HTTP response shapes remain domain
status projectors rather than generic runtime models.

### Failure policy is dispatch; effects stay domain-owned

The kit preserves configured action order, blank-value normalization, per-action failure
isolation, and result reporting. Composition roots register handlers. VM supplies capacity
release/reopen, event, webhook, optional on-chain refund, and lease truncation. API credits
supplies quota release/reopen, event, and webhook; issuance rollback remains inline at the
issuance boundary. Money movement is never a built-in generic action.

### Bare metal remains honestly verification-only

Bare metal declares settlement but no fulfillment capability, returns
`fulfillment_available=false`, and has no immutable access-grant reference. It continues
to verify and persist its primary escrow through the shared carrier/verification seam,
but is not scheduled for check/collect and receives no no-op executor. Composing full
servicing requires a later real access authority and fulfillment capability.

## Drift decisions

| Existing divergence | Decision |
|---|---|
| VM duration/resource/SSH vs credit quantity/key preparation | Domain-injected preflight; no generic interpretation. |
| VM warns on proposal/request chain divergence; credits is silent | Preserve each status/log projector; persisted proposal chain remains authoritative after verification. |
| VM pre-provision compensation vs credit pre-issuance and inline post-issuance rollback | Preserve at each domain's real side-effect boundary. |
| VM optional refund; credits no refund action | Domain action registry; no generic refund. |
| VM abandonment truncates a lease; credits does nothing | Inject VM terminal action only. |
| Legacy out-of-range match builds a minimal claim | Reject/manual rather than attach evidence to the wrong obligation. |
| Bare metal idempotently verifies but cannot fulfill | Preserve verified-only state; never synthesize collection readiness. |

## Migration Plan

1. Build the kit from the landed obligation runtime and port its unit tests.
2. Extend the storefront SQLite adapter/worker migration. Validate all legacy rows before
   the transaction; conflicting immutable snapshots roll back the whole migration.
3. Implement the Alkahest adapter and adoption path.
4. Compose VM/API-credit jobs, recovery, servicing, and failure actions; remove legacy
   claim engine and local policy/orchestration copies.
5. Keep bare-metal verified-only behavior explicit and covered.
6. Update packages/locks/images, permanent documentation, and archive after strict
   validation.

Rollback before migration is a code revert. After migration, rollback may read the
preserved escrow/obligation rows but must not re-enable dual writers; restoring the legacy
claim writer requires a separately tested reverse migration.

## Risks / Trade-offs

- **[A third lifecycle survives behind compatibility aliases]** → Clean cutover; no
  `ClaimsEngine`, claim projection, or domain-local orchestration aliases remain.
- **[An uncertain financial call is replayed with a new key]** → Stable operation ref is
  stored before I/O and reused until authoritative reconciliation.
- **[Recovery guesses the first obligation]** → Persist exact verified index/ref before
  fulfillment; invalid or missing identity is manual-required.
- **[Private delivery data leaks into generic status]** → Domain projectors own VM/credit
  response payloads; generic receipts are public-safe and opaque.
- **[Bare metal appears supported by a no-op]** → Full worker composition is conditional
  on a real fulfillment capability and immutable fulfillment ref.
- **[Packaging creates an upward dependency]** → Import-boundary tests reject kit imports
  from core role packages, domains, or deployed services.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned single obligation lifecycle and dependency direction | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| Stable identity, worker, conditional-escrow port, migration, and bare-metal boundary | `openspec/specs/settlement-servicing/spec.md`; `architecture.md` |
| Drift choices and temporary migration mechanics | This change's `design.md` |
| Current implementation/gap mapping | `docs/development/ROADMAP.md` |

## Validation record

- Runtime kit: 16 unit tests passed on Python 3.10; mypy and Ruff passed.
- Alkahest: 164 unit tests passed; the conditional-escrow adapter and codec registry are
  covered without changing the existing on-chain route.
- Core: 192 package tests passed and both core typing targets passed.
- VM: 826 unit tests and 152 integration tests passed.
- API credits: 53 storefront tests passed; the full domain suite also passed before the
  final focused rerun.
- Bare metal: 60 domain and 47 storefront tests passed.
- Packaging: the complete distribution build, scoped review wheelhouse, distribution
  manifest tests, and portable-lock scan passed.
- `make check-comment-hygiene` and strict validation of this change passed.
- Repository-wide strict validation still reports six unrelated pre-existing active-change
  failures: `add-buyer-vm-connectivity-terms`, `fix-vm-fulfillment-capacity-boundary`,
  `negotiation-driven-capacity-resize`, `pool-declared-offering-modes`,
  `refactor-e2e-fulfillment-lifecycle`, and `structured-capacity-requirements`.
- The on-chain codec E2E suite was invoked but could not connect to its required Anvil
  service; all 12 cases stopped at `w3.is_connected()` before exercising code.
