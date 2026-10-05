# Design

## Context

The current stack has peer Alkahest and Arkhai payment integrations, but selection is repeated in orchestration, delivery and recovery. This change declares dispatch once per domain role and makes settlement evidence the delivery boundary. Escrow carriers and the obligation runtime remain where they are until `move-escrow-into-alkahest`; public listing, registry and settlement wire formats remain for `drop-escrow-from-shared-wire`.

The preserved stories are VM purchase and restart-safe delivery, bare-metal purchase with selected-site access and teardown, API-credit new-key/top-up purchase with exact-once grants, and contact introduction without payment or physical delivery. This is a composition refactor, not a claim of new live payment or hardware qualification.

## Decisions

### One declaration per domain role

Each domain role owns one `mechanism_id -> stage` table. Its entries assemble mechanism-specific acceptance validation, accepted-artifact construction, prerequisite resolution and settlement execution from that kit's APIs. Existing publication/readiness/compatibility registrations remain separate contracts, but are composed from the same supported entries; registration alone never makes an option settleable.

A table is a composition declaration, not a mechanism interface. Core performs an exact lookup using `Agreement.settlement.mechanism`, carries the accepted outcome unchanged, and invokes the domain-bound role hook. The existing buyer `SettleFn` is a role orchestration hook, not a protocol kits must implement. Seller stages have domain-owned request/context types. Core does not require `accept / buyer_settle / seller_verify`, an escrow, or a buyer-first sequence. A seller-first or fused mechanism is equally valid.

A missing entry in accepted durable work fails before effects and is operator-visible; it never falls through to Alkahest. Admission and publication intersect registration compatibility/readiness with the role table, so unsupported options cannot be selected for fresh work. Disabling a mechanism for new work does not delete the stage needed by accepted recovery.

### Core owns the table carrier and evidence record

Add `core/src/market_core/settlement.py`, exported by `market_core`, for a generic immutable `SettlementStageTable[StageT]` (a mapping with no callable bound or stage-method requirements) and `SettlementEvidence`. Core carrier ownership avoids an upward dependency from core orchestration to a kit lifecycle implementation. Domain and kit packages can both consume the same dependency-light types.

`SettlementEvidence` has exactly the shared fields `negotiation_id`, `mechanism`, `settlement_ref`, `status`, and `evidence`. References are opaque and may be absent while pending. Status is a non-empty domain-defined value, not a core financial lifecycle or transition order. Core validates carrier shape and identity continuity, not the mechanism payload. Seller domain evidence distinguishes pending, verified and failed; verified means the domain's protected delivery gate passed, not that collection or financial servicing finished. Buyer-local progress cannot authorize seller delivery.

Role tables are validated at the existing explicit domain composition boundary. `domain_contract.py` must stop requiring every settlement composition to provide `verify` and `build_plan`; these become implementation details of the applicable table entries. Existing escrow helpers and runtime stay in their current packages and can be bound explicitly into Alkahest/contact stages. In particular, `_settle_one` may remain an escrow helper in buyer core for this change, but only a domain table entry chooses it: the core dispatcher has no automatic escrow fallback.

The runtime-only `core_storefront/domain_lifecycle.py` fulfillment carriers receive evidence and use its settlement reference for continuity, rather than requiring a fake escrow identity for payment delivery. This is an internal carrier adjustment, not removal of the public `escrow_uid` wire field. Responses continue to project the existing public coordinates at the domain boundary.

### Evidence is the boundary after settlement

Each seller persists one accepted-Agreement-bound evidence record per negotiation. Evidence payloads are domain-owned versioned envelopes (`vm.settlement-evidence.v1`, `bare_metal.settlement-evidence.v1`, `api_credits.settlement-evidence.v1`), retaining the Agreement digest, authoritative source evidence and validated delivery inputs. Exact retries preserve mechanism, Agreement digest and established settlement reference; changed reuse conflicts. A pending row is not a delivery authorization.

The stage verifies mechanism evidence and derives every fact delivery needs: funding expiry/hold end, accepted domain terms, any Alkahest token-backed lease bytes and condition anchor. Planners, physical convergence, credit issuance and private-result handling read these inputs and verified status; they never recognize a mechanism ID, a chain-name sentinel, receipt presence or escrow absence as authorization. The mechanism field is audit/display only outside settlement dispatch and the stage that owns it.

