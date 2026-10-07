## Context

The payments service's cross-product decisions are recorded in `arkhai-io/arkhai-payments` (`docs/issues/scm-settlement-port.md`); its wire contract is JSON Schema in that repository (`schema/payments.schema.json`) with test vectors, so this repository generates pydantic models rather than importing TypeScript.

A mandate is `{from, to, parts, deal, fee, authorities, nonce, expires}`. Parties and authorities are Arkhai account UUIDs. Each part is `once` with an asset, an amount and a hold. The transaction id is `sha256(JCS(mandate))`, so a retried approval converges on one transaction and one receipt. The receipt is Ed25519-signed with `kit/identity` framing (`arkhai.payments.receipt.v1`).

## Decisions

### Pipeline, not a shared escrow interface

Each stage consumes its predecessor's output and owns the translation into its own form. The listing is opaque to core except for its slots and which kit fills each, so buyers and registries can filter by kit, and registries may restrict kits. Behavior is discriminated dispatch on the mechanism identifier, which the registration surface in `kit/settlement-runtime` already provides.

Rejected: a mechanism-neutral signal vocabulary (start/stop/reverse or collect/reclaim) in core. Nothing but the mechanism reads it, and each domain needs explicit compatibility with each mechanism anyway.

### The agreement is the negotiation stage's output

On acceptance the seller emits one agreement object holding only the accepted terms, since terms are the only output negotiation exposes; there is no universal meaning to a transcript. Both sides keep the exact bytes from the accept response and neither rebuilds it, so serialization differences cannot produce two hashes. A sketch for the current runtime:

```text
Agreement = {
  negotiation_id, listing_id, listing_hash,
  buyer, seller: Identity,
  settlement: {option_id, mechanism, asset, rates, params},   # the settle stage's section, carried unread
  settlement_params: <buyer mechanism inputs>,
  amount, asset, duration_seconds, start_utc,   # start is explicit; "now" is resolved at acceptance
  provision_terms: <domain wire>,
  accepted_at,
}
```

### The settle stage defines the deal hash

`arkhai.payments.v1` commits to `sha256(JCS(agreement))` (RFC 8785; the Python side uses `rfc8785`). `derive_settlement_option_id`'s `json.dumps(sort_keys=True)` is not JCS and is not reused for it.

### The seller derives the mandate; the buyer confirms

The payments service never parses the agreement, so the two can evolve independently. The seller's kit derives the mandate and returns it with the agreement in the accept response:
- `from`: the buyer's Arkhai account, which the buyer supplies as `payer_account` in its `SettlementSelection.params` and the Agreement carries as `settlement_params`; `to`: the payee account in the option params. Core treats both params maps as opaque.
- one `once` part: the agreed amount in the option's asset (payments notation, e.g. `USD/2`), held for `start_utc − accepted_at + duration_seconds + window`. The window is declared in the option params, so buyers see it before negotiating, and it absorbs a late provisioning start.
- `fee`: the service's published fee policy.
- `authorities`: the kit's defaults. `start` and `stop` list buyer and seller; `reverse` lists the seller and Arkhai's dispute authority, which the service requires. The buyer is never a `reverse` authority, since that would let it claw back earned funds and defeat the hold. The wire keeps every list explicit; defaults live in the kit, not the service.
- `nonce`: fixed, since `negotiation_id` already makes each agreement unique.

The transaction id is `sha256(JCS(mandate))`, so both sides know it before approval. The buyer's kit checks the mandate against the agreement and its own policy (payee, amount, hold, `deal`) and approves it, attaching the agreement. Both sides poll `GET /transactions/{id}`; the seller provisions once the receipt matches. A push hook from the payments service is expected to replace polling (see Resolved Questions).

