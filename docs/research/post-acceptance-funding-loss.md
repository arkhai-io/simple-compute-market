# Post-acceptance funding loss as a consumer sees it

Facts-only inventory, dated 2026-09-01. No decision is taken here.

## Scope and sources

Two repositories.

- This one, at worktree commit `a1c46d20` (branch `record-protected-card-matrix`). Cited by
  repository-relative path.
- `arkhai-io/stripe-settlement-service`, the hosted settlement authority, read-only at
  `~/dev/arkhai/hosted-settlement-service`, `main` at `fecab4b`. Cited with a `authority:` prefix.
- The pinned released client, `arkhai_hosted_settlement_client` 0.4.2, read from the uv wheel cache
  at `/Users/mlegls/.cache/uv/archive-v0/OiSUPVi9cbTwUqr2/hosted_settlement_client/`. Its `models.py`
  is byte-identical in role to `authority:client/src/hosted_settlement_client/models.py`; both are
  cited as `client:models.py`. The released OpenAPI is
  `authority:.dist/openapi-v0.4.2.json`.

Where `openspec/specs` and the implementation disagree, both are recorded. This repository holds the
implementation authoritative; nothing here resolves a disagreement.

## 1. Reachable but unrepresented

These are the states a consumer cannot learn about through any permitted channel. They are listed
first because they are what the inventory is for.

### 1.1 A card dispute produces no incident anyone outside the operator can read

`FundingIncidentKind` declares `card_dispute`, `transfer_reversal`, and `refund`
(`client:models.py:251-253`), and the released OpenAPI publishes all three in its enum. No code path
writes any of them. `_funding_incident` has exactly three call sites
(`authority:service/src/hosted_settlement_service/authority.py:3461`, `:3491`, `:3516`), and the
kinds they emit are `attribution_underpaid`, `ach_return`, `post_collection_loss`,
`attribution_unmatched`, `attribution_overpaid`, and `attribution_ambiguous`. A grep for
`CARD_DISPUTE` across `authority:service/src` returns nothing; the only occurrence in the repository
is the enum declaration itself.

The events that would justify them — `charge.dispute.created`, `transfer.reversed`, `charge.failed` —
are handled by `_record_terminal_loss`
(`authority:service/src/hosted_settlement_service/recovery.py:562`), which writes to a different
table, `operator_incidents` (`authority:service/src/hosted_settlement_service/database.py:212`), and
touches neither `funding_incidents` nor `funding_records` nor `escrows`.

`EscrowResult.incident` reads only `funding_incidents`
(`authority:service/src/hosted_settlement_service/authority.py:3585`). So a card dispute after
collection is visible on `/api/v1/operator/incidents` and nowhere else. The payer, the seller, and
the storefront all see an unchanged `EscrowResult`.

This contradicts a standing obligation in the authority's own spec,
`authority:openspec/specs/operator-recovery/spec.md:36`, which requires the authority to classify
"card disputes; transfer reversals; refunds; and other verified post-collection losses with bounded
provider-neutral incident kinds".

### 1.2 Every loss outcome reaches the buyer CLI as one constant string

`core/buyer/src/core_buyer/hosted_settlement.py:304` computes
`succeeded = final.get("status") in {"ready", "collected"}`, and `:322` sets
`reason=None if succeeded else "hosted_settlement_not_completed"`. That constant appears exactly once
in the repository and has no other value.

So `manual_required`, `failed`, `expired`, and `reclaimed` all become `BuyResult(status="failed",
reason="hosted_settlement_not_completed")`. The `funding_reason` the storefront supplied in the same
HTTP body is read by nothing on this path. The run-log events the buyer emits —
`settlement_started` (`:263`) and `hosted_settlement_poll` (`:280`) — carry `status`, `action_kind`,
and `action_expires_at_unix`, and no reason field at all.

A disputed card, a returned bank transfer, a refused authorization that will not converge, and an
expired funding window are therefore indistinguishable to a buyer running the CLI, even though the
distinguishing reason was on the wire.

**No redaction rule requires this.** `openspec/specs/buyer-orchestration/spec.md:56` and `:180` both
name "public status/reason/deadline" as permitted run-log content. `funding_reason` and
`funding_deadline_unix` are allowed and simply not wired. The CLI is narrower than the spec, not
compelled by it.

### 1.3 A pre-collection return emits no incident and carries only `operator_review`

`authority:.../authority.py:3502-3504`: when `funding_state` becomes `returned` and
`financial_state` is not `collected`, `reclaimed`, or `expired`, the authority sets
`financial_state = "operator_review"` and emits no `funding_incidents` row. The consumer sees
`financial_state: operator_review` with `incident` absent. The marketplace maps that to
`manual_required` (`kit/hosted-settlement/src/market_hosted_settlement/adapter.py:766-769`).

`funding_reason` on that path comes from `_normalized_funding_reason`
(`authority:service/src/hosted_settlement_service/providers.py:1468`) as `funding_returned`, so the
reason survives; the structured evidence does not.

### 1.4 No projection states whether delivery survived the loss

There is no `fulfillment_blocked`, `delivery_revoked`, or equivalent field in any storefront
projection. `hosted_settlement_projection`
(`domains/vms/storefront/src/market_storefront/settlement_composition.py:1242-1253`) returns
`fulfillment_ref`, which stays non-null whether the VM is running or its lease was truncated seconds
earlier. A buyer polling after a dispute reads `status: "manual_required"` and cannot tell whether
the machine still exists.

The two protected end-to-end lanes that would assert this are withheld in code:
`e2e-tests/src/hosted_real_stripe/driver.py:494` defines
`_UNPROJECTED_LOSS_SCENARIOS = frozenset({"ach_return", "post_collection_loss"})`, and `:511-515`
raises `LaneExcluded("loss_projection_unimplemented", "no storefront projection reports an
authoritative funding loss")`. The assertions those lanes want — `fulfillment_blocked` and
`operator_incident_observed` — are at `driver.py:1132-1148`, and no storefront produces either.
Neither lane has ever run in any mode.

### 1.5 The bare-metal post-collection loss ends as a swallowed log line

