# Tasks — activate deployment-qualified per-period servicing

Pending implementation plan. `switch-on-hosted-per-period-vm` owns reduced, VM-only
forms of tasks 1.1–1.3, 2.3–2.4 and 3.1–3.4; each keeps its number here with only the
residual work, building on that change's VM `[charged]` declaration, operator policy
and runbooks, prepared hosted target and readiness check. Hosted deployment must
execute `returned`/`prorated`, the `chosen` dispute stop, rate-part extend/lift and
post-stop partial reversal. Seller delivery_end is a journaled dispute filing with a
qualifying mechanical payee self-penalty, never seller payment correction. No seller
restitution entry or several-stop-entries payments dependency remains. Product
implementation stays with its owners.

## 1. Internal readiness and hosted revision gate

- [ ] 1.1 Verify `switch-on-hosted-per-period-vm`, spot mechanics/publication (the
      `returned`/`prorated` derivation per declared treatment, setup parts, identity
      re-anchoring), servicing and its consolidated matrix, discovery and the
      delivery-deadline change have closed out. Recheck accepted contracts against
      those landed revisions and the VM declaration already shipped before any
      production declaration edit.
- [ ] 1.2 Confirm, extending the answers `switch-on-hosted-per-period-vm` obtained from
      the payments service's maintainers, that the intended hosted target executes
      `returned` and `prorated` on every stop entry and the term end, the dispute stop
      entry with `chosen` treatment, hold extension and lifting on rate parts, and
      partial reversal after stop. The vendored schema and vectors
      (`kit/arkhai-payments/schema/payments.schema.json`,
      `kit/arkhai-payments/test-vectors/payments.json`,
      `kit/arkhai-payments/schema/SOURCE.md`) already carry them; re-vendor through the
      existing tooling only if the producer publishes a newer revision. Verify
      provenance with public-safe identifiers only. A published schema with an older
      deployed target leaves this gate blocked.
- [ ] 1.3 Re-run the vendored vectors against the double and
      `kit/arkhai-payments/tests` for the treatments and operations beyond the MVP's:
      `returned`/`prorated` mapping (SCM last_boundary/stop), the `chosen` dispute-stop
      entry, afterStop holds with extend/lift and partial reverse before/after stop.
      Classify divergences by owner; repair compatibility without weakening product
      guarantees. Verify fail-closed refusal of every treatment a composition has not
      declared, absolute maximum terms with their own partialPeriod and no rounding,
      period-end/part-stop earning and {for} payout anchoring, activation-before-start,
      setup once encoded end at Agreement start, effectively clamped to approval if
      later, and the full-undelivered/zero-delivered self-penalty.
      Requalify foundation's delivery_end dispute-adapter intent and mediation
      published mapping; journal with end, never future-date and file pre-start
      failure at Agreement start. Seller sends no stop/reverse. Verify payee filing or valid concurrence, clean Agreement mapping, ended_at at/after Agreement start and no previous mechanical delivery_end ruling. Qualify both causes/delivered values, SignedDeliveryEndClaim canonical frame and ed25519/eip191 vectors, receipt embedding and Filing.concurrence, and respondent sign-or-contest polling. Invalid/unsigned/contested/repeat claims stay with operators, never silence defaults. Use foundation D10's cause=payee returned stops/refunds/capped penalty and cause=payer notice/partialPeriod netting with no penalty; setup returns iff delivered=false for either cause. Missing/chosen payer entries go to operators. Cases carry exact Agreement verified against mandate.deal. The delivery_end revision is vendored (`kit/arkhai-mediation/schema/SOURCE.md`); these live checks and setup-bearing preset enablement wait for the hosted mediation service to run it. A response bound is EULA/advertising only, not a code/activation gate.
      Verify seller stop entries only for entitlements such as spot notice; spot
      emergency files delivery_end. On-demand non-preemption remedy is buyer case/
      held money plus the premature-stop penalty, not mandate prevention. Verify no seller
      stop entry beyond entitlements is derived, and no implicit favourable stop,
      notice waiver, early release or multi-entry gate remains.
      Verify storefront signs end_delivery receipt (request has no at), never stops
      buyer billing; buyer half stops first, journals/retries same key through
      outage with billing until landing, and may additionally file delivery_end.
      Never add storefront monetary corrections. Return product decisions to owners.
      Kit tests use the kit-owned clock-injected authority engine directly; HTTP
      doubles wrap it with controls and mediation, with no kit-to-tooling dependency.
