# Implementation Tasks

## 1. Generalize the e2e fixtures

- [x] 1.1 Re-verify that no e2e file references bare metal or API credits, and inventory
      the VM assumptions in shared fixtures and helpers.
- [x] 1.2 Generalize fixtures and helpers away from VM-specific listing shape,
      provisioning, and teardown assumptions.
- [x] 1.3 Keep scenarios thin. Copying the VM scenarios and editing them per domain
      reproduces, one layer up, exactly the duplication this goal removes.

## 2. Recompose API credits

Implementation dependency: tasks 2.1-2.2 wait for the final committed interfaces
from `kit-storefront-composition-seam`, `kit-owned-negotiation-runtime`, and
`kit-owned-capacity-and-publication`. This change will consume those modules and
remove the API-credit copies; it will not recreate an absent extraction locally.


- [ ] 2.1 Remove every remaining local implementation of a concern the kit extractions
      own, so the domain is configuration and codecs over kit.
- [ ] 2.2 Confirm no extracted concern retains an API-credits copy. The domain already
      completes deals with its own implementations, so a passing scenario is not evidence
      of recomposition.
- [x] 2.3 Add the API-credits end-to-end deal path.
- [x] 2.4 Sequenced first deliberately: there is a working implementation to compare
      against, so a failure here is a recomposition defect rather than an unknown.

## 3. Bare-metal deployable stack

- [x] 3.1 Add the stack definition, following the topology conventions
      `domains/vms/compose.yml` and `domains/apicredits/compose.yml` already use.
      **Delivered** (recorded 2026-09-26): `domains/bare_metal/compose.yml`,
      `compose.bare-metal.yml`, and `compose.bare-metal-local.yml` with
      `dev-env/bare-metal/`, standing up the bare-metal end-to-end lane
      `bare-metal-publication-reads-pool-declarations` runs on.
- [ ] 3.2 Write it so the deployment shape can change — standalone service or a second
      contract inside a shared storefront process — without rewriting the scenarios.
- [ ] 3.3 Update `docs/bare-metal-seller-quickstart.md` with standing the stack up.
- [ ] 3.4 Confirm the Helm render tests (`helm/charts/bare-metal-storefront/tests/`)
      prove VM-only, bare-metal-only, and combined seller profiles contain no waits or
      references to disabled storefront roles, and add the missing profile if one is.
      (From `market-platform-bare-metal-10-storefront-composition` 5.4.)
- [ ] 3.5 Add operator configuration examples exposing separately composed VM and
      bare-metal roles through explicit URLs or gateway paths without sharing writable
      state. (From `market-platform-bare-metal-10-storefront-composition` 5.5.)

## 4. Bare-metal deal path

The static task 4.1 scenario consumes only the accepted `market bare-metal`
public command contract. Its live execution remains blocked on the installed
buyer contribution, sibling storefront's authenticated result/access/teardown
endpoints, selected-site authority, credentials, and real access target.

The end-to-end pipeline runs only in GitHub Actions, with no live host inventory, so
the 4.1 scenario cannot run there. The bare-metal deal path that runs on every pipeline
run — mock-provisioned, on the bare-metal lane — is owned by
`bare-metal-mock-provisioned-deal`; 4.1 remains the real-host evidence the protected
lane needs.


- [x] 4.1 Add the end-to-end scenario: discovery, negotiation, settlement, delivery,
      teardown.
- [ ] 4.2 Treat defects this surfaces in bare metal's own behavior as bare-metal
      findings, recorded against its owning change rather than absorbed here.
- [x] 4.3 Decide and record whether bare-metal teardown semantics differ from VM's, since
      whole-machine release is not VM destruction.

## 4a. Bare metal on the kit (moved here 2026-09-26)

These were `multi-domain-storefront-composition`'s external-producer gates 1.3, 3.7,
5.3, 5.5, 7.2, and 7.3. The contribution they waited on is merged; what remains is
composition. `design.md`'s "What bare metal still copies" names the files.

- [ ] 4a.1 Re-verify that `negotiation_service.py`, `negotiation.py`, the
      `/api/v1/negotiate/*` and listing routes in `api.py`, and their thread
      persistence in `sqlite_client.py` are still domain-local copies, and that no
      module in `domains/bare_metal` imports `market_negotiation_runtime`.
- [ ] 4a.2 Implement bare metal's `NegotiationDomainHooks` for the kit runtime:
      `validate_opening` decoding the closed `bare_metal.v1` demand (positive
      duration, one listed access method, one `ssh-ed25519` public key; refuse
      `access_ref`, private material, and any seller-owned routing or resource field),
      physical selection and exact settlement-option validation as `evaluate_round`
      inputs, `agreement_terms` binding the trusted listing's immutable resource and
      commercial values to the original demand, `build_artifacts` producing the
      accepted obligation the settlement runtime already consumes, and `place_hold`
      as today's hold placement.
- [ ] 4a.3 Route bare-metal negotiation through the shared shell's negotiate routes
      with the contribution registered, and delete the parallel routes, service, hook
      class, and thread persistence. No compatibility endpoint may select by URL,
      payload kind, app instance, or module getter.
- [ ] 4a.4 Serve bare-metal listings through the shared shell's listing routes from
      the common binding, and delete the domain-local listing routes.