On restart, the settlement boundary resolves the recorded Agreement through the same role table and lets that stage revalidate its persisted source evidence before handing normalized evidence to common delivery recovery. This preserves receipt rechecking without putting an Arkhai verifier into the resume runtime. Post-delivery Alkahest attestation, claim binding, refund and compensation remain inside the selected stage's continuation. Common delivery returns its result; it does not choose these actions by inspecting an ID. Continuations are reconstructed from accepted state, not serialized callables or current priority.

### Domain persistence, not escrow-shaped payment jobs

Reuse each domain's persistence owner rather than add a core evidence database:

- VM: generalize `payment_repository.py` into the domain settlement-evidence repository; separate negotiation-scoped delivery context, phase checkpoints and convergence claims from `escrows`. Alkahest may retain its real escrow rows and obligation journal. Both settlement entries hand off evidence to the same physical-delivery functions.
- Bare metal: `bare_metal_settlement_records` already holds Arkhai mandate/receipt evidence in this checkout. Generalize it to all supported stages and remove the residual `chain_name == arkhai.payments.v1` status fallback. Fulfillment stops accepting either an escrow row or a payment row as interchangeable proof and reads only verified evidence. Preserve the existing selected-site lifecycle.
- API credits: introduce negotiation-scoped settlement evidence and issuance progress through the existing storefront migration owner; payment issuance no longer uses an `escrows` row as its progress journal. Keep signed issuance evidence and private credentials in their existing separate repositories. Issuance evidence proves a grant after delivery; it is not the settlement evidence that authorizes delivery.

No copy-then-drop or compatibility adoption is required. Edit the migrations that introduce these tables and affected grant columns in place; rebuild disposable databases. Existing databases must be reset explicitly before first use, never silently repaired at startup. No shared listing/registry/wire migration is included.

### Credits service receives issuance authorization, not settlement evidence

Use the existing authenticated `CreditsServiceClient` issuance command as the authorization. The storefront alone verifies settlement; after verified evidence it constructs the immutable command containing `negotiation_id`, deterministic `fulfillment_id`, owner, service, resource, quantity, key target, request digest and optional quota-hold reference. Derive the fulfillment identity uniformly from negotiation ID. The quota-hold reference remains an operational admission hint rather than part of the immutable purchase-intent digest, so an expired hold can be replaced without changing a grant's intent.

Remove `mechanism` and the escrow/obligation reference from the credits service request/result and grant identity. Preserve the current issuance schema names with the in-place contract change; there is no old-payload adapter. Update producer and consumer together. The service validates the command/digest, rechecks key ownership/status and quota, and commits or replays exactly one grant. The storefront retains settlement references for audit, Alkahest signed issuance publication and stage-owned compensation.

This is an authority-preserving simplification, not a new JWT, capability-token service or second signature protocol. The existing operator-authenticated service channel is the trust boundary; possession of the operator credential already permits issuance. Sending raw receipts would not improve security unless the credits service independently verified every mechanism, which would duplicate storefront policy and add kit dependencies. Bearer secrets stay out of both settlement evidence and the authorization's public projections. Legacy Alkahest grant-adoption code is removed, not generalized, under the no-compatibility decision.

### Optional convention is deferred, including its home

An opt-in agree / buyer settle / seller verify convention lives in a kit, never in core, and must not import either mechanism or any domain. Its package is chosen when it is first implemented. `kit/settlement-runtime` is not assumed: `move-escrow-into-alkahest` turns it into a servicing library internal to Alkahest and contact exchange, which Arkhai payments should not depend on.

Do not implement that convention or adapters in this change. The current adapters differ in acceptance artifacts, post-delivery attestation/compensation and durable servicing; extracting a common callable shape now would risk turning the rejected core port into a required kit port. Domain stages can bind existing helpers without copying their runtime. Record the opt-in boundary in permanent architecture; a later concrete adapter extraction can earn the new module through demonstrated reuse. Contact exchange must not be forced through this convention.

## Branch inventory

Inventory at base `331768160ba5528634aefd75b09ef89efe742918`: search `core/` and `domains/` for the requested IDs/constants and `accepted_escrow_proposal`, excluding `.venv`, `build` and tests; inspect executable comparisons, then check aliases such as `ALKAHEST_MECHANISM` and the funding-gate map. Tests, literals/defaults, help examples and generic equality between selected and advertised IDs are not concrete-mechanism dispatch.