`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:463-471` calls `cleanup`
for every terminal state other than `collected`.
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/hosted_lifecycle.py:349-374` raises
`BareMetalHostedLifecycleError` when `financial_state` is `collected` or `collection_unknown`
("collection cannot be excluded; physical cleanup is frozen") and again when
`portable_evidence_ref` is set ("successful lease-ready evidence excludes financial reclaim").
`kit/settlement-runtime/src/market_settlement_runtime/servicing.py:318-334` catches every terminal
callback exception into `logger.exception`. The result is no lifecycle advance, no teardown, no
projection change, and no signal to any consumer.

`reconcile_terminal` (`hosted_lifecycle.py:393` onward), which handles `collected`,
`collection_unknown`, and `manual_required` correctly, is called only from
`domains/bare_metal/storefront/tests/test_hosted_lifecycle.py:302`, `:328`, `:352`. Nothing in
`src/` calls it.

The same swallow covers a pre-collection return arriving after evidence is published, which
contradicts `openspec/specs/settlement-servicing/spec.md:41`'s requirement to "order domain-owned VM
teardown and capacity cleanup to convergence".

### 1.6 A dispute never takes the journaled cleanup path

`kit/settlement-runtime/src/market_settlement_runtime/servicing.py:132-138` gates `_cleanup` on
`mechanism_status == "failed"`. Any loss carrying an escalating incident maps to `manual_required`
instead (`adapter.py:719-734` with `:766-769`), so `reserve_cleanup`, `complete_cleanup`, and the
`settlement_cleanup_complete` event (`servicing.py:265-268`) never fire for a dispute. The VM lease
is still truncated, but through `on_terminal`
(`domains/vms/storefront/src/market_storefront/settlement_composition.py:1367-1379`), which is not
journaled as a cleanup operation. The durable journal holds no record that a dispute caused a
teardown.

### 1.7 The operator aggregate and the buyer projection can disagree

`aggregate_settlement_status`
(`kit/settlement-runtime/src/market_settlement_runtime/models.py:216-238`) reads only
`materialization_state`, `condition_state`, `collection_state`, and `reclaim_state`. It does not read
`mechanism_status`. A post-collection loss sets `mechanism_status` to `manual_required` while
`collection_state` stays `succeeded`, so the operator-facing aggregate reports `complete` for a plan
whose buyer-facing obligation reports `manual_required`.

`openspec/specs/settlement-servicing/spec.md:168-175`, Requirement "Aggregate and per-obligation
status", requires the aggregate to be `manual_required` "when any obligation needs repair".

### 1.8 `ReversalKind` and `ReversalState` have no outward field at all

Both are defined (`client:models.py:224`, `:230`) and constrained in the authority database
(`authority:.../database.py:812`, `:816`). No response model carries either, and neither appears in
`components.schemas` of `authority:.dist/openapi-v0.4.2.json`. A payer who reclaims a bank transfer
receives `OperationReceipt{financial_state: "reclaiming"}` and cannot distinguish
`reversal.state = pending` — the normal path, Stripe accepted and is waiting on the payer's return
bank details — from `reversal.state = ambiguous`, which is parked with no retry scheduled
(`authority:.../authority.py:4790`).

### 1.9 A `charge.failed` webhook can never be confirmed

`charge.failed` is in `LOSS_EVENTS` (`authority:.../recovery.py:41`) and requires corroboration from
`list_terminal_losses` (`authority:.../recovery.py:474-483`). `StripeFinancialProvider.list_terminal_losses`
(`authority:.../providers.py:1177`) only ever emits `charge.dispute.created` and `transfer.reversed`.
A `charge.failed` webhook therefore always raises "terminal loss is not yet authoritative" and is
rescheduled retryable indefinitely (`authority:.../recovery.py:500-511`).

### 1.10 Only one incident is ever projected, and only on one route

`authority:.../authority.py:3585-3592` selects the latest `open` incident with `LIMIT 1`. An escrow
carrying both an `attribution_underpaid` and a later `post_collection_loss` shows one of them; a
resolved incident disappears from public view. `_escrow_result` is called at
`authority:.../authority.py:2628` (materialize), `:3594` (legacy-profile status), and `:3623`
(normalized status), and only the last passes `incident=`. `POST /api/v1/escrows` and every
legacy-profile status response structurally cannot carry an incident.

### 1.11 An unknown authority state makes the marketplace poll forever instead of escalating

The released client rejects a response it cannot parse with `code="invalid_response"`,
`retryable=False` (`client:client.py:201-203`). `_UNCERTAIN_RESPONSE_CODES`
(`kit/hosted-settlement/src/market_hosted_settlement/adapter.py:73-81`) includes `invalid_response`,
so `_released_call` (`adapter.py:112-125`) raises `HostedSettlementTemporaryError` rather than
`SettlementManualRequired`. The runtime then takes `_finish_retry`
(`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:844-860`) into `pending` with
capped backoff to 1800 seconds (`servicing.py:289-296`).

So an authority release that adds a `FinancialState` or `NormalizedFundingState` value the pinned
client does not know makes every obligation on that path poll indefinitely instead of parking for a
human. `_condition_decision` (`adapter.py:694-703`) has the mirror-image problem: its catch-all
swallows any future `ConditionState` into `manual_required` without naming it.

### 1.12 A resolved incident parks the obligation as hard as an open one

`FundingIncidentProjection.state` is `open | resolved` (`client:models.py:729`).
`_escalating_incident` (`adapter.py:719-734`) reads only `kind`. Nothing anywhere reads `state`. An
incident the operator has resolved through
`POST /api/v1/operator/incidents/{ref}/resolve` continues to park the obligation as
`manual_required`, and there is no marketplace path out. `incident_ref` and `evidence_digest` are
persisted and never branched on.

### 1.13 `succeeded_unavailable` is indistinguishable from `reserved`

Four of the eleven `NormalizedFundingState` values have no branch in `_escrow_status`: `reserved`,
`initiating`, `awaiting_external`, `succeeded_unavailable`. All fall through to `pending`, or to
`requires_action` if an `action` happens to be non-null. The material one is
`succeeded_unavailable` — funds captured but not yet available — which reads identically to
`reserved`, where nothing has been captured.

Five of the nine `FinancialState` values likewise have no branch: `creating`, `awaiting_payment`,
`funded`, `collecting`, `reclaiming`. `funded` in particular never produces `ready`; readiness is
decided purely from `funding_state` (`adapter.py:790-799`). An escrow mid-collection with
`funding_state == available` still projects `ready`.

`EscrowResult.condition_state` has zero branches. It is written into the receipt (`adapter.py:828`)
and mechanism state (`adapter.py:879`) and read by nothing. Only the separate
`EvaluationResult.condition_state` returned by `check()` is mapped.

### 1.14 A funding loss is recorded as a condition failure

The status branch of the obligation UPDATE carries
`condition_state=CASE WHEN ?='failed' THEN 'failed' ELSE condition_state END`
(`kit/settlement-runtime/src/market_settlement_runtime/sqlite_repository.py:1313-1314`), and the
bound parameter is `mechanism_status` (`:1327-1329`). A pure funding loss is
therefore stored as a condition failure. It happens to produce the same public status
(`settlement_composition.py:1194`), so it is invisible to callers, but the durable record is wrong.

### 1.15 A condition check erases the authority snapshot the status projection depends on

`adapter.check` returns `mechanism_state={"condition_state": ...}` only (`adapter.py:460`), and the
check branch writes `mechanism_state=COALESCE(?, mechanism_state)`
(`sqlite_repository.py:1351-1364`), which replaces the whole column rather than merging into it. Only
`manual_reason` survives (`runtime.py:751-780`). After any condition check, the next `_escrow_status`
call sees `previous_financial = None` and `previous_funding = None`, losing both the sticky-`ready`
memory (`adapter.py:796-800`) and the previously-collected memory (`adapter.py:773-774`).

In the normal servicing order — `status`, then `check`, then `collect`
(`servicing.py:298-306`) — `collect`'s write restores the collected memory (`adapter.py:488-491`),
so the post-collection path is not broken. The sticky-`ready` window is genuinely lossy. This is the
same class of defect as the archived change `2026-08-21-keep-a-parked-reason`, which fixed the
parked reason being deleted by the same whole-state overwrite.

### 1.16 A buyer that has stopped polling never learns of a post-collection loss

`core/buyer/src/core_buyer/hosted_settlement.py:27-36` defines the stable set the wait loop stops on:
`ready`, `collected`, `reclaimed`, `expired`, `failed`, `manual_required`. `ready` is in it. A
purchase that funds and fulfils returns from `wait` at `ready` and stops. A later flip to
`manual_required` is reachable only if something polls again, and nothing in the buyer's normal path
does.

## 2. Post-acceptance states in the authority

### 2.1 `FinancialState`

`client:models.py:168-177`, nine values:

`creating`, `awaiting_payment`, `funded`, `collecting`, `collected`, `expired`, `reclaiming`,
`reclaimed`, `operator_review`.

Persisted as free text in `escrows.financial_state` with no CHECK constraint
(`authority:.../database.py:115`), unlike the funding tables.

### 2.2 `NormalizedFundingState`

`client:models.py:210-221`, eleven values:

`reserved`, `initiating`, `awaiting_external`, `action_required`, `succeeded_unavailable`,
`available`, `returned`, `failed`, `expired`, `ambiguous`, `transferred`.

Enforced by CHECK on `funding_records.state` (`authority:.../database.py:669`).

### 2.3 `ConditionState`

`client:models.py:273-277`, four values: `pending`, `satisfied`, `invalid`, `manual_required`.

### 2.4 `FundingIncidentKind`

`client:models.py:245-254`, nine values:

`attribution_unmatched`, `attribution_underpaid`, `attribution_overpaid`, `attribution_ambiguous`,
`ach_return`, `card_dispute`, `transfer_reversal`, `refund`, `post_collection_loss`.

Six are emitted; `card_dispute`, `transfer_reversal`, and `refund` are not (see 1.1). Incident
`timing` is a separate closed set `pre_collection | post_collection`
(`authority:.../database.py:852`); incident `state` is `open | resolved`
(`authority:.../database.py:857`).

### 2.5 `ReversalKind`, `ReversalState`

`client:models.py:224-227` — `cancel`, `return`, `refund`.
`client:models.py:230-235` — `reserved`, `pending`, `succeeded`, `failed`, `ambiguous`.

Internal only; see 1.8.

### 2.6 `funding_reason` is an open string, not an enum

`EscrowResult.funding_reason` is validated only as at most 64 characters matching
`_SAFE_REASON = re.compile(r"^[a-z0-9_.-]+$")` (`client:models.py:25`, validator at `:754-759`).
There is no closed set anywhere in the contract.

Values actually produced by `_resolve_funding_gate` (`authority:.../authority.py:5622`):
`funding_deadline_expired` (`:5635`), `bank_transfer_unmatched` (`:5642`),
`bank_transfer_underpaid` (`:5650`), `bank_transfer_overpaid` (`:5656`),
`ach_availability_pending` (`:5675`), `funding_amount_mismatch` (`:5684`). Otherwise the provider's
own code passes through.

Values from `_normalized_funding_reason` (`authority:.../providers.py:1468`): `funding_returned`,
`payer_action_required`, `payer_confirmation_required`, `funding_method_unavailable`,
`funding_processing`, `funding_cancelled`, or `None`.

Written directly to `funding_records.reason_code`: `funding_rejected`
(`authority:.../authority.py:2496`), `reversal_rejected` (`authority:.../authority.py:4716`),
`legacy_card_recovery` (`authority:.../database.py:700`).

The marketplace adds its own values into the same field: `authority_refused_{status_code}` or
`authority_refused` (`kit/hosted-settlement/.../adapter.py:140-143`), and
`authority_incident_{kind}` or `authority_operator_review`
(`kit/hosted-settlement/.../adapter.py:853-865`). A consumer reading `funding_reason` is therefore
reading a union of provider-derived, authority-derived, and marketplace-derived strings with no
shared registry.

### 2.7 Terminality in the authority

`_monotonic_funding_state` (`authority:.../authority.py:6392-6420`) is the only transition table.

- `returned` is unconditionally absorbing and wins from any state including `transferred`
  (`:6395-6396`). `transferred → returned` is the post-acceptance funding-loss path.
- `expired` observed alongside `available` becomes `ambiguous` (`:6397-6398`).
- `transferred`, `returned`, `expired` are sticky except for the `returned` override (`:6399-6404`).
- `available` is sticky except against `ambiguous` and `returned` (`:6405-6410`).
- Ranks (`:6411-6420`): `reserved` 0, `initiating` 1, `awaiting_external` / `action_required` /
  `failed` 2, `succeeded_unavailable` 3, `available` 4, `ambiguous` 5. **`failed` is rank 2 and is
  not terminal** — a later observation can climb out of it.

So exactly one funding state is unconditionally terminal: `returned`.

On the financial side, `collected` is written once (`authority:.../authority.py:4188`) and `status()`
refuses to overwrite it (`:3563`), but `_operator_review` (`:6077`) issues an unguarded
`UPDATE escrows SET financial_state = 'operator_review'`, so `collected → operator_review` is
reachable. `operator_review` is not terminal either: the reclaim guard is
`financial_state NOT IN ('collecting','collected','reclaimed')` (`:4616`), so
`operator_review → reclaiming → reclaimed` is reachable. `_TERMINAL_REVERSAL_STATES` is
`{succeeded, failed}` (`authority:.../authority.py:110`).

## 3. `EscrowResult` and its fields

`client:models.py:740-759`. Full field list:

`protocol` (literal `arkhai.hosted-settlement.v2`), `escrow_ref`, `financial_state`,
`condition_state`, `funding_profile`, `funding_state`, `funding_reason`, `funding_deadline_unix`,
`action`, `condition_anchor`, `incident`, `expiration_unix`.

`funding_profile` is `card.v1 | us_bank_transfer.v1 | us_ach_debit.v1` (`client:models.py:180-183`),
plus an undeclared internal fifth value `legacy_card.recovery.v1` inserted by migration
(`authority:.../database.py:695`) and mapped back to `card.v1` on projection
(`authority:.../authority.py:6314`).

`incident` is `FundingIncidentProjection` (`client:models.py:726-737`): `incident_ref`, `kind`,
`state` (`open | resolved`), `evidence_digest` (a `sha256:` hex digest). No provider identifier, no
message, no amount. The `timing` and `required_action` columns the authority stores are not in the
projection.

`action` is `BuyerAction`, a subclass of `PayerAction` adding nothing (`client:models.py:722-723`).
`PayerAction` (`client:models.py:556-570`) is `kind` (`setup | payment | confirmation |
bank_instructions`, `client:models.py:238-242`), `operation_ref`, `expires_at_unix`, and exactly one
of `url: HttpUrl` or `bank_instructions: BankTransferInstructions`. The model validator enforces the
exclusivity. **`action` carries the raw URL.**

All authority routes use `response_model_exclude_none=True`, so `None` fields are omitted from the
wire rather than sent as null.

`OperationReceipt` (`client:models.py:772-777`) carries only `escrow_ref`, `operation_ref`,
`financial_state`, `receipt`. No funding state, no reason, no incident.

## 4. Buyer-role versus operator surfaces in the authority

`FastAPI(title="Arkhai Hosted Settlement", version="0.4.2")` at
`authority:service/src/hosted_settlement_service/api.py:151`. All routes are declared on `app`; there
is no `APIRouter`.

Two disjoint auth regimes, split in the middleware at `authority:.../api.py:163`.

- `/api/v1/operator/*` skips signature verification entirely and requires only the shared-secret
  header `X-Arkhai-Admin-Key` (`_require_admin`, `authority:.../api.py:961`).
- Everything else requires a signed request whose `X-Arkhai-Role` header is one of
  `account_owner`, `payer`, `resolver`, `seller`, `storefront` (`authority:.../api.py:197-205`) plus
  a replay reservation (`:873`).

Signed surface, with caller and response:

| Route | Caller | Response |
| --- | --- | --- |
| `POST /api/v1/escrows` | storefront only (`authority:.../authority.py:2219`) | `EscrowResult`, never with `incident` |
| `GET /api/v1/escrows/{ref}` | storefront, payer, or seller matching the escrow's own principal (`_require_escrow_actor`, `authority:.../authority.py:6037`) | `EscrowResult`, the only route carrying `incident` |
| `POST /api/v1/escrows/{ref}/check` | same three (`:3630`) | `EvaluationResult` |
| `POST /api/v1/escrows/{ref}/collect` | seller or storefront; seller must equal claimant (`:3798`, `:3805`) | `OperationReceipt` |
| `POST /api/v1/escrows/{ref}/reclaim` | payer or storefront (`:4247`) | `OperationReceipt` |
| `POST /api/v1/escrows/{ref}/confirmations` | payer only (`:3726`) | `EvaluationResult` |
| `POST /api/v1/funding/authorizations` | payer only, must own the profile (`:1000`) | `FundingAuthorizationResult` |
| `POST /api/v1/funding/confirmations` | payer only (`:1175`) | `FundingActionResult` |
| `/api/v1/payers/**` | payer only | payer/setup/instrument models |
| `/api/v1/accounts/{ref}/readiness`, `/links`, `/owner/*` | seller or account owner (`:6021`) | `AccountReadiness`, `AccountLinkResult` |

`action` is suppressed unless the caller's role is `payer` or `storefront`. A seller never sees it
(`authority:.../authority.py:3597`, `:3626`, `:6298`).

Operator-only surface, all admin-key, all untyped:

| Route | Response |
| --- | --- |
| `GET /api/v1/operator/incidents` | untyped `list[dict]` (`authority:.../api.py:680`) |
| `GET /api/v1/operator/incidents/{ref}` | untyped `dict`; context whitelisted to `account_ref`, `evaluation_ref`, `event_type`, `operation_ref` (`authority:.../recovery.py:775-781`) |
| `GET /api/v1/operator/payers/{ref}` | untyped `dict` (`authority:.../recovery.py:790`) |
| `GET /api/v1/operator/funding/{ref}` | untyped `dict`, returns all incidents with `timing` and `required_action` (`authority:.../recovery.py:823-838`) |
| `POST /api/v1/operator/reconcile` | `dict[str, int]` |
| `POST /api/v1/operator/incidents/{ref}/resolve` | `{"incident_ref", "state"}` |

Operator resolution codes are closed at exactly two: `acknowledged_platform_loss`,
`configuration_corrected` (`authority:.../recovery.py:886`).

`operator_incidents.error_class` and `error_code` are free text
(`authority:.../database.py:212`). Emitted classes: `provider_mismatch`, `configuration`,
`condition_authority`, `condition_authorization`, `authorization`, `provider_refund`,
`platform_loss`. This vocabulary has no public projection of any kind.

## 5. What the marketplace projects

### 5.1 The shared adapter's lifecycle set

`kit/settlement-runtime/src/market_settlement_runtime/models.py:27-36` defines `EscrowStatus`:
`requires_action`, `pending`, `ready`, `collected`, `reclaimed`, `expired`, `failed`,
`manual_required`.

Per-effect states in the same file: `MaterializationState` (`pending`, `in_progress`,
`materialized`, `manual_required`, `:18`); `ConditionState` (`pending`, `ready`, `failed`,
`manual_required`, `:21`); `TerminalEffectState`, used for both `collection_state` and
`reclaim_state` (`pending`, `in_progress`, `succeeded`, `manual_required`, `:22`) — note it has no
`failed` value; `OperationState` (`:17`); `OperationKind` (`materialize`, `status`, `fulfill`,
`cleanup`, `check`, `collect`, `reclaim`, `:15`). Plan aggregate is `active | partial | complete |
manual_required` (`:212`).

### 5.2 The mapping from authority to marketplace

`_escrow_status` (`kit/hosted-settlement/src/market_hosted_settlement/adapter.py:737-805`) is the
single decision point, in order:

1. `post_collection_risk` (`:749-765`): previous `financial_state` was `collected` and now the
   authority reports `operator_review`, or an escalating incident, or `funding_state` in
   `{returned, failed, ambiguous}` → `manual_required`.
2. `financial_state == operator_review` or an escalating incident → `manual_required` (`:766-769`).
3. `funding_state == ambiguous` → `manual_required` (`:770-771`).
4. previous `financial_state` was `collected` → `collected` (`:772-773`).
5. `funding_state` in `{returned, failed}` → `failed` (`:774-778`).
6. `funding_state == expired` or `financial_state == expired` → `expired` (`:779-783`).
7. previous `financial_state` was `reclaimed` → `reclaimed` (`:784-785`).
8. `financial_state == collected` → `collected`; `== reclaimed` → `reclaimed` (`:786-789`).
9. `funding_state` in `{available, transferred}`, or previously so → `ready` (`:790-799`).
10. an `action` is present, or `funding_state == action_required` → `requires_action` (`:800-804`).
11. otherwise `pending`.

Two consequences worth naming. **`returned` and `failed` collapse to the same word, `failed`** — a
returned bank transfer and a card the provider refused are the same string to every consumer. And
**a returned funding carrying an incident never reaches step 5**, because step 2 diverts it to
`manual_required`; only an incident-free return reads as `failed`.

`_escalating_incident` (`adapter.py:719-734`) treats every incident kind as an escalation except
`attribution_underpaid`. Its docstring records why: that one "is raised on the first retrieval of
every push transfer, before any money can have landed", "never clears itself", and reading it as an
escalation "parks every bank-transfer deal permanently, including the ones the authority went on to
call funded". No spec states this carve-out.

`_materialization_status` (`adapter.py:706-716`) narrows the same computation to
`requires_action | pending | ready | manual_required`.

`hosted_projected_reason` (`adapter.py:146-165`) resolves the one reason a consumer reads:
`receipt.funding_reason`, then `mechanism_state.funding_reason`, then `mechanism_state.manual_reason`
(`MANUAL_REASON_KEY`, defined at
`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:26`), then `None`. Its docstring
states it lives in the kit "so a storefront cannot project a status without the reason behind it by
forgetting to."

`_parked_reason` (`adapter.py:838-865`) supplies `authority_incident_{kind}` or
`authority_operator_review` when the obligation is parked and the authority supplied no
`funding_reason`. Because a real dispute does supply one, the incident kind normally does not surface
through this path.

### 5.3 The three storefront projections are not one surface

`openspec/specs/settlement-servicing/spec.md:261-264` says all three domains carry the same reason
"in the same field, because the projection is built from one shared surface". That is true of
`hosted_projected_reason`. It is not true of the status, which exists in three separate
implementations.

- VM: `hosted_public_status`
  (`domains/vms/storefront/src/market_storefront/settlement_composition.py:1181-1198`).
- API credits: a byte-equivalent second copy
  (`domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py:574-594`).
- Bare metal: a third, different implementation
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/hosted_lifecycle.py:927-941`),
  keyed on its own `recovery_state` and `financial_state` rather than on the runtime record.

VM and API credits both yield `reclaimed | manual_required | collected | failed | ready | funded`
falling through to `mechanism_status or "pending"`. Both check `manual_required` **before**
`collected`, so a post-collection loss flips the buyer-visible status from `collected` to
`manual_required`. `funded` is a projection-only value with no counterpart in `EscrowStatus`; it
means ready but not yet fulfilled. `fulfilling`, which
`openspec/specs/storefront-publication/spec.md:326` names as a lifecycle reservation, appears in no
projection.

Bare metal exposes strictly more than the other two. Its projection
(`hosted_lifecycle.py:241-262`) returns `physical_state`, `financial_state`, `recovery_state`, and
`teardown_state` directly to the caller. Those are domain-local vocabularies with no spec entry:

- `FinancialState` (`domains/bare_metal/.../models.py:29-36`): `pending`, `collection_unknown`,
  `collected`, `collection_blocked`, `reclaimed`, `manual_review`.
- `RecoveryState` (`:37-44`): `none`, `funding_returned`, `reclaim_pending`, `reclaimed`,
  `loss_manual`, `manual_review`.
- `TeardownState` (`:45-52`): `not_started`, `pending`, `tearing_down`, `failed`, `torn_down`,
  `released`.

Bare metal also reads `funding_reason` from the transient receipt only, not from
`record.status_receipt`, and returns only the transient receipt as `receipt`
(`hosted_lifecycle.py:262`). When the authority refuses an operation, `_finish_manual`
(`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:885`) returns an outcome with no
receipt, so a parked bare-metal obligation projects `receipt: null`. VM and API credits fall back
through `reclaim_receipt`, `collection_receipt`, `status_receipt`, `materialization_receipt`
(`settlement_composition.py:1224`; apicredits `:613`). The incident therefore does not ride along on
bare metal the way it does on VM (see 5.4).

The three field sets, exactly:

- VM, `SettlementPublicResponse`
  (`domains/vms/storefront/src/market_storefront/models/hosted_settlement_models.py:15-33`, handlers
  at `domains/vms/storefront/src/market_storefront/controllers/settle_controller.py:281`, `:297`,
  `:313`): `settlement_ref`, `obligation_ref`, `funding_authorization_ref`, `funding_profile`,
  `payer_principal`, `claimant_principal`, `status`, `funding_reason`, `funding_deadline_unix`,
  `action`, `action_kind`, `action_expires_at_unix`, `condition_anchor`, `fulfillment_ref`,
  `receipt`.
- API credits, `ApiCreditsHostedSettlementResponse`
  (`domains/apicredits/storefront/src/apicredits_storefront/settlement_models.py:24-42`, handlers at
  `.../controllers/hosted_settlement_controller.py:75`, `:91`, `:107`): the VM set minus
  `condition_anchor` and `fulfillment_ref`, plus `result` and `tenant_credentials`.
- Bare metal, no response model at all — the raw `Mapping` is returned
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:275`, `:286`, `:297`):
  `agreement_ref`, `obligation_ref`, `settlement_ref`, `funding_profile`, `status`,
  `funding_reason`, `physical_state`, `financial_state`, `recovery_state`, `teardown_state`,
  `fulfillment_identity`, `public_result`, `portable_evidence_ref`, `action`, `receipt`. It drops
  `payer_principal`, `claimant_principal`, `funding_authorization_ref`, `funding_deadline_unix`,
  `action_kind`, `action_expires_at_unix`, and `condition_anchor`.

### 5.4 The incident does reach a buyer, undeclared

The change proposal `openspec/changes/project-an-authoritative-funding-loss/proposal.md:3` states
that the adapter "stores it in mechanism state and the public settlement payload drops it". The code
is more complicated than that.

`_status_receipt` (`adapter.py:816-834`) and `_mechanism_state` (`adapter.py:867-885`) both store
`result.incident.model_dump(mode="json")`. The VM projection returns `"receipt": receipt or None`
(`settlement_composition.py:1252`), where `receipt` is whichever of `reclaim_receipt`,
`collection_receipt`, `status_receipt`, or `materialization_receipt` is set, in that order, behind a
transient receipt when one is supplied (`:1224-1231`). When the last completed operation was a status
reconcile, the incident is on the
wire. The e2e harness already reads it that way:
`e2e-tests/tests/e2e/roles/scenarios/vms/hosted/network.py:1165-1176` pulls
`receipt["incident"]["kind"]` and `["state"]` off the status payload.

So the incident is reachable but undeclared: not a named field, not guaranteed present, and not
covered by any requirement. `SettlementPublicResponse`
(`domains/vms/storefront/src/market_storefront/models/hosted_settlement_models.py:12-33`) types
`receipt` as `dict[str, Any] | None`.

## 6. Storefront-mediated versus direct authority reads

`openspec/specs/market-composition/spec.md:11`, Requirement "Hosted payer calls bypass storefront
without bypassing authority":

> Composition roots MAY expose exact released-client payer profile/setup/instrument operations and
> one accepted-obligation funding authorization directly from buyer to hosted authority. [...]
> Storefronts MUST NOT proxy, choose, or persist payer/instrument state, and buyers MUST NOT call
> hosted escrow status, reclaim, condition, collection, provider, recovery, or operator surfaces
> directly.

Seven forbidden surface families: escrow status, reclaim, condition, collection, provider, recovery,
operator. Its scenario at `:20-23` is explicit: "**WHEN** a marketplace purchase needs hosted
settlement status after start / **THEN** the buyer uses the authenticated seller storefront rather
than the hosted authority."

`openspec/specs/buyer-orchestration/spec.md:10` repeats it: "Only these payer operations and exact
per-purchase authorization MAY call the hosted authority directly; escrow start/status/reclaim remain
storefront-mediated." Also `:155`. And `openspec/specs/market-composition/spec.md:180`, Requirement
"Thin hosted consumer boundary": "Buyer composition MAY use kit-owned direct payer/authorization
helpers; storefront composition MUST mediate escrow operations."

The consequence for this inventory: **`EscrowResult.incident` is on a surface a buyer may not call.**
`GET /api/v1/escrows/{ref}` is the only route that carries it, and it is a hosted escrow status
surface. The buyer's only permitted route to it is whatever the storefront chooses to project — which
is the accidental `receipt` passthrough of 5.4.

The storefront-mediated surface is `POST /api/v1/settlements`,
`GET /api/v1/settlements/{settlement_ref}`, and `POST .../{settlement_ref}/reclaim`
(`openspec/specs/storefront-publication/spec.md:307`; buyer transport at
`core/buyer/src/core_buyer/hosted_settlement.py:56-117`). `GET` is authorized against
`agreement.buyer_principal` (`kit/settlement-runtime/src/market_settlement_runtime/hosted_routes.py:158-181`),
and `_require_participant` admits payer or claimant while `_require_principal` narrows collect and
check to the claimant (`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:674-702`).

The operator surface is not merely forbidden to buyers; it is unreachable from the marketplace
altogether. The released client exposes no operator method
(`client:client.py`): `health`, payer profile/setup/instrument, `authorize_funding`,
`confirm_funding`, account readiness/link/rotate/retire, `materialize`, `get_status`, `check`,
`collect`, `reclaim`, `confirm`, `get_attestation`, `publish_fulfillment`, `check_arbiter`. Grepping
`operator` across the client yields only the `OPERATOR_REVIEW = "operator_review"` enum value. There
is no `/api/v1/operator/*` binding anywhere in this repository; the only textual references are in
the unimplemented change (`openspec/changes/project-an-authoritative-funding-loss/proposal.md:19`,
`design.md:13`), both recording that the client exposes no method for
`/api/v1/operator/incidents/{ref}/resolve`.

There is no seller-facing or operator-facing per-obligation read route in the marketplace.
`market settlement status` (`domains/vms/storefront/src/market_storefront/groups/settlement.py:101-118`)
reports mechanism readiness, not obligations. A seller whose money was clawed back after delivering
has no API telling them so; the storefront operator reads its own SQLite and the stage log.

### 6.1 The vocabulary a human actually reads

**VM `market buy`** (`domains/vms/buyer/buy_cli.py`). The only funding line during the wait is
`funding poll #{attempt}  status={status}` (`:976-979`); quiet mode prints a dot per poll
(`:929`, `:931`). Action lines are `Buyer action  complete the action in the opened browser`
(`:969`), `Buyer action  complete the action at the printed URL` (`:971`), and
`Buyer action  interaction is required` (`:973`). The closing panel `Buy complete` (`:1127-1153`)
has rows `Status`, `Seller`, `Negotiation`, `Agreed price`, `Escrow UID`, `Fulfillment UID`,
`Reason`, `Connection`, `Tenant creds`, with border colour keyed to
`ready | failed | timeout | exited | no_matches` (`:1146-1152`) and exit code 4 when the status is
not `ready` (`:1155`). `Status` and `Reason` come from `BuyResult`, not from the storefront body, so
the only values that row can take on the hosted path are `hosted_settlement_not_completed`
(`core/buyer/src/core_buyer/hosted_settlement.py:322`), `user_declined` (`:206`), or the timeout
sentence `Hosted settlement did not reach a stable public status within {n}s` (`:145-148`).

**VM `market settle`** (`domains/vms/buyer/settle_cli.py`) prints nothing about funding state on the
hosted path. It logs `hosted_settlement_terminal` with `settlement_ref` and `status` only
(`:341-345`) and exits 7 when the status is neither `ready` nor `collected` (`:347-348`). The
`Settlement complete` panel at `:594-606` is the legacy Alkahest path.
`buyer action required; rerun with --action open or --action print`
(`core/buyer/src/core_buyer/action_policy.py:43`) exits 8 (`action_policy.py:12`).

**`market settlement status`** in both buyer CLIs (`domains/vms/buyer/cli.py:34-65`,
`domains/apicredits/buyer/cli.py:32-61`) emits `{mechanism}: ready|disabled|unready` followed by
`  {blocker.code}: {blocker.message}`. This is mechanism readiness, not a settlement's state.

**The bare-metal buyer is the only consumer that shows the funding projection.**
`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:85-92` dumps the whole storefront
projection as JSON with `action` replaced by `action_required` reduced to `kind` and
`expires_at_unix`. Used by `start` (`:474`), `complete` (`:520-528`), `status` (`:541-548`), and
`reclaim` (`:594`). Its failure sentences are
`hosted settlement did not reach buyer-ready state: {status!r}` (`:505-508`),
`bare-metal fulfillment ended in state {state!r}` (`:516`), and
`bare-metal fulfillment did not become active` (`:518`).

**Storefront error sentences a buyer can receive**
(`kit/settlement-runtime/src/market_settlement_runtime/hosted_routes.py`): `settlement not found`
(404, `:152`, `:155`), `request retry is pending` (409, `:180`),
`settlement fulfillment already committed` (409, `:350-353`),
`settlement fulfillment or collection already reserved` (409, `:362-365`),
`hosted settlement authority is temporarily unavailable` (503, `:263`),
`hosted settlement status is temporarily unavailable` (503, `:310`),
`hosted settlement reclaim is temporarily unavailable` (503, `:378-381`),
`settlement reservation disappeared` (500, `:386`). Plus
`hosted settlement runtime is unavailable` (503,
`domains/vms/storefront/src/market_storefront/controllers/settle_controller.py:248`).

**Adapter-minted reason strings** beyond those in 2.6:
`hosted settlement {operation} rejected: {code}` (`adapter.py:122-125`) and
`hosted settlement {operation} temporarily unavailable: {code}` (`adapter.py:115-117`).

## 7. The redaction rules

### 7.1 The persistence allowance

`openspec/specs/settlement-servicing/spec.md:27`, under Requirement "Authoritative profile funding
precedes every domain effect":

> Status MAY persist only safe reason, deadline, and action metadata.

It is a `MAY` and the word `only` closes the enumeration. The parallel clause under Requirement
"Hosted financial authority lifecycle" (`:182`) says what the whole row may hold: "exact funding
profile, operation-scoped funding authorization and settlement references, public
lifecycle/reason/deadline/action metadata, condition anchors, canonical fulfillment references, and
opaque receipts", and MUST NOT hold "stable payer/instrument refs, provider identifiers,
Checkout/setup/confirmation/bank-instruction URLs, payment/bank/card/mandate data, credentials, or
raw evidence/provider payloads."

Requirement "Provider-neutral conditional escrow client" (`:201`) bounds "action metadata":

> Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized
> reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable
> receipt.

Its scenario at `:205-206` is the decisive split: "the runtime persists the opaque hosted reference
and public action kind/expiry while the URL/client secret remains transient and service-owned."

The reason is not operator-only. `:231-234`:

> An obligation the marketplace parks as `manual_required` MUST project a stable reason alongside its
> status, in the same field a consumer reads for a funding reason, and every domain adopting the
> hosted mechanism MUST project it identically. A `manual_required` projection carrying no reason
> MUST NOT occur.

So the consumer-visible triple is status, stable reason, deadline, plus transient action kind and
expiry. Against that, `:259` says the reason exists "so the operator can distinguish a refused
condition, an unsupported profile, and an account that lost a capability without provider access".
The specs give the same reason to both roles and give provider detail to neither. **There is no
spec-defined operator channel with wider privileges than the consumer channel.**

### 7.2 The raw action URL

Every rule found:

- `openspec/specs/settlement-servicing/spec.md:13` — persistence "MUST NOT contain [...] client
  secret, or raw action."
- `settlement-servicing/spec.md:206` — "the URL/client secret remains transient and service-owned."
- `settlement-servicing/spec.md:182` — rows MUST NOT persist
  "Checkout/setup/confirmation/bank-instruction URLs".
- `settlement-servicing/spec.md:287` — "URLs, and headers MUST NOT enter fulfillment references,
  hosted requests, settlement rows, logs, or generated fixtures."
- `openspec/specs/buyer-orchestration/spec.md:12` — "CLI output and metadata MUST exclude Customer,
  PaymentMethod, mandate, bank/card detail, client secret, provider payload/identifier, and raw
  action URL."
- `buyer-orchestration/spec.md:22` — the CLI "stores no URL or client secret".
- `buyer-orchestration/spec.md:180` — the CLI "MUST NOT persist or log an action URL, client secret,
  bank/card/payment/customer data, stable instrument ref in storefront state, provider identity,
  request credential, or raw service body."
- `buyer-orchestration/spec.md:155` — actions "are transient and MUST NOT enter run-log events."
- `buyer-orchestration/spec.md:56` — run logs retain "action kind/expiry" and resume "MUST NOT rely
  on a persisted URL".
- `openspec/specs/cli-query-language/spec.md:86` — "`open` MUST open a returned transient buyer
  action, `print` MUST display it without opening, and `fail` MUST stop before performing the action
  [...] The policy MUST [...] NOT cause an action URL or secret payload to enter durable logs."
- `openspec/specs/storefront-publication/spec.md:27` — "raw actions [...] MUST NOT enter negotiation,
  accepted terms, start requests, storefront SQLite, logs, or evidence."
- `openspec/specs/test-compatibility/spec.md:167` — protected reports "MUST exclude [...] raw
  actions/URLs".
- `openspec/specs/settlement-configuration/spec.md:242` — the payer-setup token is transient "on the
  same terms as an action URL: passed to the authority, never persisted in a marketplace row, never
  projected, and never reported."

**An intra-spec tension worth recording rather than resolving.** `buyer-orchestration/spec.md:12`
says CLI *output* must exclude the raw action URL. `buyer-orchestration/spec.md:189-190` says that
when action policy is `print`, "the CLI displays it without opening it or writing it to the run log."
The first requirement is scoped to "Buyer payer-profile utilities are direct and namespaced" and the
second to "Hosted buyer action handling", so they may be two scopes rather than a contradiction, but
the two sentences say opposite things about the same artifact. The implementation follows the second:
`BuyerActionHandler.handle`
(`core/buyer/src/core_buyer/action_policy.py:73-113`) calls `self.print_url(material)` with the URL
itself, and `resolve_buyer_action_policy` (`:47-56`) defaults a non-interactive run to `PRINT`.
`BuyerActionMetadata` (`:24-34`) is documented as a "Durable allowlist for an action; intentionally
excludes its URL" and carries only `kind` and `expires_at_unix`.

The runtime passes the whole action through: `_safe_action`
(`kit/hosted-settlement/src/market_hosted_settlement/adapter.py:806-812`) returns
`result.action.model_dump(mode="json")`, URL included, with the docstring "Return the current action
to the caller; persistence sanitizes it later." `get_buyer_action` (`adapter.py:553-566`) does the
same with the docstring "callers must not persist it." All three storefront projections return that
dict as `action` alongside the separately extracted `action_kind` and `action_expires_at_unix`.

The sanitization the docstring promises is `_safe_buyer_action`
(`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:917-927`), which keeps only `kind`
and `expires_at_unix` and drops `url`, `bank_instructions`, and `operation_ref`. It runs on every
persistence write — `runtime.py:819` for materialize, `:840` for status — and
`sqlite_repository.py:1225` serializes only the reduced dict. A `record.buyer_action` reloaded from
disk is therefore URL-free, which is why the projections can only fill `action_kind` and
`action_expires_at_unix` from it. `payer_setup_projection`
(`kit/hosted-settlement/src/market_hosted_settlement/payer.py:487-500`) applies the same reduction to
CLI JSON output, with the comment "Exclude all transient action values from command JSON".

So the operative rule as implemented is: the URL may cross the wire and may be displayed once, and
may not be persisted, logged, or re-read. It exists only in flight — authority, adapter, runtime
return value, HTTP response, the buyer's browser.

### 7.3 The incident and operator detail

The word `incident` appears in the normative specs exactly twice, both as a status category and never
as a payload: `settlement-servicing/spec.md:41` ("MUST project an incident/manual status") and `:55`
("WHEN hosted status reports a post-collection loss incident"). The only thing the spec permits
surfacing is at `:56`: "exposes safe operator-required state".

No requirement anywhere grants a structured incident object a place in persistence or in any
projection. Under `:182`'s closed enumeration and `:229`'s "identifiers, and payloads MUST NOT reach
marketplace persistence or any marketplace response", whether a structured incident falls inside or
outside "opaque receipt" is unsettled. The code stores and projects it regardless (5.4).

### 7.4 The provider-neutrality boundary

`openspec/specs/market-composition/spec.md:25` is the rule that makes the whole vocabulary problem
structural:

> Marketplace packages, schemas, config, persistence, logs, tests, and deployment MUST use released
> hosted payer/profile/authorization and conditional-escrow models only. They MUST NOT import Stripe
> SDK/types, model Customer, PaymentMethod, mandate, charge, debit, bank instruction, transfer,
> return, refund, dispute, webhook, provider credential/ID, hosted database/migration,
> reconciliation, or operator recovery behavior.

The marketplace may not model return, refund, or dispute. `settlement-servicing/spec.md:41` repeats
it from the operational side: the marketplace "MUST NOT select a Stripe cancellation, return, refund,
reversal, or dispute operation." `settlement-servicing/architecture.md:154` records that "disputed
outcomes [...] require a separate accepted design." There is no dispute state in the normative specs.

## 8. Evidence, receipts, journals

### 8.1 In the authority

Two disjoint journals, and which one records a loss depends on how it was discovered.

**Discovered by `status()` polling.** A `returned` funding on a `collected` escrow writes a
`funding_incidents` row (`authority:.../database.py:839`) with `kind` = `ach_return` for
`us_ach_debit.v1` else `post_collection_loss`, `timing` = `post_collection`, `required_action` =
`allocate_platform_loss`, and `evidence_digest` = `sha256({funding_ref, state})`
(`authority:.../authority.py:3484-3502`). `financial_state` stays `collected`;
`funding_records.state` becomes `returned`. Written by `_funding_incident`
(`authority:.../authority.py:5689`) as `INSERT OR IGNORE`, unique on
`(funding_ref, incident_kind, evidence_digest)`. Proven by
`test_late_ach_return_preserves_completion_and_opens_post_collection_incident`
(`authority:service/tests/test_authority.py:2443`).

Readable by the payer, seller, or storefront on that escrow as `EscrowResult.incident`, and in full
by an operator via `GET /api/v1/operator/funding/{funding_ref}`
(`authority:.../recovery.py:838`), which returns all incidents with `timing` and `required_action`.

**Discovered by webhook or terminal-risk reconciliation.** `_record_terminal_loss`
(`authority:.../recovery.py:562`) writes an `operator_incidents` row with
`error_class = 'platform_loss'` and `error_code` in
`{charge_failed, charge_dispute_created, transfer_reversed}`, `context_json = '{}'`, plus an
`admin_audit_events` row (`actor='system'`, `action='open_incident'`) and a `platform_loss_detected`
critical alert. It writes no `funding_incidents` row and updates neither `funding_records` nor
`escrows`, and fires only when `financial_state` is `collecting` or `collected`
(`authority:.../recovery.py:578`). Proven at `authority:service/tests/test_authority.py:1710-1724`.
**Operator-only.**

`OperationReceipt.receipt` is `sha256({escrow_ref, operation, operation_ref})`
(`authority:.../authority.py:4744`) and carries no funding evidence. Payer return addresses are held
encrypted on `funding_reversals.return_instructions_ciphertext`
(`authority:.../database.py:925`, migration `0007_return_instructions`) and NULLed on terminal
(`authority:.../authority.py:4718`, `:4770`).

### 8.2 In the marketplace

| Artifact | Written at | Carries the loss? | Reader |
| --- | --- | --- | --- |
| `settlement_obligations.mechanism_state` | `adapter.py:867-885` | yes, full `FundingIncidentProjection` | storefront DB only |
| `settlement_obligations.status_receipt` | `adapter.py:816-834` | yes | storefront DB; reaches the buyer via the `receipt` field (5.4) |
| parked reason under `manual_reason` | `adapter.py:838-865` | only when the authority supplied no `funding_reason` | via `funding_reason` |
| operation journal row | `kit/settlement-runtime/src/market_settlement_runtime/sqlite_repository.py:104`, `:530-537` | operation, receipt, `last_error` | storefront DB only, **no read route** |
| stage-log event | VM only: `settlement_composition.py:1381-1382`, `:719-727`; worker at `servicing.py:265-268` | reason string only | operator: stderr JSON plus the `stage_events` table (`core/storefront/src/core_storefront/stage_log.py:66-104`) |
| capacity event | `kit/site/src/market_site/ledger.py:1317-1322`, `CapacityEvent(kind="lease_truncated")` | no — carries only `resource_id`, no obligation ref, no reason | site authority DB |
| bare-metal lifecycle row | `hosted_lifecycle.py:366-372`, `financial_state="collection_blocked"`, `recovery_state="funding_returned"` | yes | storefront DB only |

A lost settlement produces no new marketplace evidence artifact.
`openspec/specs/settlement-servicing/spec.md:41` forbids rewriting the completed fulfillment record
and `:51` keeps it "attributable"; the only artifact the spec names for the loss path is status plus
reason.

## 9. A fulfillment already begun

### 9.1 What the specs require

`openspec/specs/fulfillment/` says nothing about funding. Grepping its 462 lines plus
`architecture.md` for `fund`, `dispute`, `return`, `reversal`, `loss`, `refund` returns no hit on
funding. The capability is deliberately funding-blind; its "does not own" list is at `:21-28`.
`begin_fulfillment_teardown` is valid only from `active` (`fulfillment/spec.md:430-432`).

The normative home is `openspec/specs/settlement-servicing/spec.md:41`, Requirement "Profile-specific
reclaim and loss remain authority-owned", which fixes three windows:

- Return **before** fulfillment: block fulfillment and collection, follow hosted reclaim/recovery
  (`:43-46`).
- Return **after fulfillment starts, before collection**: "preserve the immutable fulfillment record,
  block collection, order domain-owned VM teardown and capacity cleanup to convergence, and delegate
  financial return/reclaim entirely to the hosted authority" (`:48-51`).
- **Post-collection** loss: "project an incident/manual status without rewriting completed
  marketplace fulfillment or attempting local reclaim" (`:53-56`).

`settlement-servicing/spec.md:268` adds that "fulfillment success MUST permanently remove marketplace
reclaim authority and MUST resume check and collect after restart even when expiry subsequently
passes."

`openspec/specs/physical-provisioning/architecture.md:45`, non-normative but on point: "Financial
return before collection blocks further collection and starts convergent physical cleanup;
post-collection loss is an incident and never releases capacity."

`vm-storefront-fulfillment`, `compute-provisioning-contract`, `deployment-state`, and
`introduction-delivery` are all silent on funding loss.

### 9.2 What the code does

Post-collection polling continues because `_operation_identity`
(`kit/hosted-settlement/.../adapter.py:887-903`) sets `"terminal_risk_monitoring": True`
unconditionally, and `servicing.py:158-167` keeps rescheduling `status` for a row whose
`collection_state` is `succeeded` when that flag is set. `terminal_risk_monitoring` appears in no
spec.

VM teardown runs through `_terminal_requires_lease_truncation`
(`domains/vms/storefront/.../settlement_composition.py:667-671`), which returns false when
`collection_state == "succeeded"`. So a post-collection loss leaves the machine serving.
`truncate_lease_for_terminal_settlement` (`:676-733`) sets `reservation.state = leased`,
`lease_end_utc = now`, and writes a `lease_truncated` capacity event
(`kit/site/src/market_site/ledger.py:1302-1325`). It does not call `begin_fulfillment_teardown`;
actual deprovision is indirect, via lease expiry
(`openspec/specs/compute-provisioning-contract/spec.md:51-58`).

Bare metal is broken on this path; see 1.5. API credits releases an uncommitted quota hold on
reclaim (`domains/apicredits/storefront/.../settlement_composition.py:696` onward) and does nothing
on a post-collection loss.

Reclaim is blocked until domain cleanup lands: `runtime.py:587-600` refuses with "domain cleanup must
complete before reclaiming returned funding" when `mechanism_status == "failed"`, a fulfillment
exists, and collection has not succeeded. The buyer's own status poll wakes the worker for the same
case (`hosted_routes.py:293-299`), and `sqlite_repository.py:1443-1447` and `:1487-1494` keep the row
eligible and route it to the `cleanup` operation.

`funding_deadline_unix` is relayed into every projection
(`settlement_composition.py:1244-1245`) and acted on nowhere. `runtime.reclaim` gates on
`record.obligation["expiration_unix"]` (`runtime.py:586`) — the marketplace's own deadline, not the
authority's.

`kit/settlement-runtime/.../jobs.py` has no funding awareness; the coordinator knows only `fulfilled`
and `failed` (`:39-50`, `:133-168`). `kit/settlement-runtime/.../policy.py` is a generic ordered
failure dispatcher with no funding-loss action registered and no hold/release/revoke vocabulary.
`kit/delivery` and `kit/resource-pools` have no funding concept at all; the only `hold` functions in
`kit/resource-pools/src/market_resource_pools/hints.py:111`, `:152`, `:167` are capacity TTL policy.

## 10. Active OpenSpec changes on this subject

| Change | Tasks | State |
| --- | --- | --- |
| `project-an-authoritative-funding-loss` | 0/18 | proposal only |
| `disburse-a-settlement-disposition` | 0/30 | proposal only |
| `consume-expanded-stripe-funding` | 12/15 | implemented; three items externally blocked |
| `carry-the-payer-return-address` | 16/16 | implemented |
| `name-a-refusal-that-will-not-converge` | 11/11 | implemented |
| `name-unverifiable-responses` | 7/8 | implemented but for a final diagnosis |

`project-an-authoritative-funding-loss` adds no new lifecycle literal. Its
`proposal.md:20`: "No new state in the shared lifecycle. `manual_required` already carries the parked
obligation; this change projects what put it there." It adds two optional status fields: the
incident's `incident_ref`, `kind`, and `evidence_digest` passed through unchanged, and a derived
`fulfillment_blocked` boolean (`proposal.md:9-10`, `design.md:32-35`). `design.md:32` records the
rejection of `incident.state` as "the authority's internal resolution progress". Its delta at
`specs/settlement-servicing/spec.md:9` would require that "A post-collection loss MUST leave capacity
service running." `design.md:50` records the accepted trade: "a seller can lose the money and keep
serving the machine". `design.md:62` leaves open whether a `refund` or `transfer_reversal` incident
should read differently to a `card_dispute`; all three project identically in the proposal.

`disburse-a-settlement-disposition` records a named gap it does not close
(`proposal.md:129`): "Commitment finality — how long a committed payment stays reversible, and by
whom — is not modeled here. It is a real gap with real consequences for fulfillment timing and
reserves, and it is a separate change." It also notes (`proposal.md:127`) "no change to which
reversal mechanic the hosted authority selects — `cancel`, `return`, and `refund` remain its choice
from funding state, never the marketplace's."

Three active changes edit the same requirement, "Profile-specific reclaim and loss remain
authority-owned". `consume-expanded-stripe-funding` is already synced; the other two are unimplemented
and will conflict textually.

## 11. Known defects recorded in commit bodies

Commit messages in both repositories are substantive primary sources. The ones bearing on this
subject:

- `9973bade` "Correct what a funding loss does before it is called missing" retracts an earlier claim:
  "The note said kit/settlement-runtime carries no funding-loss handling and that a disputed funding
  does not stop delivery. Neither was checked. A post-collection loss is observed, parks the
  obligation as manual_required, and shows in the buyer-visible status ahead of collected. What is
  absent is what any domain does about it afterwards, and the projections the two withheld lanes read
  — which are two different projections, not one."
- `2a3ecee2` "Record the bank-transfer return proven against Stripe test mode" records an open defect
  outside every change's scope: "The neutral runtime finishes a reclaim with state='succeeded'
  whenever the mechanism client returns, without reading the financial_state the adapter hands back",
  so "the buyer-facing status read reclaimed while the authority held reclaiming, the reversal
  pending". Also recorded at `openspec/changes/carry-the-payer-return-address/tasks.md:120-123`, and
  deliberately left open as "a question about the runtime's terminal contract for every mechanism".
- `2a3ecee2` also records a hard limit on proving the return: "A push-funded return reaches succeeded
  only when the payer answers Stripe's mail", and test mode's only transition out of
  `requires_action` is `expire`, to `failed`.
- `0650af66` "Record what the bank-transfer reclaim lane actually refuses": `hosted_routes.reclaim`
  "ends in a bare `except Exception` that rewrites every remaining failure as a fixed 503 with that
  text (`hosted_routes.py:352-356`), and the module logs nothing, so the cause does not survive the
  process."
- `04fe8f61` "Report a funded obligation whose fulfillment could not begin": the start route's bare
  except answered 503 "hosted settlement authority is temporarily unavailable" for a fulfillment
  failure, so "a funded obligation was hidden from the party that funded it." Fixed; the comment
  block is at `kit/settlement-runtime/.../hosted_routes.py:236-247`.
- `authority:fb0cd29` "Reject an impossible funding reversal instead of calling it uncertain":
  "stripe.InvalidRequestError was not wrapped, so it escaped the ProviderRejectedOperationError
  branch into the authority's bare except, which reports provider_uncertain with retryable=True. A
  caller was told to retry a permanent failure forever." Fixed.
- `authority:openspec/changes/reject-an-impossible-funding-reversal/proposal.md` records the
  downstream symptom: "a marketplace consumer retried this to its bound and reported a timeout,
  naming no cause — an authority that refuses permanently while advertising retryability makes every
  layer above it unable to diagnose itself."
- `openspec/changes/name-a-refusal-that-will-not-converge/tasks.md:79-84` records that "the
  authority's own `retryable` flag is false for all three codes here, including `operation_conflict`.
  That flag means the identical request may be re-sent, which is not what a polling wait asks."
- `c3af88b8` "Record that a refusal lane does not observe its own reason": the two card refusal lanes
  "prove no funding artifact exists, which is the property worth proving, but not which refusal the
  provider gave: without a PaymentIntent there is no decline_code, so the two lanes assert the same
  absence and differ only in the outcome each copies from its scenario."

## 12. Contract movement across releases

Diffing `authority:.dist/openapi-v0.3.0.json` through `v0.4.0`, `v0.4.1`, and `v0.4.2`: the only
contract change is `ReclaimRequest` gaining `return_instructions_email`. No path and no enum value was
added or removed. The v0.4.2 the marketplace pins carries exactly the enum sets in section 2, minus
`ReversalKind` and `ReversalState`, which are never published.

Three client versions are in play in this checkout at once. `kit/hosted-settlement/pyproject.toml:9`
and the domain `pyproject.toml` files pin `==0.4.2`; the uv locks resolve 0.4.0; and `.dist/` carries
a stale `arkhai_hosted_settlement_client-0.2.1` wheel. `EscrowResult` and all six value sets are
byte-identical across 0.2.1 and 0.4.2, so nothing in this inventory turns on which is installed, but
the divergence is real.

The three unchecked tasks in `consume-expanded-stripe-funding`
(`openspec/changes/consume-expanded-stripe-funding/tasks.md:36-38`) are all blocked on the same thing:
no complete signed staged producer/consumer artifact pair and no protected Stripe test-mode
credentials, and "local simulation cannot substitute for those assertions."