For bare-metal, the buyer calls seller settlement with only the negotiation ID. The seller derives the deterministic transaction ID from the accepted mandate and polls the payments service. Acceptance stores the mandate in shared opaque `negotiation_threads.settlement_data` beside exact `agreement_bytes`; receipt verification records domain-owned transaction/receipt evidence as `settlement_verified`. This is a domain-owned evidence record, not an escrow row or `SettlementPlan`. Fulfillment resolves the same record by negotiation ID and still uses the accepted selected-site binding before any provisioning effect. *Superseded in part by [R6](#r6-bare-metal-payment-settlement-starts-fulfillment): payment settlement now starts fulfillment itself rather than waiting for a separate buyer `begin` call.*

All three domains use that shared mandate location and return it through negotiation responses and `NegotiationOutcome`. VM uses the same negotiation-scoped mandate and signed-receipt evidence. Its existing local `escrows` table stores only physical provisioning progress under the negotiation ID for payments, with no chain/address, plan, or obligation. The foreground task and recovery sweeper share the existing convergence lease and durable physical fulfillment ID; recovery rechecks the stored receipt against the exact accepted Agreement before any physical effect. The VM buyer's Arkhai account is `[vms].payer_account`, not its marketplace signer or a payments-service configuration field.

Agreement timestamps may contain fractional seconds. Mandate derivation preserves the Agreement bytes/hash, rounds the acceptance-to-start interval up for the whole-second hold, and rounds approval expiry down. Domain adapters do not rewrite accepted timestamps.

### Depositing the agreement

*Refined by [R5](#r5-agreement-attachment-is-two-owned-policies): the buyer's attachment is its own `attach_agreement` policy, off by default, and the seller deposits before delivery.*

Approval may carry the agreement as an attachment, which the service checks against `deal` and keeps for disputes. If the seller's kit is set to deposit and the snapshot shows no agreement, it attaches it itself. The listing option declares the setting, so buyers can see it and filter on it: it gives the deal Arkhai's dispute fast path, which sellers without a reputation can advertise. Any party could deposit on its own, so a buyer's protection is this transparency, not a veto.

### Stateless kit

Shared typed registration, configuration, and owner-scoped client provision live in `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`. A selected outcome without an escrow proposal enters the domain's `agreement_settlement` stage through `make_settle_hook`. Buyer seller-settle requests contain only negotiation ID; pending receipts return retryable pending, completed calls are idempotent, and nonterminal physical or issuance progress is re-driven under the same durable identity.

Every call goes to the payments service: approve and attach (buyer), poll and attach (seller), `reverse` (seller refund; see [R7](#r7-refunds-are-seller-initiated)). Headless callers authenticate with WorkOS user-scoped API keys for their owner's Arkhai account. Hold release and fee collection happen in the service.

The kit also exports a typed `MechanismRegistration` for publication inputs and
public option filtering. Its client factory, accepted-obligation builder, and
settlement verifier remain unset; compositions use the registration without routing
payments transactions through the conditional-escrow lifecycle engine.

## Review-round decisions

A merge-readiness review found that the three domains had each grown their own copy of the payments mechanism and that the copies had drifted. The drift was concrete:

- the canonical typed client could not send the payment settle request;
- bare metal returned retryable 503 for a receipt that did not prove the Agreement;
- the acceptance artifact had three wire shapes (VM `{mandate}`, bare metal the bare mandate, API credits `{mandate, transaction_id}`);
- pending had three spellings (`pending`, `settlement_pending`, HTTP 202 `provisioning`), and "unavailable" was 503 in two domains and 502 in the third;
- buyer verification strictness differed, with only API credits checking the seller's transaction ID and the advertised option;
- no permanent test exercised the payment path through the typed client.

The decisions below were accepted in design review. Where they conflict with earlier sections, these govern.

### R1. Agreement settlement through the typed storefront client

`StorefrontClient` and `SyncStorefrontClient` gain `settle_agreement(negotiation_id)`, which sends only the negotiation ID and the signer's principal. The EVM method is renamed `settle_evm` so EVM arguments never appear on the agreement path. Both keep the wire path `/api/v1/settle/{id}` and the signed operation `settle_escrow`; the storefront dispatches on the accepted Agreement's mechanism. A sync/async parity test covers the client's public methods.

Production buyers have never used `StorefrontClient`; `core_buyer` has its own signed-JSON helpers for negotiation and Alkahest settlement too. The defect in scope is that the canonical client could not express the request, so no integration or system test could exercise the route. The VM and bare-metal payment transports and `core_buyer.submit_settlement_request` stay; migrating buyers onto the typed client and collapsing those transports belongs to `buyers-use-the-storefront-client`.

Rejected: a typed request union on one `settle()` (repeats on the client a dispatch the server already makes), and optional EVM arguments (blurs two contracts).

### R2. Receipt outcomes are typed

The kit's seller receipt check returns one of four outcomes, and each domain maps them identically:

| Outcome | Meaning | Response | State |
|---|---|---|---|
| `Pending` | The service has no transaction for the mandate yet | 202, `status: "pending"`, `retryable: true` | None |
| `Verified` | Signature, issuer, transaction, deal, from and to all match | Continue to deposit and delivery | Receipt recorded |
| `Invalid` | A receipt exists but does not prove the Agreement | 409, non-retryable, logged as an error | **None persisted** |
| `Unavailable` | The service cannot be reached or answers outside its contract | 503, `retryable: true` | None |

An invalid receipt is never the buyer's fault: the transaction ID is the hash of a mandate the seller derived, and the buyer cannot produce a different signed receipt under it. It means a stale seller trust pin, a service fault, or tampering. Persisting nothing lets the same deal recover once an operator fixes the pin.

Incomplete seller payment configuration (no fee policy, dispute authority, or service identity) fails registration preflight and startup rather than surfacing per request. The seller makes one `GET /transactions/{id}` per settle request and does not poll inside it; the buyer's settle retries are the polling loop.

Rejected: 400 for an invalid receipt (blames the buyer), 502 (commonly retried by clients), and continuing to infer outcomes from `ValueError` versus other exceptions.

### R3. Payment test levels and the vector-pinned receipt fixture

- **Kit unit:**
  - mandate derivation (hold rounding, approval expiry, authorities, nonce, fee);
  - per-field tamper rejection in `check`;
  - receipt verification (scheme, issuer, signature, deal, from and to);
  - client response handling against `httpx.MockTransport` (not-found as pending, API errors, protocol errors, redirects, attachment);
  - outcome classification, buyer approval, reversal, and the `PaymentSettlementData` model;
  - the receipt fixture's byte-exact reproduction of the published vector.
- **Storefront integration:** VM through `StorefrontClient.settle_agreement` and `refund_settlement` over `ASGITransport`, with the real app, SQLite and DI, replacing only the payments-client provider at `PaymentsClient`. Cases: pending then verified, an impostor-signed receipt, a receipt for another mandate, unavailable, idempotent repeat, refund, and the `refund` failure action. Bare metal and API credits each prove one happy path and one invalid receipt.
- **System:** one API-credit payment scenario covering publication, discovery, negotiation, approval, receipt-gated issuance, status, recovery, and a seller refund stage. It is readiness-gated: it reports blocked, never mocked, when no payments target is reachable. VM and bare-metal payment variants remain live-qualification gaps.

No test can build a receipt over its own Agreement without signing it. The published vector receipt covers a fixed three-part mandate with nonce `vector-1` and a placeholder deal, which no accepted Agreement derives. The kit therefore exposes `receipt_message(receipt)`, the bytes its verifier checks, and ships `market_arkhai_payments.fixtures.receipts` (`sign_receipt`, `build_signed_receipt`), which takes an injected signer and ships no key material. Its unit test reproduces the vector's message and signature byte for byte. This was checked against the current kit: message, issuer, and signature all match. `kit/identity` exposes its field framing as a public function so the payments kit stops importing `market_identity.canonical._frame`; that step runs after the merge ([P1](#p1-the-identity-framing-function-goes-public-after-the-merge)). `domains/vms/storefront/examples/payment_smoke.py` uses the fixture. The `TESTING.md` amendment that makes this compliant is under [Accepted permanent wording](#accepted-permanent-wording).

### R4. One payments mechanism implementation

`kit/arkhai-payments` owns everything that is mechanism, not domain:

- one Agreement → `MandatePolicy` builder, replacing four copies;
- `PaymentSettlementData` `{mandate, transaction_id}`, the single acceptance wire shape;
- a seller stage that builds settlement data at acceptance, validates stored data against the exact Agreement bytes, checks receipts with the R2 outcome, re-checks stored receipts, deposits the Agreement (R5), and reverses (R7);
- a buyer approval that validates the Agreement bytes, the seller's settlement data including its transaction ID, and optionally the advertised option binding. It then applies the buyer's attachment policy, approves, and verifies the approval receipt and polled snapshot. API credits' stricter checks become everyone's.

Domains keep payer-account sourcing, confirmation UX, HTTP binding, delivery, journals, run logs, and recovery. API credits' payment orchestration moves from its settle controller into a domain service so the controller stays a thin binding.

The settle response carries neutral fields in every domain: `negotiation_id`, `settlement_ref` (the transaction ID), `status` with `pending` reserved, `retryable`, and `escrow_uid` equal to the negotiation ID. Domain delivery fields follow.

The kit exposes framework-free operations and outcomes; this change does not build a shared settle route service. The development branch's `kit-owned-storefront-shell` extracts the settle route set from all three domains and mounts route services, so a shared service here would be built twice.

### R5. Agreement attachment is two owned policies

The Agreement discloses both marketplace principals, the listing, amount and timing, and provision terms such as the buyer's SSH public key, requested shape, or an API key ID. Neither the published contract nor the kit offers a way to withdraw an attachment.

- **Buyer:** `attach_agreement` on the shared `[Settlement.arkhai_payments]` configuration, default `false`. When true, the buyer attaches the exact Agreement at approval. The seller role rejects `true` in preflight and composition. A separate buyer configuration model was rejected as premature.
- **Seller:** when the selected option sets `deposit_agreement` and the transaction has no Agreement attachment, the seller attaches it after recording the verified receipt and before any delivery effect. A failed deposit is `Unavailable` (503, retryable); a retry re-checks the stored receipt and repeats the idempotent deposit. Delivering first and depositing later was rejected: it needs durable background retry, and it lets a seller deliver without honoring a term the buyer may have filtered on.
- **The buyer never runs the seller's deposit.** It is only in the seller's interest.

| Buyer `attach_agreement` | Option `deposit_agreement` | Outcome |
|---|---|---|
| false | false | Nothing deposited |
| true | false | Buyer attaches at approval |
| false | true | Seller attaches after verifying the receipt, before delivery |
| true | true | Buyer attaches; the seller finds it and does nothing |

### R6. Bare-metal payment settlement starts fulfillment

After verifying, recording, and depositing, the bare-metal settlement service calls the existing idempotent fulfillment `begin` logic itself and returns the lifecycle state. The buyer's payment flow drops its `begin` call, retries `settle` while pending, and then polls the existing fulfillment status route.

On this tree the `POST /api/v1/fulfillments/begin` route remains for the bare-metal Alkahest path. The development branch removes it and starts Alkahest fulfillment from the obligation servicing worker. Payment deals have no obligation, so they must not depend on either.

All three domains now verify and deliver in `settle`.

Rejected:
- a synthetic obligation for payments, which contradicts the no-plan, no-obligation design;
- keeping `begin` for payments only, which keeps a two-call protocol unique to one domain and fights the route's removal.

### R7. Refunds are seller-initiated

The normal deal flow never refunds. A buyer cannot reverse; that is deliberate, because otherwise a buyer could use resources and then refund itself. The buyer's recourse is a dispute through the payments service.

A seller operator refunds through `POST /api/v1/settlements/{negotiation_id}/refund`, signed by the seller principal like the existing listing refund route, using `StorefrontClient.refund_settlement(negotiation_id)` and its sync twin. The route is keyed by deal and named neutrally. The storefront dispatches on the Agreement's mechanism: `arkhai.payments.v1` is supported, and any other mechanism returns 409 because it refunds through its own path. The Alkahest listing refund is unchanged.

- It is a full reversal of still-held parts through the kit's idempotent `reverse`.
- It requires a verified receipt; otherwise it returns 409.
- It records `refunded` as a terminal settlement state, after which `settle` never starts delivery.
- A repeat returns `refunded` without a second reversal.
- An elapsed hold or collected funds return 409, "nothing left to reverse".
- It does not tear down anything already delivered; teardown stays a separate operator decision.

The kit owns the reversal operation and outcome classification. Each domain adds a thin binding and the state write.

### R8. An opt-in refund failure action covers payment deals

`[fulfillment.failure_policy].actions` keeps one `refund` action, meaning "refund the buyer when my own fulfillment fails". It is opt-in and off by default, as for Alkahest. The handler dispatches on the deal's Agreement: Alkahest keeps its existing token refund, and `arkhai.payments.v1` uses the R7 reversal and `refunded` state.

- For payment deals it fires only when the deal never reached a delivered state. A refund after delivery stays an operator decision.
- A failed reverse leaves the deal `failed` with the action's recorded failure. The idempotent operator route is the backstop; failure actions have no retry machinery.
- VM's existing handler gains the payments branch, which fixes its current silent skip (`buyer_evm_address_unknown`) on payment deals.
- API credits' policy gains a `refund` handler.
- Bare metal has no failure policy; see merge item M5.

### R9. Snapshot proofs are not trusted evidence

`SignedTransactionSnapshot` carries a service proof that SCM does not verify. Sellers rely only on the independently signed receipt embedded in it, which suffices for `once` parts, whose gating reads only transaction, deal, from and to. Test fakes may give snapshots a placeholder proof. Any change that reads snapshot part state as evidence must first add snapshot verification, a snapshot vector, and a fixture. `spot-deals-through-arkhai-payments` is the first such change.

### R10. Documentation corrections

- `proposal.md` describes the accepted scope; escrow-into-Alkahest is a non-goal.
- `core/src/market_core/schemas.py` stops describing `SettlementPlan` and `SettlementObligation` fields as universals, and drops "work item I.1 / I.3" and the nonexistent "Settlement Lifecycle" section reference. Those carriers belong to mechanisms using the obligation runtime; Agreement-only mechanisms bypass them. The `SettlementSelection.params` comment uses a neutral example instead of naming Arkhai payments.
- The change's delta specs still assert deferred §1 behavior (for example, that core MUST NOT define `claimant` and that `ConditionalEscrowClient` MUST NOT be shared), while the permanent specs correctly do not. Deltas are reconciled once, at closeout, against the final permanent text after the merge:
  - remove the deferred §1 statements;
  - add deltas for R1–R9;
  - address the seven >500-character warnings that current `@latest` strict validation reports.

  Reconciling now would churn the deltas twice.

## Accepted permanent wording

Exact text for promotion at closeout. Destinations are listed in [Planned promotion](#planned-promotion).

### `docs/development/TESTING.md`

**Marketplace Identity Verification**, the secret-canary bullet, becomes:

```markdown
- Configuration and artifact tests use secret canaries to reject private
  material in public models, persistence, logs, rendered ConfigMaps,
  arguments, images, wheels, manifests, and fixtures. Payment tests use the
  installed payments kit's generated wire models and never import the
  payments service implementation. "Payment Receipts in Tests" below covers
  how they obtain signed receipts.
```

**A new section after "Marketplace Identity Verification":**

````markdown
## Payment Receipts in Tests

A seller delivers only after verifying a receipt that the payments service
signed for the exact mandate derived from the accepted Agreement. Proving that
gate below the system level needs a receipt for each test's own Agreement. The
published vectors cannot supply one: their receipt covers a fixed vector
mandate that no accepted Agreement derives.

Tests get receipts from the payments kit's fixture:

```python
receipt = build_signed_receipt(signer=SERVICE, mandate=accepted.mandate)
```

Tests and diagnostics never frame or sign a receipt themselves. Code like this
is a second framing implementation that nothing checks against the service:

```python
signature = service.sign(_frame(("arkhai.payments.receipt.v1", jcs_sha256(receipt))))
```

The fixture is trustworthy because it uses the same framing function as the
kit's verifier, and the kit's unit suite proves it reproduces the published
vector exactly:

```python
assert receipt_message(vector_body).hex() == vectors["receipt"]["message"]
assert sign_receipt(Ed25519Signer(vector_seed), vector_body) == vector_receipt
```

The fixture takes its signer as an argument and ships no key material.
Integration tests replace `PaymentsClient`, the code that wraps the payments
HTTP boundary, with a fake that serves fixture receipts. Each test varies one
property:

```python
payments.serve(build_signed_receipt(signer=SERVICE, mandate=accepted.mandate))   # delivers
payments.serve(build_signed_receipt(signer=IMPOSTOR, mandate=accepted.mandate))  # 409, no delivery
payments.serve(None)                                                              # 202 pending
```

A fake may give the surrounding transaction snapshot a placeholder proof,
because sellers trust only the embedded receipt. A change that makes snapshot
state authoritative must first add a snapshot vector and fixture.
````

**Contract Fixtures**, appended to "When to add one":

````markdown
An external service that publishes conformance vectors is the exception.
The vectors stand in for the producer's own tests, so the consuming kit
may own a `build_*()` fixture in its `src/<package_name>/fixtures/` as
long as its unit suite proves the fixture reproduces the vectors:

```python
assert sign_receipt(vector_signer, vector_body) == vector_receipt
```

Such a fixture needs no `validate_*()`, because the vectors already are
what the producer emits. "Payment Receipts in Tests" is the current
instance. Without published vectors, an external service's shape stays a
local inline value.
````

### `openspec/specs/settlement-servicing/spec.md`

In "Arkhai payments settles charge-first from an agreement", replace the sentences "Approval MAY attach the Agreement for dispute handling. If the seller option enables agreement deposit and the transaction snapshot has no Agreement, the seller kit MUST attach it." with:

```markdown
The buyer MUST attach the exact Agreement at approval only when its
`attach_agreement` policy is enabled, which it is not by default, and MUST NOT
perform the seller's deposit. If the selected option sets `deposit_agreement`
and the transaction has no Agreement attachment, the seller MUST attach it
after verifying the receipt and before any delivery effect. A failed deposit
is retryable and blocks delivery.
```

Replace the scenarios "Buyer approves with an optional Agreement attachment" and "Seller reverses a held payment" with:

```markdown
#### Scenario: Buyer attaches only by its own policy

- **WHEN** the buyer approves a mandate with `attach_agreement` disabled
- **THEN** the approval carries no attachment, whatever the selected option's
  `deposit_agreement` setting

#### Scenario: Seller deposits before delivering

- **WHEN** the selected option sets `deposit_agreement` and the verified
  transaction has no Agreement attachment
- **THEN** the seller attaches the exact Agreement before any delivery effect,
  and a deposit failure returns retryable unavailable without delivery

#### Scenario: Seller operator refunds a held payment

- **WHEN** a seller-authenticated refund request names an accepted payment deal
  with a verified receipt and still-held funds
- **THEN** the storefront requests `reverse` for that transaction once, records the
  deal refunded so delivery cannot start, and repeats return the same result

#### Scenario: Only the seller initiates a refund

- **WHEN** delivery fails or a buyer requests settlement after any outcome
- **THEN** no storefront issues `reverse` unless a seller-authenticated refund
  request names the deal, or the seller has enabled the `refund` failure action
  and the deal failed before any delivery; the buyer's recourse is a dispute
  through the payments service
```

The receipt-outcome classification (R2), the neutral settle response fields (R4), bare-metal settle-starts-delivery (R6), and the refund route (R7) are written as requirements in the same capability during implementation, following the decisions above.

## Planning findings

Found while naming files for the review-round plan. Each refines how a decision is carried out; none reopens one.

### P1. The identity framing function goes public after the merge

Exposing framing publicly is new API on `arkhai-kit-identity`, which needs a version bump. About fifteen packages here and twenty-five on the development branch pin it exactly (`==0.3.0`), so bumping now means repinning and relocking every one of them, then repeating that in the merge. Until the merge, `receipt_message` in the payments kit remains the single framing implementation that both the verifier and the receipt fixture call, still importing `_frame`; R3's test rule holds without the identity change. After the merge, `frame_fields` becomes public, the identity kit is bumped once, and every pin moves in one step.

### P2. Packaging is gated on "no new failures" until the merge

`make check-packaging` and its four checks were copied unchanged from the development branch. On this tree they report 191 failures before any change of this one (1 Python-version, 23 layout, 131 uv-setup, 36 lock), because they encode the development branch's packaging convergence, which this branch predates. Resolving them here would duplicate that work and conflict at the merge. The accepted gate before the merge is that the checks report nothing beyond a baseline captured from the unmodified tree and that every lock this change touches is current; §6.3 requires a clean `make check-packaging` on the merged tree.

### P3. Bare-metal settlement records gain `refunded` in place

`bare_metal_settlement_records.status` has `CHECK (status IN ('accepted', 'settlement_verified'))`, which SQLite cannot alter. The table is new on this unmerged branch. Following task 4.0's precedent, migration `bare-metal-storefront-0008-settlement-records` is edited in place to admit `refunded` rather than adding a rebuild migration that would also need renumbering over the development branch's chain. VM and API credits record `refunded` in the unconstrained `escrows.status`.

### P4. The kit takes an injected client factory

The kit's seller stage and buyer approval take a `client_for_owner` callable, defaulting to `payments_client_for_owner(config, owner)`. Integration tests replace it with a fake `PaymentsClient`, which is the code that wraps the payments boundary. The fake ships beside the receipt fixture as `market_arkhai_payments.fixtures.payments_client` so the kit and all three storefront suites share one fake.

### P5. A refund re-checks the receipt itself

API credits verifies each receipt on demand and stores none, so a refund cannot rely on a stored receipt. The kit's reversal therefore checks the current receipt first. It needs `Verified`, otherwise it returns not-paid (409) or unavailable (503); then it calls `reverse`. Payments-service codes map exactly:

- `transaction_not_found` → not paid, 409;
- `hold_matured`, `hold_not_reversible`, `insufficient_held_funds` → nothing left to reverse, 409;
- transport, protocol and every other code → unavailable, 503.

The same mapping serves the `refund` failure action.

### P6. `refunded` is never overwritten

The R8 failure action can record `refunded` while a domain's own failure path is about to record `failed` (VM's payment coordinator after a not-fulfilled result; API credits' issuance failure). Those writes become conditional on the current status not being `refunded`, and `settle` checks `refunded` before checking the receipt.

## Implementation findings

Found while implementing §5; each is a correction within an accepted decision.

- **API credits refunded automatically on issuance failure.** Its payment path called `reverse` whenever issuance definitely failed, an automatic refund in the normal flow that R7 and R8 exclude. That call is removed; refunding a failed issuance happens only through the opt-in `refund` failure action.
- **API-credit seller authentication failed on empty-body requests.** It parsed every POST body as JSON, so the refund route and the existing `close_listing` route returned 500 through the typed client, which sends no bytes for an empty body. An empty body now authenticates as the empty-body hash.
- **Version bumps reach exact pins outside `pyproject.toml`.** The storefront Dockerfiles install their own wheel by exact version, and the VM storefront pins the bare-metal storefront exactly, so the bumps cascaded into Dockerfiles, two READMEs, and the bare-metal storefront version.

## Merge with the development branch

This change lands after `bare-metal-mock-provisioned-deal` on the development branch, whose tree has moved since this change branched. The merge will be resolved from a conflicted snapshot. These are the decisions it raises that are already known:

- **M1. Hosted Stripe removal versus continued hosted work.** The development branch archived `bind-one-hosted-release-coordinate`, `carry-the-payer-return-address`, and `resolve-hosted-client-from-an-index`, which this change lists as superseded. It also added `core_buyer/hosted_settlement.py`, a hosted release workflow, and hosted compose files. Decide whether the §3.2 removal still holds, and how the superseded list and those archives are recorded.
- **M2. Agreement versus the development negotiation runtime.** The development branch has no `Agreement`, and bare metal composes onto `kit/negotiation-runtime` there (`bare-metal-mock-provisioned-deal` §6). This change's §2 Agreement and settlement-data work must be re-applied to that runtime.
- **M3. Settle surface.**
  - The development client already dropped `ssh_public_key` and `chain_name` from `settle`, so the R1 rename applies to that narrower signature.
  - Admin settle verify, evaluate, and wait are kit route services there.
  - Its permanent `ARCHITECTURE.md` five-piece route rule applies to `settle_agreement` and `refund_settlement`, including whether mechanism-specific client methods belong in kit client extensions over `authenticated_request`.
  - `kit-owned-storefront-shell` will extract the settle and refund bindings.
- **M4. Restart re-drive for payment deals.** `kit-owned-listing-and-fulfillment-lifecycles` frames convergence as obligation resumption; payment deals have no obligation, so it must also resume from domain receipt evidence. VM's partial resume shows the gap.
- **M5. Bare-metal failure policy.** Development-branch §7 reworks bare-metal failure and teardown. The R8 `refund` action reaches bare metal once a failure policy exists there.
- **M6. Bare-metal fulfillment trigger.** Development-branch §7.1 removes `begin` and starts Alkahest fulfillment from the obligation servicing worker. R6 keeps payments independent of both. Verify after the merge that the settle-starts-fulfillment path survives intact.
- **M7. Permanent documents.** `TESTING.md`, `ARCHITECTURE.md`, `ROADMAP.md`, and the specs have diverged; this change's sections are re-applied over the development text. The registry package moved from `core/registry/src/` to `core/registry/src/core_registry/`.

## Planned promotion

| Decision | Planned permanent location |
|---|---|
| R1 agreement settlement client methods and parity | `openspec/specs/buyer-orchestration/spec.md#requirement-payment-buyers-preserve-accepted-state`; `docs/development/TESTING.md` sync/async parity rule (already present) |
| R2 receipt outcomes and status mapping | `openspec/specs/settlement-servicing/spec.md#requirement-negotiation-scoped-payment-settlement-converges` |
| R3 vector-pinned receipt fixture and payment test levels | `docs/development/TESTING.md` (wording above); `openspec/specs/test-compatibility/spec.md#requirement-payment-evidence-is-attributed-at-its-owning-boundary` |
| R4 kit-owned mechanism, single settlement-data shape, neutral settle fields | `openspec/specs/settlement-servicing/spec.md` and companion `architecture.md#charge-first-payment-settlement`; `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-registers-as-a-peer-settlement-mechanism` |
| R5 attachment policies | `openspec/specs/settlement-servicing/spec.md#requirement-arkhai-payments-settles-charge-first-from-an-agreement` (wording above); `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials`; `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover` |
| R6 bare-metal settle starts fulfillment | `openspec/specs/physical-provisioning/spec.md#requirement-signed-payment-receipts-gate-selected-site-execution` |
| R7 seller-initiated refunds | `openspec/specs/settlement-servicing/spec.md` (wording above) |
| R8 mechanism-dispatched refund failure action | `openspec/specs/settlement-servicing/spec.md`; `openspec/specs/settlement-configuration/spec.md` |
| R9 snapshot proofs not trusted | `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement` (current limitation) |
| R10 core carrier description | `core/src/market_core/schemas.py` docstrings, consistent with `openspec/specs/settlement-servicing/spec.md#requirement-mechanism-neutral-plan-carrier` |

These rows move into the design promotion record as each promotion lands.

## Superseded changes

Built on `fiat.stripe.v1` and `kit/hosted-settlement`: `consume-expanded-stripe-funding`, `add-api-credits-hosted-settlement`, `add-bare-metal-hosted-settlement`, `bind-one-hosted-release-coordinate`, `carry-the-payer-return-address`, `project-an-authoritative-funding-loss`, and the hosted sections of `disburse-a-settlement-disposition`. The old service never ran with production money, so nothing deployed needs migration. Archive or withdraw them when this change is accepted.

## Deferred

- **Identity slot.** `kit/identity` already dispatches by scheme, but the listing carries one `seller_principal`. Revisit when a listing needs to advertise several identity schemes.
- **Negotiation slot.** `kit/negotiation-runtime` builds in one protocol (counter/accept/exit, an amount, `AgreementTerms`). Revisit when a second negotiation protocol arrives, e.g. auctions.
- **Per-stage kit declarations** (which predecessor outputs a stage accepts, for filtering). Revisit with the negotiation slot.
- **Escrow carriers into Alkahest** (§1). Unowned follow-up in the roadmap; see Resolved Questions.
- **Buyer calls through `StorefrontClient`.** `core_buyer`'s signed-JSON helpers and the VM and bare-metal payment transports stay; migrating them, and collapsing the transports, is owned by `buyers-use-the-storefront-client` ([R1](#r1-agreement-settlement-through-the-typed-storefront-client)).
- **Seller-side restart re-drive for payment deals.** Payment deals re-drive on buyer settle retries. Resuming them without a buyer belongs to the development branch's fulfillment-convergence extraction ([merge item M4](#merge-with-the-development-branch)).
- **Partial reversal and automatic refund after delivery** ([R7](#r7-refunds-are-seller-initiated), [R8](#r8-an-opt-in-refund-failure-action-covers-payment-deals)).
- **Bare-metal failure policy.** Bare metal has none; the `refund` failure action reaches it after the merge ([M5](#merge-with-the-development-branch)).
- **Verifying transaction snapshot proofs** ([R9](#r9-snapshot-proofs-are-not-trusted-evidence)), required by `spot-deals-through-arkhai-payments`.

## Resolved Questions

- §1 is deferred: existing `SettlementObligation` claimant, expiration, and condition fields and the shared conditional-escrow runtime remain. Moving those carriers and listing fields into Alkahest is not implemented or promoted. The Agreement carries canonical parties; the Arkhai mandate's `to` comes from its payment option, and its path does not construct an obligation.
- `kit/settlement-runtime` stays where it is for now: Alkahest, contact exchange, core and the domains all use it. Arkhai payments keeps no client-side servicing state and bypasses it, producing no settlement plan or obligation; moving escrow semantics out of core is a follow-up change.
- Both kits poll the payments service by transaction ID; the storefront relays nothing. A push hook from the payments service is tracked as an idea in arkhai-payments (`transaction-webhooks`) and is expected to replace polling.
- The SDK's default window is `P7D`. The payments service enforces no minimum; chargeback exposure is covered by its cash reserve.

## Closeout disposition

Permanent specifications are edited directly for implemented §2–§3 behavior. The change remains active for verification; it is not archived. Strict validation passed after delta scenario headings were aligned with the promoted contract; current `@fission-ai/openspec@latest` additionally reports seven >500-character requirement warnings, which fail `--strict` (see [R10](#r10-documentation-corrections)). Archive preview reports already-promoted ADDED requirements; eventual archival must skip spec updates rather than replay the delta over these permanent edits. §1 delta statements that remove core escrow fields, move the shared port into Alkahest, or remove legacy Alkahest listing carriers remain deferred and are not synchronized as current guarantees.

The hosted-document cleanup includes all 18 destinations named in §3.2, plus their adjacent servicing, publication, marketplace-identity, physical-provisioning, and API-credit contracts and repository testing/deployment guides. Historical hosted changes remain in `openspec/changes`; rejected legacy config names and forbidden-import assertions deliberately remain. No Stripe profile, credential, authorization, or operation is mapped to Arkhai payments.

Implementation evidence retained from §3: Stripe removal commits `aa97accd` and `c39090ea` preserved Alkahest/contact coverage, with 2,251 regressions (one skipped), 42-source typing, wheels/CLI/Helm checks. VM fractional-time derivation and restored admin diagnostics were separate repairs. VM controlled HTTP/payment/delivery smoke observed pending → provisioning → ready with one delivery; it is not live-ledger or hardware evidence. Bare-metal ran no payment-service smoke. API-credit E2E was unavailable because the local payments service was down. Global integration, deployment, and typing qualification remains §4.1-owned.

Verification closeout compared the accepted decisions with promotion `e97b4b7a`; `docs/attachments/settle-through-arkhai-payments/decision-review.md` records the comparison. Small normative wording corrections remain in `negotiation-protocol/spec.md#requirement-deterministic-agreed-terms` and `api-credits/spec.md#requirement-idempotent-credit-issuance` / `#requirement-verified-settlement-fulfillment`. SCM #254 reconciles API-credit configuration with the shared-kit rule: buyer/storefront roots use the kit registration, owner-scoped client helper and api_key_env policy. The buyer account is [apicredits].payer_account; each seller request uses the accepted option's payee account and closes its client. Shared publication preserves hourly major-unit scaling and accepts generic integer-base-unit prices per unit. API credits alone maps credit/token/request onto that surface; the kit owns no domain-unit vocabulary. No compatibility shim is needed on this unmerged branch. The local diagnostic uses development_auth, not a domain-local development account. Local development evidence does not establish production WorkOS authentication.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Negotiate → settle → provision; core defines only shared-reader carriers, not one escrow adapter API. | `docs/development/ARCHITECTURE.md#composition-from-above-and-below`; `openspec/specs/market-composition/spec.md#requirement-deals-compose-negotiate-settle-and-provision-stages` and companion `architecture.md#typed-phase-boundaries` |
| Acceptance fixes exact Agreement bytes and explicit start; core does not define a universal deal hash. | `openspec/specs/negotiation-protocol/spec.md#requirement-deterministic-agreed-terms`; `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| Buyer supplies payer_account in selection params and Agreement settlement_params, separately from marketplace identity and trusted service policy; VM uses [vms].payer_account; API credits uses [apicredits].payer_account and the accepted option selects the seller client owner. | `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials`; `openspec/specs/marketplace-identity/spec.md` |
| All domains return and persist the seller-derived mandate in shared opaque settlement_data beside agreement_bytes in negotiation_threads. | `openspec/specs/negotiation-protocol/spec.md#requirement-acceptance-persists-opaque-settlement-data`; `openspec/specs/settlement-servicing/spec.md#requirement-negotiation-scoped-payment-settlement-converges` |
| make_settle_hook sends selected outcomes without escrow proposals to the domain agreement_settlement stage. | `openspec/specs/market-composition/spec.md#requirement-buyer-dispatch-preserves-agreement-only-settlement`; companion `architecture.md#agreement-based-payment-composition` |
| JCS deal/transaction hashes, declared hold window, fixed nonce, fee/reverse policy, Agreement deposit, and fractional-time rounding. | `openspec/specs/settlement-servicing/spec.md#requirement-arkhai-payments-settles-charge-first-from-an-agreement`; companion `architecture.md#charge-first-payment-settlement` |
| Buyer approves and polls; seller settle accepts only negotiation ID, polls the same transaction, verifies the signed receipt, returns retryable pending, and re-drives nonterminal progress idempotently. | `openspec/specs/buyer-orchestration/spec.md#requirement-payment-buyers-preserve-accepted-state`; `openspec/specs/settlement-servicing/spec.md#requirement-negotiation-scoped-payment-settlement-converges` |
| VM and bare-metal receipt evidence gates selected-site fulfillment and recovery; VM provisioning progress is not a chain escrow or obligation. | `openspec/specs/physical-provisioning/spec.md#requirement-signed-payment-receipts-gate-selected-site-execution` and companion `architecture.md#signed-payment-receipt-boundary`; `docs/development/ARCHITECTURE.md#fulfillment` |
| API-credit receipt verification precedes authority-owned exact-once grants and private credential delivery; uncertain issuance is recoverable. | `openspec/specs/api-credits/spec.md#requirement-payment-grants-are-principal-bound-and-exact-once` and companion `architecture.md#payment-composition-and-recovery` |
| Shared registration/config/client provider lives in payments settlement_config.py; Arkhai payments is a peer of Alkahest, with no wallet requirement or conditional-escrow hooks. | `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials` and companion `architecture.md#registration-and-ownership`; `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-registers-as-a-peer-settlement-mechanism` |
| External payments authority owns ledger, holds, fees, disputes, cash movement, and provider state; stateless generated-model kit uses owner-scoped WorkOS credentials and identity-framed Ed25519 receipts. | `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-authority-remains-external`; `openspec/specs/deployment-state/spec.md` and companion `architecture.md#arkhai-payment-consumers`; `docs/development/ARCHITECTURE.md#authority-boundaries` |
| Stripe mechanism/client, funding/setup/recovery surfaces, and hosted release/profile matrix are not current behavior; legacy settings are rejected, not converted. | `openspec/specs/settlement-configuration/spec.md#requirement-settlement-configuration-selects-explicit-peer-mechanisms`; `openspec/specs/storefront-publication/spec.md#requirement-payment-publication-discloses-mandate-policy`; `openspec/specs/cli-query-language/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover` |
| Consumer tests prove SCM behavior only; live payment/provider and physical delivery claims need their actual authority. | `openspec/specs/test-compatibility/spec.md#requirement-payment-evidence-is-attributed-at-its-owning-boundary` and companion `architecture.md#payment-evidence-ownership`; `docs/development/TESTING.md#marketplace-identity-verification`; `openspec/specs/README.md#settlement-documentation-ownership` |
| Goal 6 names current peer payment composition and deferred escrow isolation; Goal 4 and qualification gaps no longer point to superseded hosted adopters. | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice`, `#goal-4--make-a-domain-a-composition-of-kit`, and `#payment-qualification-boundaries`; `openspec/changes/README.md#roadmap-goal--make-the-settlement-mechanism-a-composed-choice` |
| API-credit payment rates remain integer base units per credit/token/request; hourly rates retain asset-precision scaling. | `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection` |
| Moving escrow fields and the conditional-escrow port into Alkahest, additional listing slots, per-stage declarations, push payment notification, and rate-part (spot/interruptible) payments, which move to `spot-deals-through-arkhai-payments`. | Deferred, not promoted as implemented behavior; retained in this design and §1. Existing escrow carrier contract remains in `openspec/specs/settlement-servicing/spec.md#requirement-mechanism-neutral-plan-carrier`. |