There are **50 concrete-ID comparison sites in 26 production files**: **23 T** (table-owned composition/admission hooks), **14 E** (evidence/issuance-authorization reads, including deleting compatibility fallback), **13 M** (mechanism-owned validation inside a stage). The map in `prepare_credit_issuance_request` is one additional E dispatch site with two ID keys, not a comparison. The first-pass accepted-proposal comparison scan finds **23 directly spelled None checks**: one T dispatch, eleven M stage/materialization guards and eleven carrier-projection guards. Alias/type-test sites are classified below separately, including the VM acceptance-artifact shape branch. A comparison spanning several source lines counts once; carrier parsing is not settlement dispatch.

Paths below abbreviate package roots, not ownership:

| File | Concrete comparisons | Disposition |
|---|---:|---|
| `core/buyer/src/core_buyer/negotiation_client.py` | 1 | T: Alkahest-only missing-plan validation becomes a selected entry's acceptance validator; keep generic exact-Agreement checks |
| `domains/apicredits/buyer/buy_cli.py` | 1 | T: buy settlement dispatch |
| `domains/apicredits/buyer/deal_helpers.py` | 1 | M: accepted Alkahest-obligation decode belongs in that stage |
| `domains/apicredits/buyer/payments.py` | 4 | T: registration selection; M x3: payment-only option/mandate checks |
| `domains/apicredits/buyer/settle_cli.py` | 1 | T: accepted-run dispatch |
| `domains/apicredits/service/src/services/keys_service.py` | 3 | E: remove mechanism allowlist, escrow alias and legacy Alkahest replay adoption; consume authorization |
| `domains/apicredits/settlement/fulfillment.py` | 3 + gate map | E: common issuance uses evidence; retry policy is supplied by the stage and post-issuance attestation/compensation returns to the Alkahest continuation |
| `domains/apicredits/settlement/payments.py` | 2 | M: payment clause and mandate validators |
| `domains/apicredits/storefront/src/apicredits_storefront/controllers/settle_controller.py` | 6 | T x2: dispatch/refusal; E x2: status/re-drive and reference projection; M x2: request/Agreement validation moves into payment stage |
| `domains/apicredits/storefront/src/apicredits_storefront/negotiation_runtime.py` | 3 | T: acceptance input validation, mandate construction and quota-hold hook |
| `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py` | 3 | T: Alkahest readiness inputs/client construction and payment clause validation are table-entry hooks |
| `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/arkhai_payments.py` | 1 | M: payment Agreement guard |
| `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py` | 1 | T: supported buyer stage, not a hardcoded payment-only branch |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/arkhai_payments.py` | 1 | M: payment option guard |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py` | 2 | T: resources for the enabled Alkahest entry, no implicit default |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_service.py` | 2 | T: verify dispatch; E: delete chain-name-sentinel status fallback |
| `domains/vms/buyer/arkhai_payments.py` | 2 | M: payment Agreement guard and payer selection |
| `domains/vms/buyer/settle_cli.py` | 2 | T: accepted-run dispatch and unsupported refusal |
| `domains/vms/storefront/src/market_storefront/arkhai_payments.py` | 1 | M: payment option guard |
| `domains/vms/storefront/src/market_storefront/cli_publish.py` | 1 | T: Alkahest readiness-input projection |
| `domains/vms/storefront/src/market_storefront/controllers/settle_controller.py` | 2 | T: seller dispatch/refusal |
| `domains/vms/storefront/src/market_storefront/negotiation_runtime.py` | 1 | T: accepted mandate hook |
| `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py` | 2 | E: source revalidation moves to the selected stage; delivery follows validated evidence and stage continuation |
| `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_planner.py` | 2 | E: stage-supplied lease/condition encoding, no ID switch |
| `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py` | 1 | E: delivery result returns to stage-owned completion |
| `domains/vms/storefront/src/market_storefront/settlement_composition.py` | 1 | T: Alkahest readiness-input hook |

Accepted-proposal guards by file:

- T x1: `core/buyer/src/core_buyer/orchestration.py:make_settle_hook` dispatch goes. M x1: `_settle_one` checks its own required input, reachable only from an explicit stage.
- M x10: API-credit `buyer/deal_helpers.py` (1), `buyer/settle_cli.py` (1); VM `buyer/deal_helpers.py` (1), `buyer/escrow_cli.py` (3), `buyer/settle_cli.py` (3), `negotiation/policies.py` (1). Keep/move these within Alkahest materialization or the existing namespaced raw Alkahest utility, never use them to select settlement.
- Carrier projection x11: core buyer `negotiation_client.py` (1), `orchestration.py` (1); API-credit buyer `buyer_client.py` (2), `negotiate_cli.py` (1), storefront `negotiation_runtime.py` (1); VM buyer `buyer_client.py` (2), `buy_cli.py` (1), `negotiate_cli.py` (1), storefront `negotiation_runtime.py` (1). These serialize/decode an optional existing field; they do not choose a mechanism and remain opaque.

Alias/type-test follow-up:

- T: VM storefront `negotiation_runtime.py:_build_response_artifacts` chooses escrow-artifact construction from `isinstance(proposal, Mapping)`. Bind that construction to its Alkahest entry; retain the existing flat-wire coercion that resolves the selected mechanism, not an escrow-presence settlement fallback.
- M: VM/API-credit `buyer/settle_cli.py:_accepted_proposal_chain` and VM `buyer/escrow_cli.py` proposal dictionaries are Alkahest-owned field readers. API-credit/VM `negotiation/policies.py` accepted-proposal dictionary guards are materialization/projection within the existing legacy acceptance adapter; they do not authorize delivery.
- Carrier: core buyer `negotiation_client.py:parse_accepted_terms_from_reply` checks the `raw_esc` dictionary solely to decode an optional field. `deal_helpers.py`'s two captured-proposal blocks validate presence, dictionary shape and transcript consistency; keep these fail-closed parsing checks, not mechanism choices.

The second pass also found mechanism-specific typed allowlists/defaults in API-credit `settlement/credits_client.py`, service `models/keys_model.py` and `db/migrations.py`; remove them with the authorization/grant rewrite. The existing declarations in bare-metal `settlement_composition.py` become its table, not extra registries. Core `schemas.py` flat-escrow coercion, `core_storefront/escrow_identity.py` backfill, VM `publication_migration.py`, raw escrow commands, and field-presence/transcript consistency checks are existing carrier/Alkahest compatibility surfaces, not new dispatch: retain them for the explicitly out-of-scope carrier/wire work. No contact-ID comparison was found outside kits; its supported seller entry and fused evidence handoff still have to survive composition.

## Execution and first use

Land shared core carriers/dispatch first. VM, bare-metal, API-credit storefront/buyer, and credits-service work then have disjoint file ownership. The credits-service worker owns the domain client DTO/digest; the API-credit storefront worker consumes it and depends on that interface before final validation. Domain workers own their evidence migrations and repositories; the evidence-storage section is a contract checklist, not a competing worker on those files.

Use fresh disposable databases and installed internal wheels. First use is the existing accepted-run `market settle --from <run>` surface for VM/API credits, the bare-metal purchase/result surface, and the existing controlled seller settlement/typed-credit-client paths. Preserve Alkahest and contact behavior as well as wallet-free payment dispatch. Check deployed readiness before complete-deal scenarios. A controlled local example establishes wiring only, not live ledger/hardware qualification; unavailable external prerequisites are reported rather than replaced with a mock success.

## Core implementation boundary

`market_core` exports `SettlementStageTable[StageT]` (immutable Mapping; opaque
values; mapping or duplicate-checked pair input) and frozen `SettlementEvidence`
with exactly the five shared fields above. Evidence supports `to_dict`,
`from_dict` and `validate_identity`; the copied payload mapping is read-only,
with nested values left domain-owned. No status vocabulary is imposed.

`ImmutableSettlementCapability` declares optional `buyer_stages` and
`seller_stages`; at least one non-empty table is required, and supplied
buyer/storefront roles require their matching table. No `verify` or
`build_plan` capability methods remain. Legacy storefront artifact construction
receives an explicit `build_plan=` callback.

Buyer `make_settle_hook(stages=..., invoke=...)` invokes
`invoke(selected_stage, NegotiationResult, on_event)` and returns `BuyResult`.
The exact outcome, Agreement bytes and settlement data remain unchanged.
`make_escrow_settle_hook` binds the existing escrow ports explicitly into an
applicable entry, never a dispatch default. `validate_acceptance(outcome)` in
`negotiate_with_seller` and `make_negotiate_hook` runs before accepted-round
observation; each domain resolves its same entry and owns required artifacts.
`BuyerSettlementPolicy` requires the supported table as `stages=`.

`BuyResult` and recovered `DealContext` carry optional `settlement_evidence`.
The dispatcher emits a `settlement_evidence` event and recovery correlates it
with the accepted Agreement and established reference. Storefront transient
input can carry evidence; `StorefrontFulfillmentContext` requires it and exposes
`settlement_ref`, and `StorefrontFulfillmentLifecycle` returns that reference
rather than `escrow_uid`. Public wire DTOs are unchanged. Domain boundaries
project their legacy public coordinates explicitly.

Sections 2–5 must adapt the concrete domains to these signatures before their
consumer suites can run. Keep applicable escrow behavior as an explicit table
entry; preserve its missing-plan/proposal guard in the selected validator.
Core contains no mechanism-ID or proposal-presence dispatch; existing carrier
projections/coercions and the explicit escrow helper's own input guard remain.

Core diff/comment/import review and focused validation are recorded in
[`core dispatch evidence`](../../../docs/attachments/core-dispatch/index.md).
This is implementation self-check evidence, not independent or live domain
qualification. Domain evidence schemas, seller revalidation and joined
qualification remain with their assigned sections. Roadmap closeout is 8.7.

## VM seller implementation boundary

Tasks 2.2–2.3 use `VmSettlementRepository` in the existing `payment_repository.py` owner. `vm_settlement_evidence` stores negotiation, mechanism, exact Agreement digest, established reference, status and versioned source/delivery payload. `vm_delivery_records` independently stores negotiation-scoped immutable request/context, physical identities, phases, private results and expiring claims. The introducing migration and fresh table definition are edited in place; databases containing the former payment table are refused and require an explicit reset.

Seller stages supply `vm.delivery-facts` version 1: accepted order/provision terms, normalized required attributes, lease start/end and funding expiry, plus accepted Alkahest lease bytes/condition anchor or payment receipt identity/holds/hold end. Genuine Alkahest escrow and obligation records remain separate. The scoped repository adapter lets existing delivery helpers use their coordinate keywords without reading or writing payment escrow rows.

Task 2.4 must consume these facts directly, remove remaining planner/recovery/delivery mechanism switches, and return Alkahest revalidation, attestation and claim binding to the selected entry. Payment receipt checking is entry-owned already, but common recovery still selects that gate through its old switch. Recovery retains genuine Alkahest context discovery only when no delivery row exists; no payment sentinel or adoption path remains. Task 2.5 follows after that refactor; the existing controlled example is mechanically adapted and self-driven now. Task 2.6 owns promotion to the VM fulfillment and physical-provisioning spec/architecture destinations above.

Fresh-wheel self-checks and replay setup are in [`VM seller evidence`](../../../docs/attachments/vm-seller-evidence/index.md). No live qualification or independent acceptance is claimed.

## Planning validation

- `openspec validate route-settlement-by-mechanism --strict`: passed.
- `make check-comment-hygiene`: passed on the planning checkout.
- All named test-suite files exist; implementation suites and live deployment lanes are planned, not claimed as run.

## Open Questions

None. The credits authorization boundary is decided above. Optional convention implementation is deliberately deferred, not a dependency of this plan.

## Design promotion record

Core promotions below follow local diff review and focused checks. Remaining rows are destinations for their owners, not claims of current domain behavior.

| Accepted decision | Permanent location | State |
|---|---|---|
| Core table/evidence carriers; role dispatch without a universal mechanism API or fixed actor order | `openspec/specs/market-composition/spec.md`; `architecture.md#typed-phase-boundaries`; `docs/development/ARCHITECTURE.md#composition-from-above-and-below` and `#package-and-dependency-layers` | Core promoted; domain adapters remain in sections 2–5 |
| Registration is admission/configuration, never settlement execution; supported table intersection | `openspec/specs/settlement-configuration/spec.md`; `architecture.md#registration-and-ownership` | Planned |
| Agreement-based buyer dispatch and accepted-run recovery | `openspec/specs/buyer-orchestration/spec.md`; `architecture.md#configured-mechanism-choice-and-buyer-actions` | Core promoted; concrete buyer surfaces remain in sections 2–4 |
| Domain-owned evidence/progress, common delivery and stage-owned continuation | `openspec/specs/vm-storefront-fulfillment/spec.md` and `architecture.md`; `openspec/specs/physical-provisioning/spec.md`; `architecture.md#signed-payment-receipt-boundary` | Planned |
| Storefront settlement authority, neutral credits authorization, exact-once grants and separate issuance evidence/private results | `openspec/specs/api-credits/spec.md`; `architecture.md#authority-boundaries`, `#idempotency-boundaries`, `#payment-composition-and-recovery` | Planned |
| Optional convention lives in a kit, home deferred; no mandatory adoption | `openspec/specs/market-composition/architecture.md#settlement-runtime-composition`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership` | Planned; adapter implementation deferred |
| No compatibility migration for this evidence/grant cutover | Domain evidence requirements in the three capability specs above; reset instructions in their architecture companions | Planned |
| Goal 6 dispatch/evidence gap closes, carrier/wire and live-qualification gaps remain | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` | Planned for completion, not planning |
