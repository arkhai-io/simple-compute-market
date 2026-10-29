# Tasks — activate deployment-qualified per-period servicing

Pending implementation plan. The sole external contract capability gate is the
hosted deployment of the payments revision adding per-part authorities and hold
extensions, with support for every offered stop term. Non-charged partialPeriod
terms wait for their revision; a supported charged/charged subset need not. No
additional payment capability is requested. Product implementation remains in its owning changes.

## 1. Internal readiness and hosted revision gate

- [ ] 1.1 Verify foundation, spot mechanics/publication, servicing and discovery
      implementation/closeout evidence. Confirm the in-lane payment/mediation double
      and unified delivery integration are available. Recheck accepted contracts
      against those landed revisions before any production declaration edit.
- [ ] 1.2 Confirm the intended hosted target deploys the required payments revision.
      Reuse or update `kit/arkhai-payments/schema/payments.schema.json`,
      `kit/arkhai-payments/test-vectors/payments.json` and
      `kit/arkhai-payments/schema/SOURCE.md` through existing vendoring tooling.
      Verify provenance with public-safe identifiers only. A published schema with
      an older deployed target leaves this gate blocked. Require producer-published
      signed snapshot, before/after-start, and partial-reversal before/after-stop
      vectors. Any absence blocks Qualification against the published contract;
      pinned kit-owned candidates permit only Qualification against a proposed contract,
      not Live evidence or production enablement. Use lane-double D6's definitions.
- [ ] 1.3 Re-run the vendored vectors against the double and
      `kit/arkhai-payments/tests`; verify per-part start/stop/reverse authorities,
      notice scheduling and charged/returned/prorated mapping (SCM started_period/
      last_boundary/stop), afterStop holds, partial reverse before/after stop and
      extend/lift. Requalify mediation adapter compatibility with the same revision.
      Classify divergences by owner; repair compatibility without weakening product
      guarantees. Verify fail-closed unsupported partialPeriod terms (charged/charged
      only until vendored and only with explicit buyer policy opt-in), absolute maximum
      terms with their own partialPeriod and no rounding, chosen dispute-stop entry,
      period-end/part-stop earning and {for} payout anchoring, activation-before-start,
      setup once end at activation and full-undelivered/zero-delivered self-penalty.
      Never add a storefront end-refund correction. A required product decision
      returns to its owning change. Kit tests use vector-derived in-process fakes.

## 2. Reproducible qualification and target preparation

- [ ] 2.1 Run both compute lanes against the payment/mediation doubles using the
      existing scenario runner under `e2e-tests/tests/e2e/roles/scenarios`. Include
      convergence's full rate matrix including spot's prepared entry points and
      declaration coverage; reuse its coherent-real-time and integration-restart
      evidence boundaries, not a second qualification matrix. Record
      published-contract qualification separately from historical proposed results.
- [ ] 2.2 Retire a proposed runtime extension only once no required scenario needs
      it. Retain evidence provenance as D2 recommends. Validate fail-closed behavior
      outside lane profiles with focused composition/config integration coverage.
- [ ] 2.3 Prepare the actual owned hosted test target through existing setup tooling.
      Confirm selectors before seeding; record deployment alias/revision, checkout
      ownership, service identity/mode, persona/auth method by environment-variable
      name, isolated funding/capacity seed and a runnable complete-deal entry point.
      Do not commit secrets, internal endpoints, account identifiers or raw private
      logs. Commit verifier-required setup, not ignored worktree-local files.
- [ ] 2.4 Run the target readiness check and stop on not-ready before deal scenarios.
      Record the observed readiness separately from the required environment. Verify
      configured payment and Agreement-selected dispute authorities and cleanup
      ownership; never reuse an unconfirmed inherited target for destructive seeding.

## 3. Hosted evidence and production enablement

- [ ] 3.1 Run both-domain live complete deals and the hosted payment/dispute matrix
      in design D4: activation then start, priced payer stop plus hint, authority
      partialPeriod billing, setup once, seller notice surviving storefront
      absence, exhaustion, exceptional_end, acknowledged buyer_end, case extend/lift
      and partial reverse after stop. Use supported test controls for uncertainty/
      restart; annotate races/outages qualified only in the double. Every required
      live scenario must pass or remain explicitly blocking activation.
- [ ] 3.2 Record actual authority effects, physical recovery, kept evidence and
      remaining holds/cases per run, with public-safe target/revision provenance.
      Close created deals, recover resources and stop owned setup resources after
      evidence collection. Never relabel double conformance as live behavior.
- [ ] 3.3 Enable published-contract servicing in both compute production profiles
      and their owned composition/config-generation paths. Verify publication,
      acceptance and materialization all enforce the declaration. Preserve identity/
      mode and original authorities for running deals; use existing drain/cutover
      rules if a coordinated deployment change is necessary.
- [ ] 3.4 Verify declaration withdrawal disables new deals but keeps existing watch,
      end work and evidence retention. Run focused composition tests in both
      storefronts, affected config/schema/Helm render tests, kit contract tests and
      affected typing checks. Run `make check-packaging` before code review; fix
      changed comments/import placement during implementation, not closeout.

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
      `openspec/specs/README.md` as needed. Complete the promotion record. Let archive
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
| D1 hosted per-part/hold gate and offered partialPeriod/end support | settlement-configuration spec/architecture; ARCHITECTURE settlement servicing |
| D2 vector conformance and honest evidence provenance | test-compatibility spec/architecture |
| D3 owned-target preparation, production declaration and rollback | settlement-configuration spec/architecture; docs/development/DEPLOYMENT_AND_CONFIG.md |
| D4 live versus qualification matrix and completion | test-compatibility spec/architecture; docs/development/ROADMAP.md Goal 8 |
| Goal completion and deployment gate resolved | docs/development/ROADMAP.md, at closeout |
| Row/status/dependency graph | openspec/changes/README.md, at closeout |