- [ ] 1.3a Extend the dispute-authority policy `switch-on-hosted-per-period-vm`
      published to the hosted mediation authority's mechanical rulings, recording its
      repeat/concurrent-case and dismissal policy and its key-retention and
      origin-continuity commitment against D3; a missing item is a blocker, not a
      caveat.

## 2. Reproducible qualification and target preparation

- [ ] 2.1 Run both compute lanes against the payment/mediation doubles using the
      existing scenario runner under `e2e-tests/tests/e2e/roles/scenarios`. Include
      convergence's full rate matrix, the MVP's four VM rows, spot's prepared entry
      points and declaration coverage; reuse its lane-clock and integration-restart
      evidence boundaries, not a second qualification matrix. Label every run
      lane-double evidence.
- [ ] 2.2 Validate fail-closed behavior outside lane profiles with focused
      composition/config integration coverage for bare metal and for every treatment
      a composition has not declared; the VM `[charged]` case is the MVP's.
- [ ] 2.3 Extend the hosted test target `switch-on-hosted-per-period-vm` prepared,
      through the same setup tooling, to bare-metal capacity and personas and to the
      hosted mediation authority. Confirm selectors before seeding; record deployment
      alias/revision, service identity/mode, persona/auth method by
      environment-variable name, isolated funding/capacity seed and a runnable
      bare-metal complete-deal entry point. Do not commit secrets, internal endpoints,
      account identifiers or raw private logs. Commit verifier-required setup, not
      ignored worktree-local files.
- [ ] 2.4 Re-run the readiness check `switch-on-hosted-per-period-vm` established,
      extended to bare metal and the hosted mediation authority, and stop on not-ready
      before deal scenarios. Record the observed readiness separately from the
      required environment; never reuse an unconfirmed inherited target for
      destructive seeding.

## 3. Hosted evidence and production enablement

- [ ] 3.1 Beyond the MVP's live rows, run bare-metal live complete deals and the
      residual hosted payment/dispute matrix in design D4: priced payer stop plus
      hint, authority `returned`/`prorated` partialPeriod billing, setup once, seller
      notice surviving storefront absence, read-before-timer-end where the funding
      timer is enabled, delivery_end dispute filing and sole qualifying mechanical
      payee ruling, buyer-half same-key outage stop retry with billing until landing,
      receipt evidence and receipt-backed delivery_end or triage, case extend/lift
      and partial reverse after stop, and the buyer's independent recovery
      observations. Use supported test controls for uncertainty/restart; annotate
      races/outages qualified only in the double. Every required live scenario must
      pass or remain explicitly blocking activation.
- [ ] 3.1a Run the completion scenario: an unconfigured buyer, one that changed no
      acceptance setting, takes an on-demand and a spot deal live under the shipped
      presets, and a live preemption returns the unstarted remainder.
- [ ] 3.2 For the runs of 3.1 and 3.1a, record actual authority effects, physical
      recovery, kept evidence and remaining holds/cases per run, with public-safe
      target/revision provenance. Close created deals, recover resources and stop
      owned setup resources after evidence collection. Never relabel double
      conformance as live behavior.
- [ ] 3.3 Extend the VM production composition's declared treatments to `returned` and
      `prorated`, and declare the bare-metal production composition's treatments, in
      their owned composition/config-generation paths. Verify publication, acceptance
      and materialization all enforce each list. Preserve identity/mode and original
      authorities for running deals; use existing drain/cutover rules if a
      coordinated deployment change is necessary.
- [ ] 3.3a Replace, in `docs/operator-handbook.md`, the operator runbooks the
      mechanical rulings supersede, keeping the procedures for filings outside the
      mechanical guards.
- [ ] 3.4 Requalify convergence's startup/withdrawal contract under the bare-metal
      declaration and the extended VM list; verify accepted terms and authorities
      remain unchanged. Run focused composition tests in both storefronts, affected
      config/schema/Helm render tests, kit contract tests and affected typing checks.
      Run `make check-packaging` before code review; fix changed comments/import
      placement during implementation, not closeout.

