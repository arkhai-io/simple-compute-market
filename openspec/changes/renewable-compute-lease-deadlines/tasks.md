# Tasks — compute lease activation deadlines

Design-stage plan; no implementation is claimed. All material decisions and
recommendations are in `design.md`. Renewal/lapse policy is deferred, not a task.
Package paths below describe this branch; reverify them after the pool-authority
dependency lands rather than preserving a forbidden import to fit this plan.

## 1. Dependency and contract gates

- [ ] 1.1 Verify `inject-site-pool-authority` has landed its session-scoped pool-facts
  port. Add the resolved provisioning allowance through that port; do not import
  the pool authority into `kit/site`. Reconfirm provider declaration ownership and
  any relocated pool package paths with the landed implementation.
- [ ] 1.2 Before event integration, verify `agreed-evidence-and-early-termination`
  supplies the signed `lease_ended` record, durable outbox, end service and evidence
  retention. Confirm its extension point for `activation_deadline_lapsed`. Do not
  implement a second event format, end service or site-triggered refund.
- [ ] 1.3 Coordinate the service migration order with
  `capacity-reservation-lifecycle-hardening`; select a separate leased-deadline
  query/index, rather than extending its reserved-hold expiry index. Before
  reservation acknowledgement-gap qualification, require only that change's
  negotiation-keyed exact-request reservation-idempotency slice; do not gate
  site-local activation work on its whole implementation/archive. Confirm
  `unify-compute-delivery-path` consumes the activation call without a target time
  and wires every commit caller before deployed enablement. Renewable ships the
  explicit compute composition setting `activation_deadlines_enabled` false; unify
  owns final enablement after storefront-first/site-off deployment and qualification.

## 2. Allowance declaration and validation

- [ ] 2.1 Extend `kit/resource-pools-contracts/src/market_resource_pools_contracts/hints.py`
  with the positive-integer `provisioning_allowance_seconds` tag and strict parsing.
  Extend pool write validation in `kit/resource-pools` (or its landed owner) so
  create/replace/patch/import and validate-only use the same provider support rule.
  Missing means provider default; null/zero/malformed values do not disable it.
- [ ] 2.2 Pass provider allowance declarations as plain data from the compute
  composition in `provisioning/compute/service/src/compute_provisioning_service/container.py`;
  set recommended VM/bare-metal defaults of 1800/7200 seconds and state them in
  `provisioning/compute/service/src/compute_provisioning_service/seed/pools.yaml`.
  Keep the API-credits composition's provider declaration empty. Existing pool
  rows need no data backfill; their absent overrides resolve the provider default.
  Add/configure `activation_deadlines_enabled` false in the compute composition;
  effective pool facts resolve no allowance while off without disabling support or
  validation. Snapshot only new commits when enabled; turning it off never clears
  an existing deadline. Document deployment and caller qualification ownership.
- [ ] 2.3 Validate at the lowest meaningful level: parsing in the existing hints
  unit suite (`kit/resource-pools-contracts/tests/unit/test_hints.py`); provider
  fallback, refusal and atomic imports in
  `kit/resource-pools/tests/integration/test_resource_pool_service.py` (or its
  landed successor). Use the existing suites; any new test requires maintainer
  approval. Run each affected package's `make test` after refreshing internal wheels.

## 3. Site deadline and conditional activation

- [ ] 3.1 Add nullable `renew_by_utc` and `renewal_phase` to
  `kit/site/src/market_site/db.py`. Add a service-owned ordered migration in
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
  leaving existing rows null, with the due-query index. Existing active leases
  must not become awaiting activation during upgrade.
- [ ] 3.2 Extend `kit/site/src/market_site/ledger.py` commit to snapshot the resolved
  allowance inside the same transaction, require a finite end where one resolves,
  and set the provisional deadline from max(commit_time, lease_start_utc). Recommit preserves it. Add
  activation from `leased` / `awaiting_activation` to `active`, setting the deadline
  to the current agreed end without a caller-supplied time. Active retries return
  unchanged; no-allowance/legacy leases return unchanged. All other states refuse.
- [ ] 3.3 Update truncation to cap the deadline and the due query to select the
  earlier of deadline and agreed end. Return the observed end/deadline/phase and
  cause to expiry. Claim all those values with `leased` state before release
  effects; stale claims write nothing. Preserve agreed-window overlap accounting
  and the release guard. Ordinary term end wins a tied due cause.
- [ ] 3.4 Extend the typed authority in `kit/site/src/market_site/authority.py`,
  models in `http_models.py`, `router.py` and the site client in
  `kit/site-client/src/market_site_client/client.py` for activation and lease
  inspection. Use existing service authentication and exact response verification;
  request bodies carry no billing kind, funded-through time or allowance override.
