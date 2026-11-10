# Tasks — compute lease delivery deadlines

Design-stage plan; no implementation is claimed. All material decisions and
recommendations are in `design.md`. Renewal/lapse policy is deferred, not a task.
Package paths below describe this branch; reverify them after the pool-authority
dependency lands rather than preserving a forbidden import to fit this plan. The
activation-deadline column's name and the specification owning the enablement switch
are open in `design.md`; no task below decides them.

## 1. Dependency and contract gates

- [ ] 1.1 Verify against the landed code that activation is the single
  `activated_at_utc` written by `activate_lease` (`kit/site/src/market_site/ledger.py`),
  that both lease views expose it, and that every compute commit and recovery caller
  commits through `CapacityEffects.commit`
  (`kit/capacity-publication/src/market_capacity_publication/capacity.py`) from
  `domains/compute/delivery/src/compute_delivery/path.py`. Verify
  `inject-site-pool-authority` has landed its session-scoped pool-facts port. Add the
  resolved delivery deadline through that port; do not import the pool authority into
  `kit/site`. Reconfirm provider declaration ownership and any relocated pool package
  paths with the landed implementation.
- [ ] 1.2 Before event integration, confirm the landed signed `lease_ended` record and
  durable outbox admit `activation_deadline_lapsed` as a cause without a contract
  change. Do not implement a second event format, end service or site-triggered refund.
- [ ] 1.3 Coordinate the service migration order with
  `capacity-reservation-lifecycle-hardening`; select a separate leased-deadline
  query/index, rather than extending its reserved-hold expiry index. This change ships
  the explicit compute composition setting `activation_deadlines_enabled` false and owns
  the post-qualification repository composition-default edit, after storefront-first,
  site-off rollout and explicitly enabled owned-lane drives of every wired caller
  (section 4). Hosted operators independently confirm readiness; public records never
  include hosted identifiers.

## 2. Delivery-deadline declaration and validation

- [ ] 2.1 Extend `kit/resource-pools-contracts/src/market_resource_pools_contracts/hints.py`
  with the positive-integer `delivery_deadline_seconds` tag and strict parsing.
  Extend pool write validation in `kit/resource-pools` (or its landed owner) so
  create/replace/patch/import and validate-only use the same provider support rule.
  Missing means provider default; null/zero/malformed values do not disable it.
- [ ] 2.2 Pass provider delivery-deadline declarations as plain data from the compute
  composition in `provisioning/compute/service/src/compute_provisioning_service/container.py`;
  set recommended VM/bare-metal defaults of 1800/7200 seconds and state them in
  `provisioning/compute/service/src/compute_provisioning_service/seed/pools.yaml`.
  Keep the API-credits composition's provider declaration empty. Existing pool
  rows need no data backfill; their absent overrides resolve the provider default.
  Add/configure `activation_deadlines_enabled` false in the compute composition;
  effective pool facts resolve no delivery deadline while off without disabling support or
  validation. Snapshot only new commits when enabled; turning it off never clears
  an existing deadline. Document deployment and caller qualification ownership.
- [ ] 2.3 Validate at the lowest meaningful level: parsing in the existing hints
  unit suite (`kit/resource-pools-contracts/tests/unit/test_hints.py`); provider
  fallback, refusal and atomic imports in
  `kit/resource-pools/tests/integration/test_resource_pool_service.py` (or its
  landed successor). Use the existing suites; any new test requires maintainer
  approval. Run each affected package's `make test` after refreshing internal wheels.

## 3. Site deadline and conditional expiry