- [ ] 4a.5 Reduce what remains of `runtime.py` and `server.py` to contribution
      adapters over `StorefrontAppConfig`; record in `design.md` anything that cannot
      reduce and why.
- [ ] 4a.6 Focused tests: the conformance matrix `multi-domain-storefront-composition`
      7.5 added runs under the bare-metal contract; opening refusal for each forbidden
      demand field; terms mismatch refusal; the bare-metal e2e lane's negotiation
      stages pass unchanged through the shared routes.

## 4b. Migrated seller and buyer requirements (verification)

Each task verifies a requirement migrated from an archived change against the
delivered packages, and each has a delta in `specs/`. `design.md`'s "Migrated
requirements" table records the source.

- [ ] 4b.1 **Opening carries only buyer-owned demand.** Verified by 4a.2's refusal
      tests and one e2e stage proposing an `access_ref`; both parties derive identical
      terms for a valid SSH demand. (`negotiation-protocol` delta.)
- [ ] 4b.2 **Resume is transcript-exact.** A buyer run interrupted after the seller's
      round resumes against the recorded thread when the registry listing has changed,
      and does not adopt the changed listing. (`negotiation-protocol` delta.)
- [ ] 4b.3 **Clean wheel.** Install the staged core buyer, bare-metal domain, kit, and
      bare-metal buyer wheels into a clean environment: entry-point discovery registers
      `bare_metal.v1`, the namespace imports, and no undeclared source-checkout
      dependency exists; uninstall the buyer wheel and confirm the namespace disappears
      while other domains start. (`deployment-state` delta.)
- [ ] 4b.4 **No invented seller topology.** The installed buyer configured with remote
      registry/storefront authorities and trust pins completes discovery, negotiation,
      settlement, status, access, and teardown through public authenticated APIs, with
      no compose-only hostname, co-located database, provisioning socket, or bypass
      profile in reach. (`deployment-state` delta.)
- [ ] 4b.5 **Package boundary.** Runtime and type-only import analysis of the built
      buyer wheel reaches no seller, site, fulfillment/provisioning implementation,
      sibling buyer, provider SDK, e2e helper, or test package; a missing accepted
      client surface fails with a prerequisite-version error rather than a local
      transport. (`test-compatibility` delta.)

## 5. Validation

External gate: tasks 5.1-5.2 require running API-credit and bare-metal seller
stacks, role-scoped credentials, the selected site/provisioning authority, and a
real whole-host access target. Static scenario/configuration work is not live-deal
evidence. Task 5.3 is intentionally unrun in this delegated lane.


- [ ] 5.1 Run both new end-to-end paths against a live service stack. For bare metal,
      the mock-provisioned deal from `bare-metal-mock-provisioned-deal` is the path that
      runs in the pipeline; real access and revocation remain the protected lane's.
      This repository has
      previously recorded e2e work validated only statically because no stack was
      available; treat a live run as an explicit gate, not a formality.
- [ ] 5.2 Confirm the goal's completion test: each domain runs a full deal through a
      composed storefront with no domain-local copy of an extracted concern.
- [ ] 5.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.
- [ ] 5.4 Run the bare-metal domain, publication, storefront unit/integration, shared
      core storefront, compute contract, and site capacity suites, and rebuild the
      affected wheels/images with packaging, import-boundary, and migration checks.
      (From `market-platform-bare-metal-10-storefront-composition` 6.1 and 6.3.)

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 6.2 **Import placement.** Review imports this change adds or touches.
- [ ] 6.3 **Documentation compliance.** Confirm the per-domain deal path landed in
      `test-compatibility`, the stack requirement in `deployment-state`, and that
      `TESTING.md` states what an end-to-end deal path proves.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior and
      validation evidence, including whether the live run happened.
- [ ] 6.5 **Roadmap currency.** Update Goal 4's current-state description in
      `docs/development/ROADMAP.md`. If every gap is closed, remove the goal — its
      durable result belongs in the specs and `ARCHITECTURE.md`.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.
- [ ] 6.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 6.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-and-credits-domain-stacks` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 6.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An end-to-end deal path is proven per domain, exercising shared fixtures rather than copied scenarios | `openspec/specs/test-compatibility/spec.md` — "Per-domain end-to-end deal path" |
| Every domain intended for deployment has a stack definition | `openspec/specs/deployment-state/spec.md` — "Deployable stack per market domain" |
| What an end-to-end deal path proves | `docs/development/TESTING.md` |
| Why API credits is recomposed rather than merely made to pass, and why fixtures generalize instead of scenarios copying | This change's `design.md` |
| A bare-metal opening carries only buyer-owned demand; resume is transcript-exact | `openspec/specs/negotiation-protocol/spec.md` — "Bare-metal negotiation preserves demand and authority ownership" |
| The bare-metal buyer ships as a clean wheel and addresses independently configured authorities | `openspec/specs/deployment-state/spec.md` — "Bare-metal buyer ships as a clean wheel contribution" |
| The bare-metal buyer wheel's dependencies point downward and across public clients only | `openspec/specs/test-compatibility/spec.md` — "Bare-metal buyer dependencies point downward" |
| Composing bare metal onto the kit is composition, not extraction; where each archived bare-metal requirement went | This change's `design.md` |