- [ ] 3.5 Run `make -C kit/site test` and `make -C kit/site-client test`. Integration
  jurisdiction is the public ledger API with a real embedded database: extend
  `kit/site/tests/integration/test_ledger.py` for the two claim orderings,
  elapsed-but-unclaimed activation, retry after truncation, full-window admission,
  no-allowance behavior and non-resurrection. Cover forward-start commits, switch-off
  new commits, enabled new commits and unchanged already-snapshotted deadlines. Use deterministic two-session controls,
  not sleeps. Migration behavior belongs in the compute service's existing
  migration integration suite, with new tests subject to maintainer approval.

## 4. Watchdog, evidence and first use

- [ ] 4.1 Update `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`
  and its authority calls to carry the conditional expiry claim before any provider
  effect, including direct-free and deferred-create paths. Keep provider I/O outside
  transactions and capacity held until guarded release succeeds. Extend the base
  event/outbox supplied by the foundation with the activation cause, claimed
  deadline/phase and intended effective end instant; retries preserve the original
  evidence. It is not proven release: retain the independent guarded physical
  completion fact, including release failure.
- [ ] 4.2 Extend lease views/control in `provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`,
  `provisioning/compute/client/src/compute_provisioning_client/client.py`, and the
  compute service lease controller/composition. Keep activation typed and
  offering-mode-neutral; expose null compatibility and the existing active instant.
- [ ] 4.3 Run the compute library, contracts and client `make test` targets, focusing
  on `provisioning/compute/tests/integration/test_release.py` for real persistence
  and release orchestration. Run `make -C provisioning/compute/service test-integration`
  for service migration/API composition. Unit targets cover only value/codec
  rules; do not use mocked ledger orchestration as race evidence. Run package
  typing checks where declared. Record commands, results and any unrun checks.
- [ ] 4.4 Prepare first use through the existing site/compute typed clients with a
  mock provider, seeded finite compute pool, caller service principal and controlled
  watchdog. Commit the reproducible setup/entry point with the implementation.
  Explicitly enable the switch in the owned site-only fixture, not in deployment
  defaults; prove off leaves null fields. Observe a future-start commit surviving
  until max(commit,start)+allowance and commit -> awaiting activation -> activation
  to the current agreed end (including prior truncation/lost acknowledgement) -> survival
  past allowance, and a separate unactivated lease -> claimed expiry -> guarded
  release. Readiness must pass before network scenarios. Hand this setup to the
  delivery-path owner; no storefront or payment service is needed for the site trace.
- [ ] 4.5 Before pre-closeout review, check comment hygiene and touched import
  placement, fixing code here rather than at closeout. Run `make check-packaging`
  after focused behavior passes. Record the limit: site-only evidence is not proof
  that every deployed delivery caller activates; that proof belongs to
  `unify-compute-delivery-path`.

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
  activation deadlines, not renewable active leases, as delivered. Record that buyer
  guarantees come from authority actions and held-money disputes. Preserve the
  deferred separate-site-operator revisit condition in the owning change history.
- [ ] 5.6 **Campaign index currency:** update this change's row and dependency graph
  in `openspec/changes/README.md`, retaining the current identifier, recording the
  activation-only boundary and the delivery-path enablement gate; run
  `make check-change-index` and record the update in the promotion record.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=renewable-compute-lease-deadlines`;
  resolve all failures and leave no architecture exception owned by this change.
  Run `make check-agent-skills` if implementation touched agent instructions.
- [ ] 5.8 **End-to-end pipeline:** record the run/result and relevant existing VM,
  bare-metal and API-credit complete-deal scenarios (`test_full_deal.py`,
  `test_bare_metal_mock_deal.py`, `test_credits_payment_deal.py` under
  `e2e-tests/tests/e2e/roles/scenarios/`). Coordinate activation-specific traces with
  `unify-compute-delivery-path`: a reserved deal survives allowance after activation,
  a crash before activation expires, and quota holds remain unchanged. If caller
  wiring or lane readiness is absent, name its owning change as an explicit blocker
  and record those validations unrun, not passed. No renewal scenario is owed.
- [ ] 5.9 **Promotion:** write D1–D2 to
  `openspec/specs/site-capacity/architecture.md`; update capacity reservation,
  recovery workers and authority boundaries in `docs/development/ARCHITECTURE.md`;
  put provider defaults/overrides and deadline snapshot semantics in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, including off-by-default switch,
  forward-start anchor, mixed-version compatibility and unify-owned enablement. Archive synchronizes the four
  delta-covered `spec.md` files (`site-capacity`, `resource-pool-management`,
  `physical-provisioning`, `compute-provisioning-contract`). Update
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
| D1–D2 deadline, activation, claim and admission | `openspec/specs/site-capacity/spec.md`, `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D3 allowance support/default/override validation | `openspec/specs/resource-pool-management/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D5 watchdog, lease-end intent and proven-release distinction | `openspec/specs/physical-provisioning/spec.md`; recovery workers in `docs/development/ARCHITECTURE.md` |
| D5 typed activation and inspection | `openspec/specs/compute-provisioning-contract/spec.md` |
| D4 deferred renewal | Not promoted; retained in archived design with its revisit condition |
| Goal/campaign status | Goal 8 in `docs/development/ROADMAP.md`; campaign row in `openspec/changes/README.md` |