- [ ] 3.1 Add the nullable activation-deadline column, named as the design settles, and
  its due-query index to the shared site schema in
  `kit/site/src/market_site/migrations.py`, applied by both
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py` and
  `domains/apicredits/service/src/apicredits_service/db/migrations.py`; existing rows
  stay null.
- [ ] 3.2 Extend `kit/site/src/market_site/ledger.py` commit with a typed
  `accepted_delivery_deadline_seconds` and `committed_at_utc` on the request, distinct
  from pool configuration. Inside the commit transaction: read the pool's current
  effective deadline through the pool-facts port; refuse an anchor after the site's
  clock; refuse an accepted deadline that exceeds the current policy or is supplied
  where the pool resolves none; snapshot the accepted value when permitted, or the
  pool's value when none is supplied and one resolves; require a finite end where a
  deadline is written; set the deadline from max(committed_at_utc, lease_start_utc).
  Write no phase: whether a lease is activated stays derived from `activated_at_utc`.
  Recommit preserves the originally committed deadline whatever the pool now says.
  Activation is the landed transition and is not changed.
- [ ] 3.3 Make the due query select an unactivated lease at the earlier of its deadline
  and agreed end, and an activated lease at its agreed end. Return the observed end,
  deadline, activation absence and cause to expiry. Claim all those values with
  `leased` state before release effects; stale claims write nothing. Preserve
  agreed-window overlap accounting and the release guard. Ordinary term end wins a
  tied due cause.
- [ ] 3.4 Extend the typed authority in `kit/site/src/market_site/authority.py`, the
  models in `http_models.py`, `router.py`, the site client in
  `kit/site-client/src/market_site_client/client.py` and `CapacityEffects.commit` so
  the commit request carries the typed accepted deadline and commitment instant. Use
  existing service authentication and exact response verification; request bodies carry
  no billing kind, funded-through time or replacement for the pool's policy — the
  accepted value is the deal's term, not an override.
- [ ] 3.4a Add the activation deadline to the site's reservation view and the compute
  contract's `LeaseView` beside `activated_at_utc`.
- [ ] 3.5 Run `make -C kit/site test` and `make -C kit/site-client test`. Integration
  jurisdiction is the public ledger API with a real embedded database: extend
  `kit/site/tests/integration/test_ledger.py` for the two claim orderings,
  elapsed-but-unclaimed activation, full-window admission and no-deadline behavior.
  Cover forward-start commits, switch-off new commits, enabled new commits, unchanged
  already-snapshotted deadlines, truncation before and after a due read, and the
  policy-change matrix: the pool raised after acceptance (accepted value enforced),
  lowered below the accepted value (refused), no longer enforcing one (refused), a
  commit without an accepted value taking the pool's, a future commitment instant
  refused, and a recommit after a policy change preserving the original snapshot. Use
  deterministic two-session controls, not sleeps. Migration behavior belongs in both
  hosting services' existing migration integration suites, with new tests subject to
  maintainer approval.

## 4. Watchdog, evidence, publication and first use

- [ ] 4.1 Update `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`
  and its authority calls to carry the conditional expiry claim before any provider
  effect, including direct-free and deferred-create paths. Keep provider I/O outside
  transactions and capacity held until guarded release succeeds. Extend the base
  event/outbox supplied by the foundation with the activation cause, claimed
  deadline and intended effective end instant; retries preserve the original
  evidence. It is not proven release: retain the independent guarded physical
  completion fact, including release failure.
- [ ] 4.2 Carry the accepted deadline and the commitment instant the servicing journal
  records (`kit/deal-servicing/src/market_deal_servicing/journal.py`) from the delivery
  path's commit step (`domains/compute/delivery/src/compute_delivery/path.py`) through
  `CapacityEffects.commit`, and through the shared compute contract and client
  (`provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`,
  `provisioning/compute/client/src/compute_provisioning_client/client.py`) and the
  compute service's lease controller and composition, offering-mode neutral; the
  activation and inspection surfaces are the landed activation's and are unchanged.
- [ ] 4.2a Prove, through the delivery path's integration suite, that the site's
  deadline never precedes the storefront journal's for the same deal, that a commit
  refused for exceeding the pool's current value is recorded as seller failure before
  dispatch, and that the existing `activation_lapse` hand-off covers a lease whose
  expiry claim won activation.
- [ ] 4.2b Publish the pool's effective `delivery_deadline_seconds` — the validated
  override or the provider's declared default — read from the site's pool projection
  (`kit/site/src/market_site/projections.py`), as the option's
  `lifecycle.delivery_deadline_seconds` in both compute storefronts' publication; a
  pool resolving none publishes no deadline. Cover a pool edit between publication and
  commit.
- [ ] 4.2c Retire the payments clause's `delivery_deadline_seconds` parameter and its
  compute-option requirement in
  `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`, with its
  configuration migration and tests, so no settlement mechanism's model owns a
  lifecycle key; the published value comes only from 4.2b.
- [ ] 4.2d Implement the re-amended `deal-lifecycle` delivery-deadline behaviour
  ("The delivery deadline is the site's availability term" and "Lifecycle terms are
  part of the selected option", as `offer-per-period-vm-terms` amends them) — from
  the seller-configured, storefront-enforced stopgap to the pool's term published by
  the storefront and enforced by the site — together with the `storefront-publication`
  and `settlement-configuration` behaviour 4.2b and 4.2c change, as this change's
  design session writes those deltas.
- [ ] 4.3 Run the compute library, contracts and client `make test` targets, focusing
  on `provisioning/compute/tests/integration/test_release.py` for real persistence
  and release orchestration. Run `make -C provisioning/compute/service test-integration`
  for service migration/API composition, and the affected storefront, delivery and
  payments-kit suites for 4.2–4.2c. Unit targets cover only value/codec rules; do not
  use mocked ledger orchestration as race evidence. Run package typing checks where
  declared. Record commands, results and any unrun checks.
- [ ] 4.4 Prepare first use through the existing site/compute typed clients with a
  mock provider, seeded finite compute pool, caller service principal and controlled
  watchdog. Commit the reproducible setup/entry point with the implementation.
  Explicitly enable the switch in the owned site-only fixture, not in deployment
  defaults; prove off leaves a null deadline. Observe a future-start commit surviving
  until max(commitment,start)+delivery_deadline_seconds and commit -> unactivated ->
  activation (including prior truncation/lost acknowledgement) -> survival past the
  delivery deadline to the current agreed end, and a separate unactivated lease ->
  claimed expiry -> guarded release. Readiness must pass before network scenarios. No
  storefront or payment service is needed for the site trace.
- [ ] 4.5 Enablement. With every caller already wired, drive each commit and recovery
  caller in explicitly enabled owned lanes (switch on in the lane fixture only), then
  change the repository's compute-composition `activation_deadlines_enabled` default in
  `provisioning/compute/service/src/compute_provisioning_service/container.py` and its
  configuration owner (reverify relocated paths). Document storefront-first, site-off
  rollout and hosted operators' independent caller-readiness gate in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- [ ] 4.6 Before pre-closeout review, check comment hygiene and touched import
  placement, fixing code here rather than at closeout. Run `make check-packaging`
  after focused behavior passes.

## 5. Closeout

Documentation-only, after code review; any required code correction returns to
implementation. Follow `openspec/README.md#plan-closeout-requirements` in this order.