## 4. Closeout

Documentation-only, in order; code fixes return to implementation and review.

- [ ] 4.1 Comment hygiene: confirm changed comments/docstrings describe current
      invariants and run `make check-comment-hygiene`. Stop rather than editing code
      during closeout on any failure.
- [ ] 4.2 Import placement: confirm touched imports were moved/tested before review
      where safe, and remaining local imports have a verified cycle or deliberate
      lazy-load reason. Any needed code move returns to implementation.
- [ ] 4.3 Documentation compliance: check accepted D1–D4 decisions directly against
      OpenSpec placement and public-repository rules, classifying each disposition.
- [ ] 4.4 Narrative compression: keep final behavior, material evidence, residuals
      and documentation destinations; move unique rationale into design first.
- [ ] 4.5 Roadmap currency: update `docs/development/ROADMAP.md` Goal 8's deployment
      gate and completion with the actual hosted evidence and remaining accepted
      limitations; record it in the promotion record.
- [ ] 4.6 Campaign index currency: update this row/status and campaign dependencies
      in `openspec/changes/README.md`, preserving other dependents until archive
      cleanup; record the edit and run `make check-change-index`.
- [ ] 4.7 Packaging: run `make check-packaging` and
      `make check-architecture-change CHANGE=activate-per-period-compute-servicing`.
      Resolve or reassign no-longer-owned exceptions; run `make check-agent-skills`
      if agent instruction files changed. Code repairs return to implementation.
- [ ] 4.8 End-to-end pipeline: confirm both compute complete-deal pipelines and
      the required hosted acceptance matrix pass; index run/results and scenario
      provenance. Missing live target, setup or scenario is a blocker, not a pass.
- [ ] 4.9 Promotion: after code review, write the deployment-qualified declaration,
      disable-new/continue-existing rollback and authority-preserving cutover in
      `openspec/specs/settlement-configuration/architecture.md` and
      `docs/development/DEPLOYMENT_AND_CONFIG.md`; document evidence provenance in
      `openspec/specs/test-compatibility/architecture.md`; update
      `docs/development/ARCHITECTURE.md` settlement servicing and
      `openspec/specs/README.md` as needed. Record the mechanical rulings that
      replace operator procedures in `openspec/specs/deal-lifecycle/architecture.md`
      beside 3.3a's handbook edit. Complete the promotion record. Let archive
      merge spec deltas. Servicing owns diagram promotion; do not copy them again.
- [ ] 4.10 Documentation citations: run
      `make check-doc-citations CHANGE=activate-per-period-compute-servicing`, resolve
      every citation, then pinned `openspec validate activate-per-period-compute-servicing --strict`
      (repository invocation: `bunx @fission-ai/openspec@1.14.0 validate activate-per-period-compute-servicing --strict`).
      Run `make check-change CHANGE=activate-per-period-compute-servicing`.
- [ ] 4.11 Archival: after all preceding parts pass, run
      `openspec archive activate-per-period-compute-servicing -y` using the repository
      pin; merge deltas, update the index archive link, and have closeout review/
      triage read archived documents. Archive cleanup reverifies dependent designs.

## Design promotion record

All destinations are planned until implementation closeout.

| Accepted decision | Permanent location |
|---|---|
| D1 hosted gate beyond the MVP's subset and per-composition declared treatments | settlement-configuration spec/architecture; ARCHITECTURE settlement servicing |
| D1/D3 mechanical rulings replacing operator procedures; extended dispute-authority policy | docs/operator-handbook.md; openspec/specs/deal-lifecycle/architecture.md |
| D2 vector conformance and lane-double evidence labels | test-compatibility spec/architecture |
| D3 owned-target preparation, production declaration and rollback | settlement-configuration spec/architecture; docs/development/DEPLOYMENT_AND_CONFIG.md |
| D4 live versus qualification matrix and completion | test-compatibility spec/architecture; docs/development/ROADMAP.md Goal 8 |
| Goal completion and deployment gate resolved | docs/development/ROADMAP.md, at closeout |
| Row/status/dependency graph | openspec/changes/README.md, at closeout |