- [ ] 5.1 **Comment hygiene:** run `make check-comment-hygiene` and confirm touched
  comments describe current invariants; a required edit returns to implementation.
- [ ] 5.2 **Import placement:** confirm touched imports are module-level unless a
  verified cycle or deliberate lazy-load reason keeps one local; do not fix code here.
- [ ] 5.3 **Documentation compliance:** classify D1–D5 against documentation ownership;
  do not promote D4's deferred renewal as implemented behavior or site evidence as
  payment authority. Confirm accepted recommendations match the reviewed code.
- [ ] 5.4 **Narrative compression:** retain final behavior, material evidence,
  deferred renewal and permanent destinations; remove duplicate work narratives.
- [ ] 5.5 **Roadmap currency:** update Goal 8 in `docs/development/ROADMAP.md` to name
  activation deadlines, not renewable active leases, as delivered, and the MVP's
  seller-configured deadline as retired. Record that buyer
  guarantees come from authority actions and held-money disputes. Preserve the
  deferred separate-site-operator revisit condition in the owning change history.
- [ ] 5.6 **Campaign index currency:** update this change's row and dependency graph
  in `openspec/changes/README.md`, retaining the current identifier and recording the
  deadline-only boundary; run
  `make check-change-index` and record the update in the promotion record.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=renewable-compute-lease-deadlines`;
  resolve all failures and leave no architecture exception owned by this change.
  Run `make check-agent-skills` if implementation touched agent instructions.
- [ ] 5.8 **End-to-end pipeline:** record the run/result and relevant existing VM,
  bare-metal and API-credit complete-deal scenarios (`test_full_deal.py`,
  `test_bare_metal_mock_deal.py`, `test_credits_payment_deal.py` under
  `e2e-tests/tests/e2e/roles/scenarios/`), including a published option carrying the
  pool's deadline (4.2b). The traces for a reserved deal surviving the delivery deadline
  after activation, pre-activation crash expiry and unchanged quota holds are this
  change's own (4.4, 4.5). Missing readiness for this
  change's own pipeline scenarios remains an explicit blocker. No renewal scenario is owed.
- [ ] 5.9 **Promotion:** write D1–D2 to
  `openspec/specs/site-capacity/architecture.md`; update capacity reservation,
  recovery workers and authority boundaries in `docs/development/ARCHITECTURE.md`;
  put provider defaults/overrides and deadline snapshot semantics in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, including off-by-default switch,
  forward-start anchor, mixed-version compatibility and enablement. Retire the operator
  runbook for a lease abandoned before delivery in `docs/operator-handbook.md`, which
  the site's expiry replaces. Archive synchronizes the delta-covered `spec.md` files
  (`site-capacity`, `resource-pool-management`, `physical-provisioning`,
  `deal-lifecycle`, `storefront-publication`, `settlement-configuration`). Update
  `openspec/specs/README.md` if its descriptions change and complete the promotion
  record. Keep D4 deferred in the change, not the permanent current-state contract.
- [ ] 5.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=renewable-compute-lease-deadlines`, resolve every
  match, then `openspec validate renewable-compute-lease-deadlines --strict`.
- [ ] 5.11 **Archival:** finally run
  `openspec archive renewable-compute-lease-deadlines -y`, merging the deltas, then
  link the campaign row to the resulting archive. Closeout review reads the archived
  change and promoted permanent documents.

## Design promotion record

No promotion yet: this is the implementation plan, not implemented architecture.

| Accepted decision | Permanent location after implementation |
|---|---|
| D1–D2 deadline, claim and admission | `openspec/specs/site-capacity/spec.md`, `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D3 delivery-deadline support/default/override validation | `openspec/specs/resource-pool-management/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D3 publication read, restored deadline source and retired clause parameter | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/settlement-configuration/spec.md` |
| D3 retired abandoned-lease runbook | `docs/operator-handbook.md` |
| D5 watchdog, lease-end intent and proven-release distinction | `openspec/specs/physical-provisioning/spec.md`; recovery workers in `docs/development/ARCHITECTURE.md` |
| D4 deferred renewal | Not promoted; retained in archived design with its revisit condition |
| Goal/campaign status | Goal 8 in `docs/development/ROADMAP.md`; campaign row in `openspec/changes/README.md` |
