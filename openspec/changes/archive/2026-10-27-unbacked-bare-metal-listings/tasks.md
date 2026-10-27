# Tasks — unbacked bare-metal listings

Every prerequisite is archived: `bare-metal-publication-reads-pool-declarations`,
`bare-metal-listing-shapes`, `compose-contact-exchange-across-compute`,
`encapsulate-capacity-backing`, `share-site-projection-state`, and
`bare-metal-mock-provisioned-deal`. Design reviewed 2026-10-14; returned to design
2026-10-20 for twelve carried-in items, and that design reviewed and its findings decided
the same day (1.14), and its second design review decided (1.15). Planned 2026-10-20; no
open change gates implementation.

Section order follows the design's implementation cadence and, within it, the layers:
Alkahest settlement inputs and the provisioning service (3–10), then deployment and test
hygiene (11–13), then unbacked bare metal (14–22), then closeout (23). Inside each run the
kits come before the domains composing them. Sections 3–5 build decision 19 in three
steps — the blocker carrier and Alkahest's configuration blockers, the chain probe that
produces reachability, then each storefront's use of both — because decision 20 (Section
11) relies on an unreachable chain being non-fatal and reported, and decision 7 (Section
18) on the blocker's kind. Section 22's scenario holds its storefront's loops through
Section 13's module holds.

Paths under `domains/vms/storefront/` are VM's storefront, under
`domains/bare_metal/storefront/` bare metal's, under `domains/apicredits/storefront/` the
API-credit storefront's, and under `provisioning/compute/service/` the compute provisioning
service; `src/` abbreviates each package's source root (`market_storefront`,
`arkhai_bare_metal_storefront`, `apicredits_storefront`,
`compute_provisioning_service`). Test levels are `docs/development/TESTING.md`'s: unit,
library integration, application integration (through the service's typed client), and
system (end-to-end).

Every section that changes a package bumps its version — minor for a changed contract, as
the last release did — updates the exact pins its dependants hold, and refreshes the
locks with `make lock`; its verification then runs `make check-packaging`, which includes
`make check-architecture`.

## 1. Design

- [x] 1.1 Decide each open question in `design.md` and record the decision there.
      Decided: site-and-resource identity with optional host fields; candidates from
      the capacity declaration; a publication change over the kit negotiation
      composition.
- [x] 1.3 **Decision gate.** Resolve the 2026-10-14 design review's first findings and
      record them in `design.md`. Decided with the maintainer: the dependency on
      `bare-metal-mock-provisioned-deal` is satisfied (archived 2026-10-09); backing is
      decided by one delegate, introduced and adopted by both domains in the new
      prerequisite `encapsulate-capacity-backing`; the site emits the bare-metal view
      for unbacked supply, host or no host, built through the pool's backing
      delegate, superseding the original "candidate comes from the capacity
      declaration" decision; the `bare_metal_publication` attribute stays the opt-in
      for both backings; an unbacked resource is never judged against availability.
- [x] 1.4 **Decision gate.** Decide each open question `design.md` lists from the
      2026-10-14 review, and record each decision there. All eight decided (1.6–1.11
      record each); the spec deltas are written to them.
- [x] 1.5 **Decision gate.** Record that this change removes the refusal of unbacked
      pools `encapsulate-capacity-backing` keeps in bare-metal publication. Decided
      with the maintainer ("This change removes bare metal's temporary refusal of
      unbacked pools"); planning names the deletion as a task.
- [x] 1.6 **Decision gate.** Decide the unbacked listing payload (review question 1).
      Decided with the maintainer: host identity, access methods, and availability are
      delivery terms the backing delegate carries or forbids through
      `carry_delivery_terms` and `delivery_term_constraints`; an unbacked listing
      publishes none of them; the `access_methods` default goes ("Delivery terms are
      the delegate's decision"). This change's end-to-end evidence proves the backing
      filter through the buyer CLI.
- [x] 1.7 **Decision gate.** Decide settlement options for unbacked listings (review
      question 3). Decided with the maintainer: the prerequisite's admissibility
      covers unbacked candidates; bare-metal publication also refuses any candidate
      whose payload has no settlement option and no accepted escrow ("A candidate with
      no settlement option yields no listing").
- [x] 1.8 **Decision gate.** Decide the opening source check (review question 4).
      Decided with the maintainer: the inventory guard requirement is scoped to
      availability, so an unbacked bare-metal recheck may read its origin site's
      declarations; held projections for bare metal remain the preferred end state and
      stay with the changes that own them ("An unbacked listing's recheck reads
      declarations, never availability").
- [x] 1.9 **Decision gate.** Decide the fulfillment routes for an unbacked deal (review
      question 5). Decided with the maintainer: the routes answer 404 for any deal
      whose accepted stage does not fulfil through capacity, before building the
      fulfillment service ("A deal settled by introduction has no fulfillment").
- [x] 1.10 **Decision gate.** Decide the permanent documentation delta and the system
      evidence (review questions 6 and 7). Decided with the maintainer ("Permanent
      documentation"; "The bare-metal evidence is VM's introduction scenario, stage for
      stage"): a new bare-metal unbacked introduction scenario on shared introduction
      stages, VM moved onto them, the bare-metal lane's mail sink, bare metal's
      settlement commands namespaced with a core refusal of duplicate root commands,
      and no Helm evidence.
- [x] 1.11 **Decision gate.** Decide the two-seller topology (review question 8).
      Decided with the maintainer: withdrawn from this change and recorded as unowned
      (task 2.2; "Goal 7 closes on single-site evidence").
- [x] 1.12 **Decision gate.** Decide how unbacked listings are source-reconciled without
      an operator (review question 9). Decided with the maintainer: bare metal shares
      VM's per-site projection state and publication loop through a new prerequisite,
      `share-site-projection-state`, carved out of
      `kit-owned-listing-and-fulfillment-lifecycles`; the opening recheck reads the
      held projection, superseding 1.8's scoped live read, and the inventory-guard delta
      is dropped ("Bare metal publishes on a loop over held projections first").
- [x] 1.13 **Decision gate.** Decide the resource-pool delta's form (review question 10).
      Decided with the maintainer: a modification of the now-permanent delegate
      requirement, naming delivery terms among its decisions ("Permanent
      documentation").
- [x] 1.14 **Decision gate.** Decide the 2026-10-20 redesign and its design review, and
      record each decision in `design.md`. Decided with the maintainer: decisions 16 to 26
      for the six Alkahest settlement questions and the six Helm-run defects, with stage
      events handed to `redesign-storefront-stage-events`; and from the review, an
      Alkahest chain probe producing reachability blockers (decision 19), a listing held
      while any mechanism is unknown (decision 7), the storefronts' own dependency
      preflights removed and a VM `startupProbe` (decision 20), the resource pass's pool
      context in `compute_provisioning` and the provisioning service (decision 4), the
      carrier's backings supplied by its reader (decision 6), the introduction refusal in
      `kit/storefront` on a `completes_outside_settlement` declaration (decision 9), every
      post-acceptance reader on the committed plan (decision 16), an older run-log refused
      before funding (decision 17), the bare-metal Alkahest inputs unready rather than
      fatal (decision 19), `kit/site`'s signed failures without outcome recording
      (decision 23), and the upgrade-order points recorded as unreachable in the
      supported deployment shape (decision 25).
- [x] 1.15 **Decision gate.** Decide the second 2026-10-20 design review (61) and record
      each decision in `design.md`. Decided with the maintainer: the chain probe, its
      schedule, and the client map it rebuilds in `kit/alkahest`, registered by each
      storefront as the `alkahest-chain-probe` loop, its results not expiring while held,
      and the runtime's own blockers given a kind (decision 19; 61 F3, F5); API credits'
      seed as the `listing-seed` loop step waiting for its dependencies, a reachability
      refusal of a create answered 503, and the storefront CLI's `publish` and `listings`
      commands as clients of the running storefront (decision 19; 61 F1); only the
      mechanisms of a candidate's admissible clauses classified, an empty admissible set
      closing (decision 7; 61 F2); `kit/site`'s projection and the site-client fixture
      carrying `publication_view_problems` (decision 4; 61 F4); a rollout's mixed-version
      window recorded as a hold (decision 25; 61 F6); and the unowned API-credit limit
      added to the roadmap promotion (61 F7).
- [x] 1.2 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations. Planned
      2026-10-20 as Sections 3–23. The facts `design.md` left to planning are settled in
      the tasks that depend on them: the chain probe's transport (4.1), whether client
      construction touches the RPC (4.4), bare metal's acceptance plan (7.4), the VM
      administrator dry-run's deal (7.5), and that nothing but the contact stage's own
      revalidation reads the reveal's settlement evidence (20.4).

## 2. Withdrawn scope

The closeout placeholder 2.1 was replanned against the reviewed design as Section 23, with
the evidence it named carried into 23.8.

- [x] 2.2 **Withdrawn** 2026-10-14 (`design.md`, "Goal 7 closes on single-site
      evidence"). Two seller sites behind one storefront, on both lanes, needs one
      storefront serving several sites, which is not supported today and is not yet a
      goal of its own. The scenario is recorded as unowned in the change index; its
      behaviour stays proven at integration level by
      `domains/vms/storefront/tests/integration/test_introduction_origins.py` and the
      delivery kit's routing tests.

## 3. Readiness blockers state their kind; an unusable Alkahest section is unready

Delivers the blocker kind on every mechanism's readiness and Alkahest's configuration
blockers, and release conditions derived only for ready clauses (D19;
`settlement-configuration` "Readiness blockers state their kind", "An Alkahest section that
cannot settle makes Alkahest unready"; `storefront-publication` "An Alkahest listing
advertises its release conditions"). Touches `kit/settlement-runtime`, `kit/alkahest`,
`kit/arkhai-payments`, `kit/contact-exchange`, and the tests in the domains that build a
blocker directly.

- [x] 3.1 `kit/settlement-runtime/src/market_settlement_runtime/configuration.py`:
      `ReadinessBlocker` gains a required `kind`, `configuration` or `reachability`;
      `ordered_readiness`'s `not_configured` and `disabled` blockers are `configuration`;
      `MechanismReadiness.safe_projection` reports it. Tests in
      `kit/settlement-runtime/tests/unit/test_configuration.py` (unit): a blocker without a
      kind cannot be built; the runtime's own blockers are configuration blockers; the
      safe projection carries the kind (D19).
      Done; `ReadinessBlockerKind` exported. Unit passed.
- [x] 3.2 `kit/arkhai-payments/.../settlement_config.py` (`_blocker`) and
      `kit/contact-exchange/.../settlement_config.py` (`contact_preflight`): every blocker
      is a configuration blocker, since neither contacts anything during readiness. Tests
      in `kit/arkhai-payments/tests/test_settlement_config.py` and
      `kit/contact-exchange/tests/unit/test_settlement_config.py` (unit) (D19).
      Done; unit passed.
- [x] 3.3 `kit/alkahest/src/market_alkahest/settlement_config.py` `alkahest_preflight`,
      every blocker a configuration blocker, adding: a trusted or interruptible oracle
      equal to the seller wallet; an empty seller wallet whatever clients are composed (the
      `has_composed_client` shortcut is deleted, and a wallet given as a bare address
      string is read as one, as bare metal passes it); an interruptible section with no
      interruptible oracle; a configured release model the composing domain cannot
      deliver, from a resource naming the domain's deliverable models; and, where the
      composing storefront declares that it signs, a missing wallet key or no configured
      chain, each named by its own code. The oracle-gated "no oracle" check gains its kind
      (D19).
      Done. The composing storefront supplies `deliverable_release_models` and
      `signs_transactions`; new codes `alkahest.oracle_is_seller_wallet` (seller role
      only), `alkahest.release_model_undeliverable`, `alkahest.wallet_key_missing`,
      `alkahest.chains_missing`; `alkahest.interruptible_policy_invalid` already covered a
      missing interruptible oracle. Chain blockers are reachability or configuration as
      Section 4 settles. A section selecting both models stays a startup refusal.
- [x] 3.4 `kit/alkahest/src/market_alkahest/release_conditions.py`: delete the seller-wallet
      fallback for the oracle (and the docstring that describes it);
      `publication_release_conditions` takes the clauses' readiness and returns nothing
      for a clause whose mechanism is unready. `configured_release_model`'s refusal of a
      section that is both oracle-gated and interruptible stays a startup refusal:
      incoherent configuration stops startup (D19's retained refusals). Export changes in
      `__init__.py` (D19).
      Done; `release_conditions` refuses an interruptible model with no oracle of its own
      or one equal to the wallet. (`publication_release_conditions` was later replaced by
      `escrow_release_conditions`, 11.9.)
- [x] 3.5 Tests (unit): `kit/alkahest/tests/unit/test_settlement_config.py` — one case per
      new blocker, each with its kind, and a buyer-role preflight unchanged;
      `test_release_conditions.py` — the fallback test inverted to a refusal, and
      `publication_release_conditions` yielding nothing for an unready clause. Update the
      direct `ReadinessBlocker` constructions in
      `domains/vms/storefront/tests/unit/cli/test_settlement.py` and
      `tests/unit/test_settlement_publication.py` (D19).
      Done; VM's publication harness double reports Alkahest ready wherever it builds
      Alkahest options, as the real composition does.
- [x] 3.6 Versions: `arkhai-kit-settlement-runtime`, `arkhai-kit-alkahest`,
      `arkhai-kit-arkhai-payments`, `arkhai-kit-contact-exchange`; `make lock`.
      Bumped once against `dev` (settlement runtime 0.5.0, Alkahest 0.9.0, Arkhai payments
      0.3.0, contact exchange 0.4.0), with patch bumps for pins and the Alkahest floor
      `>=0.9.0` wherever settlement runtime 0.5.0 is required; later bumps on the branch
      follow `docs/development/RELEASING.md`'s one-bump rule (85 F11).
- [x] 3.7 **Verify.** `make -C kit test-settlement-runtime test-alkahest
      test-arkhai-payments test-contact-exchange` (unit); `make test-storefront`; `make
      test`; `make check-packaging`. End-to-end: `e2e_deal`, `e2e_alkahest_escrow_codecs`,
      and `e2e_credits_deal` read readiness through status once deployed; no scenario
      configures an unusable section, and none is owed (integration covers each blocker).
      Passed: the four kit suites, every storefront suite, `make test` by its components,
      and `make check-packaging`; the Helm render was unrun here (no `helm`) and passed
      later (Section 11's corrections). End-to-end evidence is the round's validation.

Section 3 notes:

- VM's demand derivation moved into `listing_service.derive_listing` after
  `publication_artifacts`, and API credits passes its seller wallet to the preflight, both
  brought forward from Section 5 so this section's commit passed on its own.
- VM's human-readable `settlement status` lists blocker codes without their kind; the JSON
  output carries it.
- Round 1's triage: 85 F14 removed `require_deliverable_release_model`. 91 O1, 122 F3,
  132 F1: the two chain-backed tests of VM's `tests/integration/test_alkahest.py`, which
  exercised the SDK and a spawned chain rather than the storefront, moved to the
  end-to-end tier as `e2e_alkahest_trusted_oracle` (VM lane, and the Helm `e2e` step's
  served list), deriving its release condition through `kit/alkahest`; validation 134
  passed it on the lane and on Helm. `scripts/validate_slice.py`'s all-scenarios mode
  reads `E2E_APICREDITS_MODULE` and runs the served list beside the pipeline's.

## 4. Alkahest probes its chains apart from readiness

Delivers the `kit/alkahest` chain probe, its loop in every storefront composing Alkahest, the
live client map it rebuilds, and its results in status (D19, D20;
`settlement-configuration` "Alkahest probes its chains apart from readiness", "Readiness
blockers state their kind"). Touches `kit/alkahest`, `kit/storefront`'s client factory, and
the three storefronts' composition, loops, and status.

- [x] 4.1 (Amended in its note: a step probes every chain; the timer spaces the calls.)
      `kit/alkahest/src/market_alkahest/chain_probe.py`: an `AlkahestChainProbe` holding
      the configured chains, a per-chain client constructor supplied at composition, the
      live client map, each chain's last result and when it was taken, a probe interval,
      and an RPC timeout, with an async `step()` that probes the chains that are due. The
      transport is JSON-RPC over each chain's `rpc_url` (`eth_chainId`, then `eth_getCode`
      at each address the chain's address configuration requires, through
      `resolve_alkahest_address_config`), extending the module's existing bounded
      `eth_getCode` call, because no code here reads a chain's identity through the SDK and
      a probe must not depend on a client that may not exist. Results: reachable,
      `alkahest.chain_unreachable` (an RPC error or timeout), `alkahest.chain_id_mismatch`,
      or `alkahest.contract_missing`. A chain with no client in the map has its client
      constructed at each probe until it succeeds, updating the map in place. The module's
      startup-time `probe_addresses` helpers are kept only as far as
      `domains/vms/buyer`'s `chain_cli.py` still uses them (D19, D20).
      Done: `AlkahestChainProbe` over `ProbedChain`s, results `ChainProbeResult(result,
      probed_at)`; every step probes every chain and the loop's timer spaces the calls.
      A probe reads the address configuration (`alkahest.address_config_invalid`), then
      `eth_chainId`, then `eth_getCode` at `recipient_arbiter`, `eas`, and the ERC-20 default
      escrow obligation. Only `probe_addresses_sync` stays, for the VM buyer. Exported with
      `ALKAHEST_CHAIN_PROBE_LOOP` and `ALKAHEST_CHAIN_PROBE_ROUTE`.
- [x] 4.2 `alkahest_preflight` reads the probe's results from a `chain_probe` resource and
      makes no chain call: per chain its clauses use, no result yet or an unreachable
      result is the reachability blocker `alkahest.chain_unreachable`; a mismatch or
      missing contract is the configuration blocker of the same name. Delete
      `alkahest.contract_probe_failed` and the `observed_chain_id`, `deployed_contracts`,
      `contract_probe`, and `required_addresses` resources. A preflight given no probe — a
      buyer's — reports no chain blocker, as before. Alkahest's `public_detail_keys` gains
      the per-chain result and when it was taken, so status reports both through the
      mechanism's readiness and core's status model stays mechanism-neutral (D19).
      Done. Status had no mechanism readiness, so each storefront's status gained a
      mechanism-neutral `settlement` list of the mechanisms' safe projections (core
      `HealthResponse.settlement`, the storefront client, bare metal's health model).
- [x] 4.3 Settings: `[Settlement.alkahest]` gains a probe interval (30 seconds by default)
      and an RPC timeout (5 seconds by default), positive seconds refused by key otherwise,
      as every storefront duration is (D19).
      Done: `probe_interval_seconds` and `rpc_timeout_seconds` as `kit/config`'s
      `PositiveSeconds`, seller-only; `kit/alkahest` now declares `kit/config`, retiring its
      `ARCHITECTURE.toml` row (decision 26). The values schemas match the generator's
      output (regenerated byte-identical, Section 11's corrections).
- [x] 4.4 `kit/storefront/src/market_storefront_kit/alkahest_clients.py`: expose the
      factory's per-chain construction as a constructor the probe calls, so a chain whose
      construction fails is no longer dropped for the life of the process; the kit gains
      no probe, schedule, or other Alkahest behaviour. Confirm whether the SDK's
      construction opens the RPC connection and say so in the constructor's docstring;
      either way the probe rebuilds a missing client, and an address-configuration failure
      remains `alkahest.address_config_invalid` (D19, D20).
      Done: `alkahest_client_constructor(policy)`, `None` when the policy lacks the wallet
      key. Confirmed: an HTTP `rpc_url` builds without contacting the RPC, a websocket one
      connects at construction; pinned by
      `kit/storefront/tests/integration/test_alkahest_sdk_construction.py`, in the kit's new
      `tests/integration/`.
- [x] 4.5 VM (`src/server.py`, `settlement_composition.py`, `lifecycle_steps.py`,
      `services/listing_service.py`), bare metal (`src/runtime.py`, `lifecycle_steps.py`,
      `settlement_composition.py`), and API credits (`src/server.py`,
      `settlement_composition.py`, `lifecycle_steps.py`): each builds the probe beside its
      clients, hands it to the Alkahest registration as the `chain_probe` resource,
      registers its step as the `alkahest-chain-probe` loop and lifecycle step, and passes
      the probe's live map to every client consumer — the copies at VM's
      `settlement_composition.py` (`dict(alkahest_clients)`, `evidence_clients`) and API
      credits' are removed, and VM's `listing_service` reads client availability live
      rather than once at construction (D19).
      Done. Each composition root creates the one client map and hands it by reference to
      the probe and every consumer. A storefront with no Alkahest section composes no
      probe; VM and bare metal also probe a configured but disabled section, whose accepted
      obligations are still serviced over its chains; API credits builds nothing for a
      disabled section.
- [x] 4.6 (Amended in its note: readiness makes no chain call, and every step probes.)
      Tests: `kit/alkahest/tests/unit/test_chain_probe.py` (new, unit, a stub JSON-RPC
      transport injected): each result; a chain probed at most once per interval however
      often readiness runs; a held step leaves the last result standing however old; a
      missing client rebuilt on a later step. `kit/storefront/tests/unit/test_alkahest_clients.py`
      for the exposed constructor. Application integration through `StorefrontClient`, one
      per storefront — VM `tests/integration/test_lifecycle_status.py`, bare metal
      `tests/test_http_system.py`, API credits `tests/integration/test_lifecycle_status.py`:
      the loop is listed and steppable; a storefront started with its chain refusing
      connections reports Alkahest unready with `alkahest.chain_unreachable` and the probe
      result in status, and becomes ready on a stepped probe once the chain answers, without
      a restart. Each storefront's "registers and starts every loop" unit test lists the new
      loop (D19).
      Done, as listed: kit unit cases for each result, readiness making no chain call,
      every step probing, a held result read however old, and a rebuilt client; one
      application-integration test per storefront over a stub JSON-RPC transport. The
      production hand-off of the probe was at first shown only at composition level; 85 F3
      added the composition seams and 11.5 the started VM application.
- [x] 4.7 Versions: `arkhai-kit-alkahest`, `arkhai-kit-storefront` (exact pins in the
      storefronts), and the three storefronts; `make lock`.
      Done, with `arkhai-core-storefront` and the storefront client for the status field;
      the publish manifest and `docs/development/RELEASING.md` name `kit/alkahest`'s new
      dependency.
- [x] 4.8 **Verify.** `make -C kit test-alkahest test-storefront`; `make test-storefront`,
      `make test-bare-metal`, `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: every lane's Alkahest scenario (`e2e_deal`, `e2e_buy`,
      `e2e_alkahest_escrow_codecs`, `e2e_bare_metal_mock_deal`, `e2e_credits_deal`)
      publishes only after the first probe, so each passing proves the loop runs.
      Passed: the kit and storefront suites, `make test` by its components, and `make
      check-packaging`. `e2e_credits_deal` became evidence for the loop only from Section 6,
      whose seed waits for the probe.

Section 4 notes:

- The loop's first cycle runs as its timer starts, then every interval; until it has run,
  Alkahest is unready with a reachability blocker, which Section 18's hold reads and
  Section 6's seed waits on.
- Round 1's triage (85 F7, F8, F10, F3) and second triage (122 F1) are recorded in
  decision 19: a chain whose client could not be constructed reads unreachable; a
  construction is bounded by the RPC timeout on a daemon thread of its own, one per chain;
  readiness with no publication input judges every configured chain; the composition
  seams carry the constructor and the JSON-RPC call. Tests: kit unit, VM composition,
  API-credit and bare-metal application integration.

## 5. Each storefront derives Alkahest options only from ready clauses

Delivers release conditions derived after readiness in VM, bare metal, and API credits, and
the two startup refusals moved to readiness (D19, D16's consequence for the release model;
`storefront-publication` "An Alkahest listing advertises its release conditions", "Complete
bare-metal seller lifecycle", "Publication derives all ready settlement options";
`settlement-configuration` "An Alkahest section that cannot settle makes Alkahest unready").
Touches the three storefronts.

- [x] 5.1 VM: `services/publication_loop.py` `_create_request` no longer derives demands
      before readiness; `listing_service.py` derives them through
      `publication_release_conditions` with the readiness `publication_artifacts` returns,
      so an unready Alkahest refuses no candidate per cycle. `require_vm_release_model`'s
      startup call (`server.py`, `settlement_composition.py`) goes; the preflight is given
      VM's deliverable models (D19).
      Done: `require_coherent_release_model` refuses only contradictory models; the
      composition supplies the deliverable models, `signs_transactions`, and the wallet
      with its key whenever a section is configured; `settlement status` reads the same.
- [x] 5.2 Bare metal `src/runtime.py` `build_runtime_from_configuration`: a configured
      section missing `[Wallet].address`, `[Chains]`, or `[Wallet].private_key` starts with
      the named configuration blockers rather than refusing; a `ReleaseModelError` for an
      undeliverable model no longer refuses startup; `settlement_service()` no longer
      refuses every settlement service when Alkahest lacks an address (Arkhai payments'
      reconciliation keeps running); Alkahest inputs supplied with no section are still
      refused. `settlement_composition.py` calls `publication_release_conditions` with
      readiness and passes the deliverable models (D19).
      Done; only a contradictory section refuses startup. "Enabled or not" needed the
      settlement runtime to report a disabled section's configuration blockers after
      `disabled` (decision 19).
- [x] 5.3 API credits: `settlement_composition.py` and `services/listing_service.py`
      derive release conditions after readiness, gating the escrows a listing request
      supplies as well as those its clauses compile, so an unready Alkahest yields no
      escrow option on either path; `require_api_credit_release_model`'s startup call goes;
      the preflight is given the wallet and the deliverable models (D19).
      Done; supplied escrows are judged on readiness for their own chains, clauses or not.
- [x] 5.4 Tests (application integration through the typed client): bare metal
      `tests/test_app_composition.py` — the release-model and missing-input refusal tests
      inverted to unready-with-blocker starts, and the no-section refusal kept; VM
      `tests/integration/test_release_model_startup.py` — an undeliverable model starts
      unready, the both-models refusal kept; VM `tests/integration/test_publication_loop.py`
      — an unready Alkahest publishes the other mechanisms' options and refuses no
      candidate; API credits `tests/integration/test_alkahest_release_conditions.py` — an
      undeliverable model or missing oracle yields no Alkahest option on the clause and the
      supplied-escrow paths; each storefront's status reporting the blocker (D19).
      Done. Bare metal: each missing input and an undeliverable model start unready
      (composition level), one typed-client case reporting the blocker in status. VM:
      VM delivers every model, so the undeliverable case is a unit case in
      `test_settlement_composition.py`; the publication-loop case runs over the harness
      double. API credits: through the real app, an undeliverable model or missing oracle
      reported in status and refusing a supplied-escrow create 400; a supplied escrow
      unready on its chain dropped beside a ready clause escrow (library integration).
      Kit unit: a disabled section's blockers. Not tested: contact exchange's blockers
      beside `disabled`, and bare metal's per-deal Alkahest refusal with no address.
- [x] 5.5 Versions: the three storefronts; `make lock`.
      Done; `make check-packaging` passed.
- [x] 5.6 **Verify.** `make test-storefront`, `make test-bare-metal`, `make
      test-apicredits`; `make test`; `make check-packaging`. End-to-end: `e2e_deal`,
      `e2e_listing_shapes`, `e2e_bare_metal_mock_deal`, and `e2e_credits_deal` publish their
      Alkahest options through the reordered derivation.
      Passed: the kit and storefront suites, the touched `make test` components, release
      tooling, and `make check-packaging`. Every lane supplies its storefront's wallet key,
      so `signs_transactions` leaves their Alkahest ready.

Section 5 notes:

- Operator-visible: an enabled Alkahest with no wallet key or no chain is unready and its
  options withdrawn (VM) or refused at create (API credits), where before it published
  options no deal could settle.
- Between Sections 5 and 6 the API-credit seed published nothing (it ran at startup before
  any probe); the two were validated as one round.
- Round 1's triage, 85 F9 (decision 19): a VM create derives its release conditions from
  configuration for every escrow it publishes and refuses supplied `demands` with 400
  (`test_listings_api.py` `TestCreateListingReleaseConditions`); this also answers 88 V1's
  multi-registry listings.

## 6. API credits publishes once its dependencies answer

Delivers the `listing-seed` loop step, the create route's retryable refusal, and the
storefront CLI's listing commands as clients of the running storefront (D19;
`storefront-publication` "API-credit listing creation waits for or names an unreachable
mechanism"). Touches the API-credit storefront.

- [x] 6.1 `src/startup.py`: the configured seed no longer runs in startup. It is the
      `listing-seed` loop and lifecycle step (`lifecycle_steps.py`): it waits, logging
      nothing at error level, while the credits service cannot be reached for its quota
      registration or a mechanism its clauses use is unknown (every blocker a reachability
      blocker); gives up, logging once, on a configuration failure; and finishes once the
      listing exists, created or found (D19).
      Done in `src/listing_seed.py`, registered only while a seed is configured. It waits
      on an unanswered or 5xx credits-service call or any unknown mechanism it uses
      (`wait_for_every_mechanism`), without re-sending an accepted registration; gives up
      by raising `ListingSeedGivenUp`, which the loop controller records and logs once; its
      report names a reason code or error type, never error text. It retries every 2 s, or
      the probe's interval if shorter (decision 19).
- [x] 6.2 `services/listing_service.py` and `controllers/listings_controller.py`: a create
      refused only because a mechanism is unknown raises a distinct error the route answers
      with 503, naming the unreached mechanism and that the create can be retried; a
      configuration refusal stays a 400 with its blocker codes (D19).
      Done: `SettlementMechanismUnreachable(mechanisms, chains=)`, as decision 19's
      Section 6 paragraph states; `publication_artifacts` no longer raises when nothing is
      ready, so a clause-only create gets the 503 or the 400.
- [x] 6.3 `listing_publication.py`: `ApiCreditListingClient` and
      `SyncApiCreditListingClient` gain a list method over the listing route, in both
      variants. `cli.py` `publish` and `listings` call the running storefront through them
      and no longer build services or open the database in their own process (D19).
      Done: `list_listings` on both clients; `publish` signs as the storefront's principal
      to `--storefront-url`, the configured `base_url`, or localhost; `listings` reads
      unsigned. A refusal or no answer exits 1 naming the reason.
- [x] 6.4 Tests: unit `tests/unit/test_listing_publication_client.py` (parity of the new
      method) and `tests/unit/test_listing_publication_entry_points.py` (inverted: the CLI
      uses the typed client); unit `tests/unit/test_startup_seed_quota.py` moved onto the
      step — waits on an unreachable credits service and on an unprobed chain, gives up on
      configuration, finishes once found; application integration
      `tests/integration/test_publish_reconcile.py` through `ApiCreditListingClient` — a
      create against an unprobed chain answers 503 naming Alkahest, a configuration refusal
      400, and a stepped probe then lets the same create succeed; `tests/unit/test_server_composition.py`
      lists `listing-seed` (D19).
      Done as listed, the 503 cases in `test_alkahest_release_conditions.py`, which has the
      real app: supplied-escrow and clause creates against an unprobed chain refused 503
      naming `alkahest.v1 (chain anvil)` and succeeding after a stepped probe; configuration
      refusals 400; the seed stepped in the started storefront waiting while the chain is
      unprobed and publishing after a probe. `test_unreached_mechanisms.py` (unit) covers
      the waiting rule.
- [x] 6.5 Versions: `arkhai-apicredits-storefront`; `make lock`.
      Done.
- [x] 6.6 **Verify.** `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: `e2e_credits_deal` runs on the seeded listing, so its passing proves
      the step publishes once dependencies answer (`e2e_credits_payment_deal` skips
      without a payments target, and the seed offers only Alkahest; corrected in round
      1's triage, 85 F2).
      Passed: `make test-apicredits` and `make check-packaging`; no other project depends on
      the storefront.

Section 6 notes:

- Round 1's triage: 85 F2 — `test_credits_deal_buyer_cli.py` steps `alkahest-chain-probe`
  and `listing-seed` through the administrator's `run-cycle` before discovering, so
  discovery no longer races the seed (the lane's configuration gains the storefront's
  development administrator credential); 85 F13 — the seed pages through the storefront's
  listings to find its own, and a restarted storefront publishes no second listing.
- The CLI tests' replacement of `cli._open_storefront` falls under decision 27's roadmap
  row.

## 7. Settlement verifies against the plan committed at acceptance

Delivers settle verification, and every other post-acceptance reader, on the committed
`settlement_plan` (D16; `settlement-servicing` "Settlement verifies against the accepted
plan"). Touches `kit/alkahest`, `core/storefront`'s settle models, `core/storefront-client`,
and the three storefronts.

- [x] 7.1 `kit/alkahest/src/market_alkahest/escrow_verification.py`: a verification form
      taking the accepted obligation (from the committed plan, through
      `escrow_terms_from_settlement_plan`) rather than a listing, sharing the codec lookup
      and the comparison, expiry included, with the listing form; registered as the
      settlement verifier the domains reach. Tests in
      `kit/alkahest/tests/unit/test_native_escrow_verification.py` (unit): a plan whose
      listing has since changed release policy, wallet, or address book verifies; an escrow
      differing from the plan does not (D16).
      Done: `verify_escrow_against_plan` matches the escrow to one of the plan's Alkahest
      obligations on its chain and contract, data and expiry exactly, and is the
      registration's verifier. Unit: the plan verifies after the listing's wallet or the
      arbiter's address-book entry changes; a differing amount, recipient, or expiry is
      refused naming the field. The listing form was removed in round 1's triage (85 F14).
- [x] 7.2 VM `settlement_composition.py` `prepare_vm_settlement` verifies and builds its
      obligations from `thread["settlement_plan"]`, as `failure_actions.py`'s refund does;
      `settlement_stages.py` `AlkahestStage.recover_evidence` re-derives from the plan, not
      the evidence's stored `order` (D16).
      Done; a thread with no committed plan refuses settlement, and the dry-run reads the
      accepted proposal through the same `accepted_alkahest_proposal`.
- [x] 7.3 VM heartbeat and interrupt: `controllers/deals_controller.py` reads the cadence
      from the committed plan's `service_terms.heartbeat.interval_seconds`, and a plan with
      no heartbeat term (a deal that is not oracle-gated) reports no expected heartbeat;
      `controllers/admin_controller.py` `_deal_is_interruptible` reads the plan's
      `interruptible` term, never the current listing or chain address configuration (the
      listing is still loaded for its capacity binding) (D16).
      Done; the heartbeat setting is read only at acceptance, where the plan's term is
      written.
- [x] 7.4 Bare metal `settlement_stages.py` `verify_alkahest` and `revalidate_alkahest`
      verify against the committed plan. Acceptance builds its plan from the listing record
      the opening authorized: today every round reloads the listing and `build_artifacts`
      re-authorizes against the reloaded record, and no snapshot of the opening's record is
      kept, so `negotiation_runtime.py`'s `persist_opening` persists the authorized record
      with the opening and acceptance (`build_artifacts`, force-accept included) builds from
      it (D16).
      Done. The opening's record is saved in `bare_metal_opening_listings` (migration
      `bare-metal-storefront-0015-opening-listings`), and every continuation round,
      acceptance and force-accept among them, resolves against it (decision 16's Section 7
      paragraph).
- [x] 7.5 VM administrator dry-run verify: `VerifyEscrowRequest`
      (`core/storefront/.../models/settle_models.py`) gains `negotiation_id`, as
      `EvaluateSettleRequest` has, since the escrow row exists only at settle;
      `services/admin_settle_service.py` loads that accepted deal's committed plan and
      verifies against it with the 7.1 form; `storefront_client`'s async and sync
      `verify_settle` send it; bare metal's twin (`deal_controls.py`
      `settlement_admin_routes.verify`, `BareMetalVerifyEscrowRequest`) does the same; e2e
      Stage07b (`helpers/compute_deal_stages.py`, `vms/test_full_deal_buyer_cli.py`) names
      the negotiation (D16).
      Done; the request is `negotiation_id` alone, its former term fields removed. An
      unaccepted negotiation answers 404; a deal not settled by Alkahest or on an
      unconfigured chain is `valid: false` with the reason.
- [x] 7.6 API credits `settlement_stages.py` `_prepare_alkahest_settlement` verifies and
      builds against the committed plan rather than `order` (D16).
      Done; a thread with no recorded escrow proposal refuses settlement, and the chain
      and contract come from the proposal.
- [x] 7.7 Tests: VM `tests/unit/test_settlement_composition.py`,
      `unit/services/test_admin_settle_service.py`, `unit/test_interrupt_deal_admin.py`,
      `unit/test_heartbeat_gated_listings.py` (unit); VM
      `tests/integration/test_settle_controller.py` and `test_deals_controller.py`
      (application integration through `StorefrontClient`): a deal whose listing changed
      release policy after acceptance settles; the dry-run and the real verification agree;
      the interrupt and heartbeat follow the plan. Bare metal `tests/test_http_settlement.py`
      and `tests/test_deal_controls.py` (application integration): a listing refreshed after
      the opening does not change the accepted plan, and settle verifies against it. API
      credits `tests/unit/test_settlement_fulfillment.py` (unit) (D16).
      Done. VM: settlement verifies and registers the committed plan without rebuilding it
      (unit); the dry-run through `StorefrontClient` verifies the plan after the listing
      pays another wallet, refuses an underfunded escrow, and writes nothing; the
      interrupt and heartbeat follow the plan. Not delivered: an application-integration
      VM settle after a listing change, since VM has no typed-client settle harness; the
      unit test stands for it. Bare metal: the plan builder receives the opening's record
      after the listing is rewritten, and every verification receives the committed plan.
      API credits: a deal settles after its release condition and wallet change.
- [x] 7.8 Versions: `arkhai-kit-alkahest`, `arkhai-core-storefront`,
      `arkhai-core-storefront-client` (and the exact pin in `provisioning/compute/service`),
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
      Done under the one-bump rule; `arkhai-e2e-tests` 0.3.0, its floor on the storefront
      client at 0.27.0 for the new `verify_settle`.
- [x] 7.9 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make
      test-storefront`, `make test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`;
      `make test`; `make check-packaging`. End-to-end: `e2e_deal` and
      `e2e_deal_buyer_cli` (Stage07b's dry-run and settle), `e2e_non_erc20_settlement`,
      `e2e_bare_metal_mock_deal`, and `e2e_credits_deal` settle against the plan.
      Passed: the suites named and `make check-packaging`. `e2e_bare_metal_mock_deal` settles
      only with Section 8, which pins the lane's unpinned openings; the two were one round.

Section 7 notes:

- Round 1's triage, 85 F5 and F14 (decisions 16 and 18): verification finds the escrow's
  codec through the current address book, and the guarantee is what that allows; a deal
  accepted unpinned before this release is a cutover; the listing form of verification and
  VM's listing-token extraction are removed.

## 8. An escrow proposal naming no escrow contract is refused

Delivers the refusal at the seller guard and at `kit/alkahest`'s materialization chokepoint,
and removes every unpinned branch (D18; `negotiation-protocol` "An Alkahest obligation uses
exactly the release condition its listing authorizes"; `storefront-publication` "Complete
bare-metal seller lifecycle"). Touches `kit/policy`, `kit/alkahest`,
`core/storefront-client`, the three storefronts' pricing, and the tests and scenarios that
opened unpinned.

- [x] 8.1 `kit/policy/src/market_policy/scalar_policies.py`: `escrow_shape_guard` refuses an
      escrow proposal whose escrow address is empty or zero with a named reason, and still
      passes a negotiation carrying no escrow proposal; `_accepted_escrow_for_proposal`
      loses its zero-address case. Tests in `kit/policy/tests/unit/test_escrow_shape_guard.py`
      (unit): the "unpinned escrow" case inverted (D18).
      Done: an escrow proposal (one stating a `chain_name` or `escrow_address`) naming no
      contract is refused `escrow_contract_unpinned`; an escrow against a listing accepting
      none is refused `escrow_not_in_accepted_set`. `pinned_proposal(history)` is the
      buyer's opening, which VM and API credits price from in every round, and
      `buyer_counter_guard` reads from it whether the round bargains an amount. Unit
      passed, every unpinned shape and the scalar counter case.
- [x] 8.2 `kit/alkahest`: `proposals.py` `authorize_escrow_proposal` and `alkahest.py`
      `materialize_escrow_terms_from_proposal` refuse an unpinned proposal through the
      existing `ReleaseConditionError` family, which every caller already translates, with
      its own code; `escrow_verification.py`'s default-kind branch goes. Tests in
      `test_release_authorization.py` and `test_native_escrow_verification.py` (unit) (D18).
      Done: `UnpinnedEscrowError` and `require_pinned_escrow`, which both entry points call
      first; unit cases over four unpinned shapes and the five materializers.
- [x] 8.3 First-entry pricing goes: VM `storefront_round.py` (`_selected_option`,
      `_seller_reference_amount`) and `domains/vms/listings/.../pricing.py`; API credits
      `pricing.py`'s first-escrow and first-option fallbacks; bare metal
      `negotiation_runtime.py` `_priced_acceptance`'s chain-blind fallback (D18).
      Done as decision 18's Section 8 paragraph records: VM and API credits price the
      pinned opening, an unselected escrow at zero, with their default guards first in
      fixed order; bare metal refuses such an opening in pricing, 409, before any policy,
      and prices a continuation's exit from nothing rather than refusing. Unit cases in VM
      `test_extract_initial_price.py` and `TestRoundReference`, and API credits
      `test_concept_modules.py`. Both compute storefronts' negotiation-strategy status
      probes run against a synthetic listing accepting their placeholder escrow.
- [x] 8.4 `core/storefront-client/src/storefront_client/client.py` `_negotiate_new_proposal`
      no longer fills a zero escrow address or token for an escrow opening, which would
      build exactly the refused shape: an escrow opening requires its escrow address, and a
      caller with no escrow uses the selection-only opening. Tests in
      `core/storefront-client/tests/test_negotiate_new_payload.py` (unit) (D18).
      Done: an escrow opening with no address raises `ValueError` before any request; an
      explicit zero address still reaches the server, as 8.6 tests.
- [x] 8.5 Callers that opened unpinned move to a pinned or selection-only opening: VM
      `tests/unit/test_escrow_fields_policy.py`, `unit/test_escrow_verification.py`,
      `integration/test_negotiate_controller.py`, `integration/test_listings_api.py`; bare
      metal `tests/test_http_negotiation.py` (its `_UNPINNED` cases become refusals); e2e
      `helpers/compute_deal_stages.py` (the opening and the evaluate-negotiate dry-run),
      `vms/test_full_deal_buyer_cli.py`, `vms/test_multi_registry.py`,
      `vms/test_non_erc20_settlement.py`, `bare_metal/test_bare_metal_mock_deal.py` (D18).
      Done. Pinned, a proposal must also select one of the listing's advertised conditions,
      which the unpinned openings had skipped, so every pinned opening names the listing's
      condition; `compute_deal_stages.py` gains `alkahest_opening(listing)`, used by the
      shared stages, bare metal's Stage12b, and the multi-registry openings.
- [x] 8.6 Application integration through `StorefrontClient`: in VM's
      `tests/integration/test_negotiate_controller.py` and bare metal's
      `tests/test_http_negotiation.py`, an unpinned escrow opening is refused naming the
      reason, with the seller's guard composed and with it omitted (the kit chokepoint
      refuses it) (D18).
      Done: in both, an opening at the zero address is 409 `escrow_contract_unpinned` with
      nothing accepted, under the default chain and a permissive one. Each refuses before
      the kit chokepoint, which 8.2's unit tests evidence. VM's seller stage refuses an
      unpinned carrier beside a selection (decision 18's Section 8 paragraph).
- [x] 8.7 Versions: `arkhai-kit-policy` (and the exact pin in `kit/negotiation-runtime`),
      `arkhai-kit-alkahest`, `arkhai-core-storefront-client`, `arkhai-vms-listings`,
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
      Done, with `arkhai-vms-negotiation` and `arkhai-apicredits-domain`, which also
      changed; `arkhai-e2e-tests` stays at 0.3.0 (triage 139).
- [x] 8.8 **Verify.** `make -C kit test-policy test-alkahest test-negotiation-runtime`;
      `make test-core`; `make test-vms-domain`, `make test-storefront`, `make
      test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`; `make test`; `make
      check-packaging`. End-to-end: `e2e_deal`, `multi_registry`,
      `e2e_non_erc20_settlement`, and `e2e_bare_metal_mock_deal` open
      pinned and negotiate as before.
      Passed: the suites named and `make check-packaging`, after three fresh-context checks
      whose pricing findings decision 18 records. `docs/configuration.md`'s
      `escrow_shape_guard` and `bisection` rows describe the refusals.

Section 8 notes:

- Round 1's triage: 85 F1 — `accept_unpriced_selection` and `accept_exact_listing` settle
  the pinned opening's option; 85 F6 — `authorize_escrow_proposal` holds a proposal to the
  listing's accepted entry (`escrow_not_in_accepted_set`, `escrow_field_mismatch`), and bare
  metal runs `escrow_shape_guard` as a required guard, its default policies
  `("listed_price",)`; 85 F17 — VM refuses a continuation whose opening's option was
  withdrawn, `pinned_option_withdrawn`; 85 F4 — decision 18's rationale corrected (the
  client had filled the zero address for every caller naming none). Tests: kit unit; VM
  and bare-metal integration through `NegotiationRuntime` and the typed client. Second
  triage, 122 F6: the delta attributes the accepted-entry refusal to the seller's
  acceptance.

## 9. A buyer funds only what it derives

Delivers the accept reply without `accepted_escrow_terms`, the buyer's own derivation checked
against the seller's plan on every branch and on resume, and release conditions in the
run-log (D17; `negotiation-protocol` "The accept reply carries no escrow terms";
`buyer-orchestration` "A buyer funds only what it derives"). Touches `kit/alkahest`, `core`
(`market_core`), `core/storefront`, `core/buyer`, the VM and API-credit buyers, and bare
metal's reply.

- [x] 9.1 Producers: `kit/alkahest/.../proposals.py` `accepted_escrow_artifacts_from_proposal`
      stops building the field; `plans.py`'s and `core/src/market_core/schemas.py`'s legacy
      coercions (`_coerce_legacy_escrow_terms`, `_coerce_legacy_terms_list`) go, and
      `escrow_terms_to_settlement_obligation` and `core/buyer`'s `deal_helpers.py` build the
      obligation explicitly rather than through them; `core_storefront/models/negotiation_models.py`
      `NegotiateNewResponse` and `NegotiateContinueResponse` lose the field and its
      docstring; bare metal's `_ESCROW_RESPONSE_ARTIFACTS` drops it (D17).
      Done; a flat terms shape no longer parses as an obligation or plan. The
      `ARCHITECTURE.toml` row excusing core's `alkahest.v1` vocabulary for the coercions is
      deleted (decision 26). Unit passed.
- [x] 9.2 `core/buyer`: `negotiation_client.py` (`NegotiationOutcome`,
      `parse_accepted_terms_from_reply`, `ResumeState`, the reply parse and resume, the three
      accept branches), `orchestration.py` (`_settle_one` always derives through
      `build_escrow_terms`; the negotiate hook), and `deal_helpers.py` (`DealContext`,
      `load_deal_context` and its back-fill, `NegotiationResumePoint`) stop reading the
      field. `AdvertisedPlanValidatorFn` runs on every branch that receives a plan and on
      resume, not only the selection branch; its callable receives what a derivation needs
      (the accepted proposal or selection, the agreed amount and duration), and
      `core/buyer` gains no import of `kit/alkahest` (D17).
      Done with the check placed where funds move, as decision 17's Section 9 paragraph
      records: `make_escrow_settle_hook` takes a required plan-check port run before
      `create_escrow` (`seller_plan_mismatch`); `AdvertisedPlanValidatorFn` is unchanged.
      The negotiate hook writes the selected entry's opaque `listing_record`. Unit passed;
      `_negotiate_matches` has no seam, so its recording is covered through the domains.
- [x] 9.3 The run-log: `negotiation_completed` and both negotiate CLIs' `run_ended` record
      the selected listing's advertised release conditions; `load_deal_context` and the
      resume point read them; a resumed run derives from the Agreement's selected option and
      those conditions and checks any recorded seller plan against them; a run-log accepted
      without recorded conditions and not yet funded is refused before funding, naming that
      a new run is needed; a run whose escrow exists resumes (D17).
      Done as decision 17 records: the record is `kit/alkahest`'s
      (`release_conditions_record`, `recorded_release_conditions`), written at run start
      and end, one per listing on a `market buy` resume; `derive_accepted_escrow_terms`
      derives from the recorded accepted proposal and holds it to the recorded plan
      (`require_escrow_terms_fund_plan`), refusing `release_conditions_unrecorded`; the
      amount is exact from the Agreement (`exact_agreed_amount`). Unit: kit `test_plans.py`,
      core `test_identity_recovery.py`.
- [x] 9.4 VM buyer (`settlement_stages.py` `enrich_deal`, `_accepted_proposal_chain`,
      `_resume_alkahest`, `_refuse_without_release_condition`; `escrow_client.py`;
      `escrow_cli.py`; `buyer_client.py`; `negotiate_cli.py`; `buy_cli.py`;
      `buy_orchestrator.py`) and API-credit buyer (`settlement_stages.py`
      `AlkahestBuyerStage.enrich`, `settle_cli.py`, `negotiate_cli.py`, `buyer_client.py`,
      `buy_cli.py`, `escrow_client.py`) stop reading the field; API credits supplies a plan
      validator over `kit/alkahest`'s `validate_selected_escrow_plan` as VM does (D17).
      Done. Both domains' stages carry the listing record and pass
      `require_escrow_terms_fund_plan` as the plan check; API credits supplies it through
      its settle hook, since its buyer opens with escrow proposals. VM's resume paths share
      `derive_resumed_escrow_terms`. Unit: VM `test_release_condition_refusals.py`,
      `test_negotiate_stage_dispatch.py`; API credits `test_settle_credentials.py`,
      `test_settlement_composition.py`. Not driven: API credits' `negotiate` CLI recording,
      and the carry-forward through VM's `negotiate --from` or `buy --from`.
      `escrow_cli`'s `make_create_escrow_fn` is imported at module level (176 F1).
- [x] 9.5 Tests (unit): `core/buyer/tests/unit/test_settlement_acceptance.py`,
      `test_identity_recovery.py`, `test_orchestrator.py` — a seller plan naming another
      arbiter or recipient than the listing advertised is refused before funding on the
      escrow-proposal and selection branches and on resume; an older run-log is refused;
      a funded run resumes. VM buyer `test_release_condition_refusals.py`,
      `test_resume_helpers.py`, `test_buy_resume_cli.py`, `test_buy_orchestrator.py`,
      `test_buyer_client*.py`; API-credit buyer `test_settle_credentials.py`,
      `test_negotiation_flow.py`, `test_negotiate_cli.py`. Application integration fixtures
      in VM `tests/integration/test_negotiate_controller.py` and `test_publication_loop.py`
      and bare metal `tests/test_http_negotiation.py` assert the reply carries no
      `accepted_escrow_terms` (D17).
      Done, as 9.1–9.4 list, with the replies asserted in VM and bare metal; the mismatch is
      refused at funding. No test drives a whole `market buy` against a mismatching seller;
      the live API-credit escrow path is `e2e_credits_deal`'s.
- [x] 9.6 Versions: `arkhai-kit-alkahest`, `arkhai-core`, `arkhai-core-storefront`,
      `arkhai-core-buyer` (and the exact pin in `domains/bare_metal/buyer`),
      `arkhai-vms-buyer`, `arkhai-apicredits-buyer`, the three storefronts; `make lock`.
      Done: `arkhai-core` 0.5.0 with its exact pins; the three buyers minor-bumped for
      incompatible changes; floors on `arkhai-core-buyer>=0.6.0` and
      `arkhai-kit-alkahest>=0.10.0`.
- [x] 9.7 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make test-vms-buyer`,
      `make test-apicredits`, `make test-storefront`, `make test-bare-metal`; `make test`;
      `make check-packaging`. End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, and
      `e2e_credits_deal` fund through the buyer's own derivation, and
      `e2e_bare_metal_mock_deal` through the typed client.
      Passed: the suites named and `make check-packaging`; core's mypy typecheck was unrun
      (denied in the unattended session).

Section 9 notes:

- Round 1's triage: 85 F12 — a reply carrying no plan is refused before funding on every
  path (`seller_plan_missing`); 85 F4 and, in the second triage, 122 F5 — decision 17's
  bullets rewritten to what was built.

## 10. The provisioning service refuses unserved providers and signs failures

Delivers the stored-provider startup refusal and signed 500s after authentication (D23;
`resource-pool-management` "A service refuses to start while a stored pool names an unserved
provider"; `physical-provisioning` "A failure after authentication is answered signed").
Touches `kit/resource-pools`, the provisioning service, and `kit/site`.

- [x] 10.1 `kit/resource-pools/src/market_resource_pools/service.py`: a stored-provider
      check beside `stored_declaration_problems` naming each pool and the provider no
      registered handler serves; the provisioning service's `verify_pool_declarations`
      startup step (`src/app_runtime.py`) refuses on it, beside the invalid-declaration
      refusal. Tests: `kit/resource-pools/tests/integration/test_resource_pool_service.py`
      `TestStoredDeclarations` (library integration);
      `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`
      (application integration): a stored pool naming an unregistered provider refuses
      startup naming it (D23).
      Done: `stored_provider_problems` and `require_served_stored_providers`, run after the
      declaration check; library integration as listed. The startup test drives
      `verify_pool_declarations` over migrated SQLite with two real handlers, not the
      running application.
- [x] 10.2 `src/middleware/auth.py` `ProvisioningAuthMiddleware.dispatch`: a route failure
      after authentication is logged and answered as a signed 500 with a fixed,
      non-revealing detail, following VM's `admin_identity.py`, and recorded as the
      request's outcome so an exact retry replays the same signed answer. Tests:
      `tests/unit/middleware/test_auth.py` (unit) and an application-integration case
      through `ProvisioningClients`: the typed client receives a signed 500, not a
      response-authentication error, and an exact retry gets the same answer rather than
      "in progress" (D23).
      Done (`ROUTE_FAILURE_DETAIL`). Tests under both signing schemes, and
      `test_pools_api.py` `TestRouteFailureAfterAuthentication` through the typed client:
      `ComputeProvisioningError` 500, its exact retry replaying the 500.
- [x] 10.3 `kit/site/src/market_site/auth.py` `SiteAuthMiddleware.dispatch`: the same signed
      500, recording nothing; an exact retry of a retry-safe route runs again, and of an
      unsafe one is refused as today. Tests:
      `kit/site/tests/integration/test_site_auth_middleware.py` (library integration);
      `domains/apicredits/service/tests/integration/test_credits_signed_roundtrip.py`
      (application integration through the typed client) (D23).
      Done; the application-integration case is in `test_signed_authority.py`, which runs
      the service's real app: the storefront client gets `CreditsServiceError` 500, not an
      authentication error.
- [x] 10.4 Versions: `arkhai-kit-resource-pools`, `arkhai-kit-site`, the provisioning
      service, the API-credits service; `make lock`.
      Done.
- [x] 10.5 **Verify.** `make -C kit test-resource-pools test-site`; `make
      test-provisioning`; `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: none exercises an unserved provider or a route failure, and none is owed;
      every lane's provisioning traffic passes through the changed middleware.
      Passed: the suites named, `make check-packaging`, and `make check-comment-hygiene`.

Section 10 notes:

- Decision 23 records the limits: a failure after a streamed response has started is not
  caught (85 F15), and a pool with both problems reports its declarations first.
  `marketplace-identity` already states that a response is signed whether a refusal comes
  during authentication or after.
- Round 1's triage, fixes concerning no section: 85 F11 — `docs/development/RELEASING.md`
  states that a change bumps each package at most once against its target branch; 73 R2,
  77 R1, 83 R1 — `docs/agents/change-workflow.md`, the workflow wrapper's SIGTERM outcome,
  and `round-done`'s index rebuild, each with a unit test.
- Round 1's evidence: after each triage's fixes, `make test` passed every suite but the
  Helm render (no `helm` in the session); validation 134 of `9aa024e` then passed local,
  Helm, and all three pipeline lanes.

## 11. Storefronts start degraded rather than waiting on their dependencies

Delivers the VM storefront chart without dependency-waiting init containers and with a
`startupProbe`, and the VM and API-credit storefronts without their in-process dependency
preflights (D20; `deployment-state` "A deployment does not wait on a service's
dependencies"). Touches `helm/charts/storefront`, `helm/charts/bare-metal-storefront`'s
render test, `helm/scripts/test-render.sh`, the VM and API-credit storefronts' startup and
settings, a cookbook, and the `deployment-state` delta.

- [x] 11.1 `helm/charts/storefront/templates/deployment.yaml`: delete the `initContainers`
      block (`wait-for-rpc`, `wait-for-registry`); add a `startupProbe` mirroring
      `helm/charts/bare-metal-storefront/templates/deployment.yaml`'s (`/health`, port
      `http`); drop the liveness and readiness `initialDelaySeconds` the startup probe
      replaces, as bare metal has none; the comment beside them states the current rule.
      `templates/_helpers.tpl`: delete `storefront.usesInternalRegistry` and the unused
      `rpc.url` and `rpc.wsUrl` helpers (D20).
      Done; the probes name the container port `http`.
- [x] 11.2 Render tests (`docs/development/TESTING.md` "Chart Render Tests"):
      `helm/charts/storefront/tests/test_render.py` replaces every `wait-for-*` assertion
      with one test, over every fixture, that no container named `wait-for-` renders and
      that `startupProbe` does; the tests that a chain's RPC is or is not waited for go.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts its `startupProbe`.
      `helm/scripts/test-render.sh`: the EVM fixture's chain-readiness assertion goes and
      its `CHAIN_ID|RPC_URL` check stays (D20).
      Done (chart render): over the defaults, the local release, every rendering fixture,
      and a two-agent release, no `initContainers`, a `startupProbe` on `/health`, and no
      `initialDelaySeconds`; bare metal's likewise.
- [x] 11.3 VM `src/startup.py`: delete `_preflight_provisioning` and its step, and correct
      the step list's docstring; `settings.toml` and `groups/config.py`'s template lose
      `[seller.provisioning].fail_on_unreachable` and `preflight_timeout`; both join
      `retired_settings.py`'s removed settings, so a configuration stating either is
      refused by key as every retired setting is; regenerate the values schema with `make
      helm-values-schema` and update `tests/unit/test_values_schema.py` and
      `tests/integration/test_publishable_startup.py` (D20).
      Done. The keys live at `[provisioning]`, so the retired keys are
      `provisioning.fail_on_unreachable` and `provisioning.preflight_timeout`, refused at
      startup, by `config set`, and by the values schema (regenerated byte-identical,
      Section 11's corrections).
- [x] 11.4 API credits `src/startup.py`: delete `_preflight_credits_service` and its call;
      the refusal of an unset `[credits].service_url` stays, run with the storefront's other
      configuration refusals. `settings.toml`, `storefront.credits.toml`, and
      `docs/cookbooks/vllm-apicredits-seller.md` lose `[credits].fail_on_unreachable` and
      `preflight_timeout`; the storefront refuses both by key, as it refuses
      `claims_sweep_interval`. `tests/unit/test_server_composition.py` stops patching the
      preflight (D20).
      Done; an unset `service_url` is refused before the signer or database, with the
      capacity refusals.
- [x] 11.5 Degraded start (application integration through the typed clients): VM
      `tests/integration/test_degraded_startup.py` (new), modelled on bare metal's
      refused-registry case in `tests/test_http_system.py` — a storefront whose registry,
      provisioning site, and chain RPC all refuse connections starts, `/health` answers, and
      `StorefrontClient.get_system_status` reports the registry check failing, the site's
      projection families unknown, Alkahest unready with `alkahest.chain_unreachable`, and
      the publication cycle failed, with no listing closed; once the chain answers, a stepped
      `alkahest-chain-probe` makes Alkahest ready without a restart. The VM app is built by
      `build_vm_storefront_app` over `VmCompositionSeams` whose `alkahest_json_rpc` and
      `alkahest_client_constructor` are test stubs, the stub switched to answering before
      the stepped probe, with no module patch: this is the started-application test of
      VM's probe wiring that `test_alkahest_chain_probe_composition.py` stands in for
      (122 F4, the residue of 85 F3), which stays as the composition's unit test. API credits
      `tests/integration/test_lifecycle_status.py`: it starts with its credits service
      unreachable and `listing-seed` waits (D20, D19).
      Done. VM: the real app's full lifespan starts with every dependency refused; status
      reports the registry `unreachable` and the storefront `degraded`, both site
      families `unavailable`, Alkahest unready for reachability; a stepped probe makes it
      ready without a restart. The publication cycle completes rather than failing,
      holding the unloaded site and closing nothing; decision 20 states this (triage 139
      F3). API credits: started with its credits service refused, `listing-seed` waits
      (`credits_service_unanswered`), status `degraded`. Recovery once each dependency
      answers is shown by VM's registry-refused publication test, VM's site-failure round,
      and API credits' seed completing (Section 11 notes).
- [x] 11.6 The `deployment-state` delta: the permanent requirement "A storefront chart
      passes service configuration through" still permits a chart to wait for a configured
      chain's RPC or the internal registry before the storefront starts, which D20 and the
      delta's added requirement forbid. Add to `specs/deployment-state/spec.md` a MODIFIED
      block for that requirement, copied whole with that example removed, so the archive
      leaves no contradiction; `openspec validate unbacked-bare-metal-listings --strict`
      passes (D20; a correction of the delta to the reviewed decision).
      Done: the block drops the whole sentence permitting a Kubernetes decision from the
      configuration, waiting being its only instance; strict validation passes.
- [x] 11.7 Versions: `arkhai-vms-storefront`, `arkhai-apicredits-storefront`; the chart
      versions per the charts' own convention; `make lock`.
      Neither package moves (already bumped once against `dev`); the storefront chart and
      the umbrella go 0.3.0 → 0.4.0.
- [x] 11.9 One derivation of release conditions for published escrows (122 F2). The rule
      "derive a condition for every published Alkahest escrow's chain, only while the
      readiness it was published under reports Alkahest ready" is written three times:
      VM's `publication_terms.demands_for_published_escrows`, API credits'
      `SettlementComposition.release_conditions` with its `alkahest_ready`, and bare metal's
      `_release_conditions` through `kit/alkahest`'s `publication_release_conditions` over
      its clauses. Add to `kit/alkahest/src/market_alkahest/release_conditions.py`
      `escrow_release_conditions(config, accepted_escrows, *, readiness, chains,
      wallet_address)`, returning nothing unless Alkahest is ready and otherwise one
      condition per chain the escrows name, through `release_conditions` (which refuses an
      unconfigured chain); export it, and remove `publication_release_conditions` and its
      export. VM's `listing_service.py`, API credits' composition (its
      `release_conditions` method stays as the seam and calls the kit), and bare metal's
      `settlement_composition.py`, passing its accepted escrows, call it;
      `demands_for_published_escrows` goes, and `alkahest_ready` unless something else
      reads it. Tests: the kit unit cases of `publication_release_conditions` move to the
      new function, with an unready readiness and an unconfigured chain; each domain's
      existing case that an unready Alkahest advertises nothing stays and now covers the
      shared rule. `design.md` decision 19's sentence naming the three callers of
      `publication_release_conditions` is corrected to the new function. No version bump:
      each package already carries this change's (`docs/development/RELEASING.md`).
      Done; bare metal passes the escrows its ready clauses built; `alkahest_ready` stays
      for API credits' supplied escrows. Kit unit cases as listed.
- [x] 11.8 **Verify.** `make -C helm test-render` (chart render); `make test-storefront`,
      `make test-apicredits`; for 11.9, `make -C kit test-alkahest` and
      `make test-bare-metal`; `make test`; `make check-packaging`. End-to-end: every VM-lane
      and API-credit-lane scenario starts on the changed startup. The local Helm topology
      run of D14 — `make helm-topology-up` and `make helm-topology-check` on this round's
      commit, no init containers on the VM storefront — is the maintainer's at this round's
      validation, recorded unrun if not done.
      Passed: the chart render (Helm v3.21.0, then v4.3.0, the CI pin, in Section 11's
      corrections), the storefront, API-credit, kit, and bare-metal suites, and `make
      test` by its targets. The local Helm topology run is the maintainer's and is unrun
      here. Validation 140 passed the round.

Section 11 notes:

- Corrections, on uv 0.11.17, Helm v4.3.0, and Node 22: `make helm-values-schema`
  regenerated every schema byte-identical to the committed files; a provisioning dotenv
  test whose `.env` discovery an ancestor directory could shadow now roots discovery at
  its own directory; a release-tooling test that depended on file modification times sets
  them; `aa00b15` relocked the locks an environment refresh had rewritten, with no version
  resolved differently (triage 139 F4).
- Recovery after a degraded start, each at application integration: VM's
  `test_a_listing_every_registry_refused_is_published_once_they_answer`, VM's
  `test_a_round_refused_while_the_site_fails_succeeds_once_it_answers`, API credits'
  `test_the_seed_completes_once_the_credits_service_answers`, and the existing
  `test_a_site_with_no_projection_holds_its_listings_and_its_override_is_unknown`.
- Round 2's triage, 139 F1 (decision 20): no Alkahest client is built at startup; the probe
  constructs each at its first step, and a settle for a configured chain without a client
  yet answers 503. Tests: a degraded start per storefront with a constructor that never
  returns, each answering its health check and reporting `alkahest.chain_unreachable`;
  unit cases of the 503. 139 F5 and F7: the API-credit degraded-start assertions and
  comments.
- In the API-credit storefront's tests, overriding a dotted key such as `capacity.sites`
  through `settings_overrides` leaked into later tests; replacing `[capacity]` whole and
  restoring it does not.

## 12. Helm test pods carry no workload selector label

Delivers a test-labels helper in every chart and a topology render assertion (D21;
`deployment-state` "Helm test pods carry no workload selector labels"). Touches
`helm/charts/*` and `helm/tests/test_release_topology.py`.

- [x] 12.1 A `<chart>.testLabels` helper in each chart's `templates/_helpers.tpl` —
      `registry`, `storefront`, `provisioning`, `e2e-tests`, `validate-contracts`,
      `bare-metal-storefront` — carrying chart, version, managed-by, instance, and
      `app.kubernetes.io/component: test`, never `app.kubernetes.io/name` (D21).
      Done; each helper's comment states why `name` is left out.
- [x] 12.2 Each chart's test Pod takes it, under `helm/charts/`:
      `registry/templates/tests/registry-environment-test.yaml`,
      `storefront/templates/tests/storefront-environment-test.yaml`,
      `provisioning/templates/tests/provisioning-smoke-test.yaml`,
      `helm/charts/e2e-tests/templates/tests/e2e-deal-test.yaml`,
      `validate-contracts/templates/tests/chain-environment-test.yaml`, and
      `bare-metal-storefront/templates/tests/health-test.yaml`, which also gains
      `"helm.sh/hook-delete-policy": before-hook-creation` as the others have (D21).
      Done; these six are every `helm.sh/hook` the chart templates hold.
- [x] 12.3 `helm/tests/test_release_topology.py` (chart render): over both topology releases,
      parse each Deployment's `spec.selector.matchLabels` and each Pod annotated
      `helm.sh/hook: test` in either quoting; assert no such Pod carries all of any
      Deployment's `matchLabels`, and each carries `component: test` and no `name`.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts the delete policy
      (D21).
      Done (chart render): `test_no_test_pod_carries_a_workload_selector` also reads every
      Service's selector (139 F6), ties the test pods to each chart's `templates/tests/`,
      and asserts each release's expected test templates; each assertion was broken once
      and seen to fail. It reads YAML with the standard library, so a label rendered as a
      flow mapping would read as absent; none is.
- [x] 12.4 **Verify.** `make -C helm test-render`; `make test`; `make check-packaging` if a
      chart version changed. End-to-end: the Helm topology check of 11.8 runs every test Pod;
      no compose scenario covers chart labels, and none is owed.
      Passed: the chart render and `make check-packaging`. The bare-metal chart is 0.4.0
      (triage 139), its values schema accepting the probe settings; the other charts change
      only test templates.

## 13. Scenarios hold shared services for the whole module

Delivers one hold mechanism for every lane (D22; `test-compatibility` "Scenarios hold shared
services for the whole module"). Touches `e2e-tests/` and, for the gate state a hold waits
on, the provisioning service's two pause routes.

- [x] 13.1 The provisioning service's fulfillment-convergence and lease-watchdog pause
      routes answer whether the loop is at its gate (waiting on its resume event with no
      cycle in flight), as the storefront's lifecycle pause reports each loop's gate state:
      the delta requires a hold to wait until each held loop reports itself paused at its
      gate, and these routes report only the flag. `src/controllers/system_controller.py`
      and the two watchdogs expose it; `compute_provisioning_contracts/routes.py` and the
      async and sync `compute_provisioning_client` methods return it. Tests: unit for each
      watchdog's gate state with a cycle in flight and idle; application integration per
      route through `ProvisioningClients`. The proposal's Impact "Wire" bullet names the
      field (D22).
      Done: each watchdog counts its timer cycles past the gate and reports `is_at_gate`;
      an explicit cycle does not count. The routes answer the new
      `WorkerPauseResponse(paused, at_gate)`, which the clients return. Unit tests hold
      each cycle on an event; `TestWorkerControls` through the typed client.
- [x] 13.2 `e2e-tests/tests/e2e/roles/helpers/compute_deal.py`: one helper per pause kind —
      storefront lifecycle loops (from `pause_storefront`), fulfillment convergence (from
      `convergence_paused`, which stops swallowing a failed pause), and the lease watchdog
      (new) — each pausing, waiting until every held loop reports itself at its gate,
      yielding, and resuming in a `finally`; their docstrings state the module-hold rule
      (D22).
      Done: `storefront_loops_held`, `fulfillment_convergence_held`, and
      `lease_watchdog_held` over one `_until_held`, bounded by `HOLD_TIMEOUT_SECONDS` (60);
      the `finally` covers the wait as well as the module.
- [x] 13.3 Module-scoped lane fixtures built only on those helpers: `scenarios/vms/conftest.py`
      — Bob's loops, Alice's loops (Alice's admin client moves here from
      `test_multi_registry.py`), convergence, and the lease watchdog;
      `scenarios/bare_metal/conftest.py` — the storefront's loops (replacing
      `bare_metal_loops_held`), convergence, and the lease watchdog. API-credit scenarios
      hold nothing today, so that lane gains a fixture only when a module needs one (D22).
      Done, one set of fixture names across both lanes, with `alice_loops_held` in the VM
      lane.
- [x] 13.4 Every module that paused or resumed takes its holds with `usefixtures`, listed
      first: `vms/test_full_deal.py`, `test_full_deal_buyer_cli.py`,
      `test_buy_oneshot_buyer_cli.py`, `test_listing_shapes.py`,
      `test_compute_dynamic_listings.py`, `test_multi_registry.py`,
      `test_non_erc20_settlement.py`, `test_vm_introduction.py` (its own `held_loops` goes),
      and `bare_metal/test_bare_metal_mock_deal.py`, `test_bare_metal_publication.py`,
      `test_bare_metal_introduction.py`. `helpers/compute_deal_stages.py`'s
      `Stage00_LifecyclePause` and each module's own Stage00 assert the hold through system
      status; Stage 10a and 11b assert the lease-watchdog fixture's state instead of pausing
      and resuming. `ensure_storefront_resumed`, which resumes the trading pause, stays
      (D22).
      Done. The shared stage is `Stage00_LifecycleHeld`; stages read holds back live
      through system status (decision 22). The VM lane's cleanup fixtures are no longer
      autouse and every module lists them after its holds, so the holds are released last;
      `tests/unit/test_scenario_cleanup_order.py` reads the fixture order pytest resolves.
- [x] 13.5 Source check (unit): `e2e-tests/tests/unit/test_scenario_holds.py` (new) walks
      every `tests/e2e/roles/scenarios/**/test_*.py` and the stage helpers with `ast` and
      fails, naming file and line, on any call of `admin_pause_lifecycle_loops`,
      `admin_resume_lifecycle_loops`, `pause_fulfillment_convergence`,
      `resume_fulfillment_convergence`, `pause_lease_watchdog`, `resume_lease_watchdog`, or
      a pause helper outside the hold helpers and lane conftests;
      `tests/unit/test_compute_deal_stages.py`'s shared-name and field checks follow
      Stage00's change (D22).
      Done, over every scenario and helper file but the hold helpers' bodies: a reference
      to a pause operation or hold helper by name, attribute, import, alias, or `getattr`
      string, and any string naming a pause or resume route path (139 F6). A route
      assembled from pieces naming no route is not caught.
- [x] 13.6 Versions: `arkhai-compute-provisioning-contracts`,
      `arkhai-compute-provisioning-client`, the provisioning service, `arkhai-e2e-tests`;
      `make lock`.
      Done, with `arkhai-compute-provisioning` for `is_at_gate`; `arkhai-e2e-tests` stays at
      0.3.0 (triage 139).
- [x] 13.7 **Verify.** `make test-e2e-unit` (unit); `make test-provisioning`; `make test`;
      `make check-packaging`. End-to-end: every lane's scenarios run on the holds
      (`make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal`, `test-e2e-apicredits`), and
      after `make helm-topology-check` Bob's loops report running (the maintainer's, 11.8).
      Passed: e2e-tests unit with the source check and `test_hold_helpers.py`, the
      provisioning suites, `make test`, and `make check-packaging`. The eleven held
      modules' scenarios are the end-to-end evidence (validation 140); the Helm topology
      check is the maintainer's, unrun here.

Section 13 notes:

- Round 2's triage, 139 F2: both watchdog gates read the resume event again after each
  wake, so a pause straight after a resume holds the cycle the resume woke (unit, broken
  once). The round's evidence on the final tree: one uninterrupted `make test` passed
  every suite but the Helm render (no `helm` in the triage session); validation 140
  passed the round.

## 14. The delegate decides delivery terms

Delivers the backing delegate's two delivery-term operations (D5, D1;
`resource-pool-management` "Capacity backing is interpreted by one delegate"). Touches
`kit/resource-pools-contracts`.

- [x] 14.1 `kit/resource-pools-contracts/src/market_resource_pools_contracts/backing.py`:
      `CapacityBacking.carry_delivery_terms(terms)` — backed returns the terms as given,
      unbacked returns none — and `delivery_term_constraints(terms)` — backed refuses a
      term that is not present, unbacked refuses one that is — beside
      `admissible_settlement`, on the delegate's own state as its other operations are. One
      presence rule: neither absent nor `None`; a string or collection non-empty; a boolean
      present as `True` or `False`. A refusal names every offending term (D5).
      Done: `delivery_term_constraints` takes a mapping of every term the domain names and
      raises `DeliveryTermsError` (a `ValueError` naming the terms), so a pydantic
      validator reports it; a term left out of the mapping is unchecked, so each domain
      passes all of its named terms.
- [x] 14.2 Tests in `kit/resource-pools-contracts/tests/unit/test_backing.py` (unit): each
      delegate's operations over present, absent, `None`, empty-string, empty-list, and
      `False` terms (D5).
      Done (unit).
- [x] 14.3 Version: `arkhai-kit-resource-pools-contracts`; `make lock`.
      0.2.0 → 0.3.0.
- [x] 14.4 **Verify.** `make -C kit test-resource-pools-contracts`; `make test`; `make
      check-packaging`. End-to-end: none alone; Sections 15–19 and 22's scenarios.
      Passed: the kit's unit suite, every Python suite of `make test` (the Helm render
      unrun, no `helm`), and `make check-packaging`.

## 15. The bare-metal carrier validates delivery terms against its pool's backing

Delivers the listing and view models without host defaults, and the shared carrier's
validation by its pool's backing (D5, D6; `storefront-publication` "A bare-metal listing
carries delivery terms only when backed", "A bare-metal listing sells one whole unit";
`physical-provisioning` "A bare-metal publication view is built from its capacity
declaration"). Touches `domains/bare_metal/src/arkhai_bare_metal/` and the two bare-metal
storefront call sites of the reader.

- [x] 15.1 `schema.py` `BareMetalListing`: `host_id` and `physical_host_id` optional;
      `access_methods` optional with its `["ssh"]` default removed; the validator checks
      structure and applies its backing's `delivery_term_constraints` to `host_id`,
      `physical_host_id`, and `access_methods` (D5).
      Done; the terms are named once, `BARE_METAL_LISTING_DELIVERY_TERMS` and
      `BARE_METAL_VIEW_DELIVERY_TERMS` (adding `available`), and every named term is
      passed to the delegate.
- [x] 15.2 `projections.py`: `BareMetalResourceProjection`'s `host_id`, `physical_host_id`,
      `available`, and `access_methods` optional, no default, structure checks only.
      `TrustedBareMetalResource` gains `capacity_backing`; given a label, its validator
      applies that delegate's `delivery_term_constraints` to the four terms beside the
      `pool_id` containment check; with none, no term check runs (D6).
      Done.
- [x] 15.3 `publication.py` `trusted_bare_metal_projection(*, site_id, projection,
      backings)`: each resource is validated with its pool's resolved label, or none where
      the pool is absent from `backings`; a violation refuses the generation as every
      malformed view does. `available_bare_metal_listings` passes on only the terms a view
      carries, and availability is read only for a backed pool (D6, D3).
      Done; availability was already read only through the delegate's `judge`.
- [x] 15.4 `fixtures/publication_view.py`: `build_bare_metal_publication_view` builds an
      unbacked view; `validate_bare_metal_publication_view` takes the backing and validates
      through the carrier, so both sides of the boundary test against one rule (D6).
      Done; the builders take a `backing` and carry terms through its delegate, and the
      listing fixture states `access_methods`.
- [x] 15.5 The storefront's two readers, `src/publication.py` `_classify_site` and
      `src/listing_source_check.py` `build_listing_source_check`, call `read_site_pools`
      before `trusted_bare_metal_projection` and pass `backings=reading.backings` (D6).
      Done; the pool reading sits inside the generation's refusal, so a malformed pool row
      holds the site.
- [x] 15.6 Tests: unit `domains/bare_metal/tests/test_schema.py`, `test_projections.py`, and
      `test_publication.py` — an unbacked listing or view with no terms valid and with any
      term refused, a backed one missing a term refused, `available=False` valid when
      backed, an unchecked pool absent from `backings`, no `access_methods` default, one
      inconsistent view refusing the generation. Library `tests/test_publication_cycle.py`
      and application integration `tests/test_http_negotiation.py` (through
      `StorefrontClient`) in the storefront: a generation whose backed view lacks
      `available` is held as `site_projection_refused` with the validation error, in a
      cycle and at an opening (D6).
      Done as listed. The cycle tests hold the site as `site_projection_refused` with the
      error text for a backed view missing `available`, an unbacked view naming a host, and
      a malformed pool row; the opening is refused 503 `listing_source_unverifiable`, the
      validation error reaching only the seller's log.
- [x] 15.7 Versions: `arkhai-bare-metal`, `arkhai-bare-metal-storefront`; `make lock`.
      `arkhai-bare-metal` 0.12.0 → 0.13.0, on the contracts 0.3.0; the storefront and the
      provisioning service's dev group raise their floors.
- [x] 15.8 **Verify.** `make test-bare-metal`; `make test`; `make check-packaging`.
      End-to-end: `e2e_bare_metal_publication` and `e2e_bare_metal_mock_deal` show backed
      views and listings unchanged.
      Passed: `make test-bare-metal`, `make test`'s suites, and `make check-packaging`.
      Backed views and listings keep their bytes.

## 16. Resource views receive their pool's context and never fail the projection

Delivers the pool context in the contributed-view seam, the bare-metal view builder through
the delegate and the carrier, and `publication_view_problems` carried to storefronts (D3,
D4; `physical-provisioning` "Domains contribute their inventory views", "A bare-metal
publication view is built from its capacity declaration"). Touches
`provisioning/compute` (`compute_provisioning`), the provisioning service, the VM and
bare-metal provisioning adapters, `kit/site`, and `kit/site-client`.

- [x] 16.1 `provisioning/compute/src/compute_provisioning/inventory_views.py`: a frozen
      pool-context type (pool ID, provider, resolved `PoolDeclarations`);
      `resource_views(declaration, *, pool)` returns the views it built and the problems,
      keyed by view identifier, that kept it from building one; the composer merges both
      and applies `_check_declared` to problem keys too. Export it.
      `provisioning/compute/pyproject.toml` declares `arkhai-kit-resource-pools-contracts`.
      Tests in `provisioning/compute/tests/unit/test_composition.py` (unit) (D4).
      Done: `InventoryPoolContext` and `ResourceViews(views, problems)`; the composer also
      refuses a view both built and unbuildable. Unit passed.
- [x] 16.2 The provisioning service, `src/services/capacity_inventory.py`: one row-to-context
      function, through `resolve_pool_declarations`, serves `load_capacity_pool_metadata`
      and the resource pass; `load_capacity_resource_inventory` reads the `ResourcePool`
      rows through the session factory (`main.py`'s call site passes it), resolves each pool
      once, passes each declaration its pool's context, and sets
      `publication_view_problems` on a projected resource that has any; a resource whose
      pool has no row gets no context and no view. Tests: unit
      `tests/unit/services/test_capacity_inventory.py` and
      `test_vm_inventory_views.py`; application integration `tests/integration/test_capacity_api.py`
      through the typed client — an unbacked pool's host-less declaration projects a
      `bare_metal.v2` view with no delivery terms, a host-bearing declaration in an unbacked
      pool projects none either, and a malformed declaration projects without its view and
      with a problem while every other pool still projects (D3, D4).
      Done; the pool-metadata pass does not use the context function (decision 4's
      Section 16 paragraph). Application integration:
      `test_bare_metal_views_follow_each_pools_backing_and_problems_stay_local`.
- [x] 16.3 VM adapter `domains/vms/provisioning/adapter/.../inventory_views.py`: the new
      signature and return shape (D4).
      Done.
- [x] 16.4 Bare-metal adapter `domains/bare_metal/provisioning/adapter/.../inventory_views.py`
      `BareMetalPublicationViews.resource_views`: delivery terms through the pool's
      `carry_delivery_terms`; the view built through `TrustedBareMetalResource` with the
      pool's label; the no-host rule a problem for a backed pool only; a missing or invalid
      `allocation_mode`, a missing `physical_host_id`, missing access methods, or a
      private-looking key a problem rather than a raise. Its `pyproject.toml` declares
      `arkhai-kit-resource-pools-contracts`. Tests in its `tests/test_inventory_views.py`
      (unit): unbacked with and without a host; each problem; nothing raises (D3, D4, D5).
      Done, with no branch on backing: terms through the delegate, the view validated
      through the carrier, a validation error becoming the view's problems; a backed view's
      bytes unchanged. The source reads the delegate off the context, so the contracts are
      declared in the adapter's dev group only.
- [x] 16.5 `kit/site/src/market_site/projections.py` `resource_pool_projection` copies
      `publication_view_problems` when present, uninterpreted, as it copies
      `publication_views`; `kit/site-client/.../fixtures/resource_pools.py`
      `build_projected_resource` and `validate_resource_pool_projection` carry and check it.
      Tests in `kit/site/tests/unit/test_projections.py` and
      `kit/site-client/tests/unit/test_resource_pool_fixture.py` (unit) (D4).
      Done; the fixture checks only the field's form.
- [x] 16.6 Versions: `arkhai-compute-provisioning`, the two adapters, the provisioning
      service, `arkhai-kit-site`, `arkhai-kit-site-client`; `make lock`.
      Done under the one-bump rule; `docs/development/RELEASING.md` names
      `compute_provisioning`'s new internal dependency.
- [x] 16.7 **Verify.** `make test-compute-provisioning`, `make test-provisioning` (with the
      mock profile), `make -C domains test-provisioning-adapter`, `make -C kit test-site
      test-site-client`; `make check-architecture` (the new
      `compute_provisioning` → contracts edge is permitted); `make test`; `make
      check-packaging`. End-to-end: every bare-metal-lane scenario reads views through the
      changed resource pass.
      Passed: the suites named, `make test` (a VM `test_introduction_origins` failure after
      a slow registry publication passed on rerun), and `make check-packaging` with its
      architecture rules.

Section 16 notes:

- The resource-pool projection's `publication_view_problems` is specified in the
  `physical-provisioning` delta, while `site-capacity` owns the projection and its
  `publication_views` convention.
- A rebuilt wheel keeps its version, so after reverting an edit to a wheel's source, run
  `make lock` or `make dist` again before trusting a suite.

## 17. One site-derivation log for both compute storefronts

Delivers the kit-owned site-derivation log, one status shape, and logging on change (D10;
`storefront-publication` "A compute storefront reports and logs its site derivation").
Touches `kit/capacity-publication`, `core/storefront`'s and `core/storefront-client`'s
status models, `domains/vms/listings`, and the VM and bare-metal storefronts.

- [x] 17.1 `kit/capacity-publication/src/market_capacity_publication/cycle.py`: a
      site-derivation log keyed by publication source and site, recording a site's
      summary — `holds`, `refusals`, `reports`, each entry a reason code with its pool or
      Physical Resource and detail — only from a real cycle; logging an entry as a warning
      when it first appears and at info when it clears; a site absent until a cycle derives
      it. Export it. Tests in `kit/capacity-publication/tests/unit/test_cycle.py` (unit,
      `caplog`): appear, stand, clear, previews unlogged and unrecorded, two sources kept
      apart (D10).
      Done: `SiteDerivationLog.record(source, report, site_ids)` ignores a previewed
      report; `latest()` merges every source's entries per site. Error text is not part of
      an entry's identity, and a site held whole keeps its last entries (decision 10).
      Unit cases as listed, plus the held-site carry-forward and summarized structured
      detail.
- [x] 17.2 VM: `domains/vms/listings/.../reconciler.py` loses the module dictionary,
      `_record_site_report`, and the `record_reports` flag, keeping the `reports=`
      out-parameter; `services/publication_loop.py` converts a real cycle's reports to
      entries (`regionless_pools` a `pool_region_missing` hold, `retired_pricing_keys` a
      report naming the keys, and so on) and records them in the log, which `container.py`
      holds and `services/system_service.py` serves; listing-source checks, capacity-event
      reconciliation, and failure actions record nothing (D10).
      Done. `reconciler.site_derivation_entries(report)` converts VM's categories: holds
      `pool_unresolvable`, `member_gpu_count_unreadable`, `member_resource_type_missing`,
      `listing_shapes_unreadable`, `asking_rates_unreadable`, `family_rates_unreadable`,
      `pool_region_missing`; reports `legacy_producer_backing`, `member_gpu_count_missing`,
      `listing_shape_inadmissible`, `shape_constraints_unusable`,
      `asking_rate_shape_unpublished`, `listing_shape_infeasible`,
      `claimed_attribute_undeclared`, `retired_pricing_keys`, `families_without_rates`.
      The run-cycle report carries the same entries, so its counts include `report`
      actions.
- [x] 17.3 Bare metal: `src/publication.py`'s `SiteDerivation` and `PublicationDerivation`
      give way to the kit log, with its per-cycle log lines (`_classify_site`,
      `_hold_unbounded_pools`, `_hold_pools_without_clauses`, `_report_pools`) removed;
      `runtime.py`, `lifecycle_steps.py` (no clearing at cycle start: a cycle that fails
      before deriving a site leaves that site's last derivation, which status keeps
      reporting), `publication_composition.py`, and `models.py` follow (D10).
      Done; the cycle records after its run stage, and pools held whole are held once per
      reason with their problems (decision 10's Section 17 paragraph).
- [x] 17.4 `core/storefront/.../models/system_models.py` and
      `core/storefront-client/.../models.py`: `publication_derivation` is the shared shape,
      its comment describing the entries rather than VM's categories (D10).
      Done; exercised through the VM storefront's status reads.
- [x] 17.5 Tests: VM `tests/integration/test_publication_loop.py`,
      `test_pool_overrides_api.py`, `test_reconciler_projection.py`,
      `test_reconciler_derivation.py`, `_reconciler_cases.py`, and unit
      `tests/unit/test_reconciler.py` follow the shape and the out-parameter; bare metal
      `tests/test_http_system.py` and `test_publication_cli.py`. Application integration
      through `StorefrontClient` in both: a regionless pool reported under the site's
      `holds` as `pool_region_missing` alike in VM and bare metal; a preview changes
      nothing; a site absent before its first cycle; a listing-source check records nothing
      (D10).
      Done. VM: `test_only_a_publication_cycle_records_a_sites_derivation` (absent before
      any cycle, after a capacity-event step and a preview, present after a cycle), the
      regionless hold, a legacy producer, entries for shape findings and an unreadable
      rate. Bare metal: `test_a_regionless_pool_is_logged_once_and_reported_until_it_clears`,
      and a failed cycle leaving the last derivation. The listing-source check is shown
      through capacity-event reconciliation, which derives through the same functions.
- [x] 17.6 Versions: `arkhai-kit-capacity-publication` (exact pins in both storefronts),
      `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-vms-listings`, both
      storefronts; `make lock`.
      `arkhai-kit-capacity-publication` 0.11.0, its exact pins moved in the three
      storefronts and the provisioning service's dev group; the rest already bumped once.
- [x] 17.7 **Verify.** `make -C kit test-capacity-publication`; `make test-core`; `make
      test-vms-domain`, `make test-storefront`, `make test-bare-metal`; `make test`; `make
      check-packaging`. End-to-end: `e2e_compute_dynamic_listings`, `e2e_listing_shapes`,
      and `e2e_bare_metal_publication` read status after publication.
      Passed: every Python suite of `make test` (the Helm render unrun, no `helm`) and
      `make check-packaging`. No scenario reads `publication_derivation`; the named
      scenarios exercise the cycles that record into the log, and 17.5 is the evidence
      for the shape.

## 18. A candidate with no settlement option yields no listing; an open one closes or is held

Delivers the typed refusal, the classification of the admissible clauses' mechanisms, and the
runner's close hook, for VM and bare metal (D7; `storefront-publication` "A compute candidate
with no settlement option yields no listing", "Publication derives all ready settlement
options"). Touches `core/storefront`'s publication runner and sources, and the VM and
bare-metal storefronts.

- [x] 18.1 `core/storefront/src/core_storefront/publication_runner.py`: a typed refusal a
      payload builder may return, stating whether every mechanism is ruled out by
      configuration; `publish_round` calls the source's close hook for such a refusal and
      otherwise reports it, leaving the listing as it is, as every other payload failure.
      `publication_sources.py` `PublicationSource` gains the close hook, with a default
      that closes nothing. Tests in `core/storefront/tests/unit/test_publication_runner.py`
      and `test_publication_sources.py` (unit) (D7).
      Done: `NoSettlementOption(detail, *, mechanisms, unknown)`, a `ValueError`, with
      `ruled_out_by_configuration`; the runner passes `NO_SETTLEMENT_OPTION` to
      `PublicationSource.close_candidate_listing`, and a raising hook is reported as the
      candidate's failure. Unit passed.
- [x] 18.2 Bare metal `src/publication_composition.py` `publication_payload_builder`: the
      untyped `ValueError` becomes the typed refusal, raised too when the payload carries no
      settlement option and no accepted escrow; the mechanisms of the admissible clauses
      (override, or configured clauses, after `admissible_settlement`) are classified from
      the readiness `settlement_composition.publication_payload` evaluated — ruled out by
      configuration, or unknown when every blocker is a reachability blocker — and an empty
      admissible set is the refusal with every mechanism ruled out. `src/publication.py`
      `_build_payload` records it with its site, pool, and Physical Resource at the top level
      and returns it; the source's close hook closes the candidate's open listing through
      `_reconciliation_close` as `no_settlement_option`; `_hold_pools_without_clauses` gives
      way, since a pool resolving no clause is a candidate whose every mechanism is ruled
      out, which closes (D7).
      Done. A mechanism is unknown by `MechanismReadiness.unknown`; a disabled section, or
      a ready mechanism building no option, is ruled out. Recording and the close hook are
      the kit's `RefusedCandidates` (18.3); a dry run records its close without applying
      it.
- [x] 18.3 VM `services/listing_service.py` (`_admissible_settlement_terms`,
      `derive_listing`) keeps the readiness `publication_artifacts` returns and raises the
      typed refusal; `services/publication_loop.py` `_create_request`'s no-clause case is the
      same refusal; `_build_payload` records it with site, pool, and resource; VM's close
      hook finds the open listing by the candidate's derivation key and closes it through
      `_reconciliation_close` (D7).
      Done, as decision 7's Section 18 paragraph records: `publication_artifacts` returns
      empty artifacts with their readiness; `_create_request` refuses a candidate resolving
      no clause and drops a clause naming a disabled mechanism; the close hook finds the
      listing by `publication_binding.vm_candidate_derivation_key`. Shared by both domains:
      `MechanismReadiness.unknown` in `kit/settlement-runtime`, and
      `kit/capacity-publication`'s `RefusedCandidates` with `record_payload_refusal` and
      the reason codes `settlement_mechanism_unknown` and `payload_unbuildable`, recording
      every refusal under its site at the top level. Every clause is read through
      `parse_settlement_publication_clause`, so for every consumer a non-mapping
      `mechanism_input` is refused and a malformed clause fails before its mechanism's
      enablement is judged. API credits keeps its own `_unknown` predicate.
- [x] 18.4 Both storefronts' adapters (`arkhai_bare_metal/storefront_adapter.py`,
      `arkhai_vms/storefront_adapter.py`) pass the hook into the source (D7).
      Done; the hook is a required adapter argument in both. Unit passed.
- [x] 18.5 Tests: bare metal `tests/test_publication_cycle.py` (library) and VM
      `tests/integration/test_publication_loop.py` (application integration, through
      `StorefrontClient`): an open listing whose only mechanism is configured away closes as
      `no_settlement_option` and reopens under its identity when it builds again; one whose
      only mechanism's chain is unprobed is held with its terms; a pool override leaving no
      admissible clause closes; an unknown mechanism outside the admissible clauses holds
      nothing; a contact-only candidate whose origin has no contact yields no listing. Bare
      metal `tests/test_http_system.py`'s no-clause hold test becomes the close. VM
      `tests/unit/test_unbacked_settlement_options.py` (unit) follows the typed refusal (D7).
      Done; the bare-metal cases on unbacked candidates are 19.6's carried tests.
      - VM, application integration over the publication harness: configured away, a
        disabled mechanism (as a pool hint and as the storefront's own configured clause),
        and no clause each close and reopen under the same identity; unreached is held with
        its terms, and refused with no open listing; both kinds close; unreached beside a
        contact exchange with no contact is held; a stored override naming only Alkahest
        closes an unbacked contact listing and restoring it reopens; an unbacked
        contact-only candidate with no contact yields no listing. Blockers come from the
        harness's settlement double; DSL clause text is unit-proven
        (`test_enabled_publication_clauses.py`, `test_config_loader.py`).
      - Bare metal, cycle orchestration over a real database with the production payload
        builder and settlement composition (not integration evidence under `TESTING.md`):
        the same cases on backed candidates, a preview applying no close. Application
        integration through `StorefrontClient`: the no-clause close and same-identity
        reopen across restarts (`test_http_system.py`), and an unbacked listing published
        by the app's own cycle (`test_http_introductions.py`, Section 20).
- [x] 18.6 Versions: `arkhai-core-storefront`, `arkhai-bare-metal`, `arkhai-vms`, both
      storefronts; `make lock`.
      `arkhai-vms` 0.6.1 → 0.7.0, the rest already bumped once; floors on
      `arkhai-core-storefront` rise to 0.16.0 for the close hook. The locks are kept as the
      pinned uv generated them, dependency markers included, by the owner's decision.
- [x] 18.7 **Verify.** `make test-core`; `make test-vms-domain`, `make test-storefront`,
      `make test-bare-metal`; `make test`; `make check-packaging`. End-to-end:
      `e2e_compute_dynamic_listings` and `e2e_bare_metal_publication`; no scenario closes a
      listing for configuration, and integration is the evidence.
      Qualified on the tree committed with Sections 18 to 22, with the checks of all five
      run together: `make test` passed every suite up to the Helm render (no `helm`),
      `make check-packaging` and `make check-change` passed. End-to-end evidence is the
      round's validation.

Section 18 notes:

- Three fresh-context checks; their findings are taken up in decision 7's Section 18
  paragraph and the deltas: the permanent "A storefront that cannot publish refuses to
  start" and the `settlement-configuration` scenario "No enabled mechanism is ready" are
  modified, the stale permanent passages are 23.9's, and a failed open-listing lookup is a
  reported hold rather than ending the cycle.
- The owner authorized committing Section 18 and continuing Sections 19–22 while
  `make check-change` failed only on the citation of
  `e2e-tests/tests/e2e/roles/helpers/introduction_stages.py`, which 22.1 creates; it
  passed once that file existed.
- A VM integration test once reported a registry health check `timeout` for
  `unreachable`; round 3's triage (160 F1) found the cause, a real request to the
  harness's `registry-a.test` URLs, and the harness now answers the probe through an
  injected transport.

## 19. Bare metal publishes unbacked listings

Delivers unbacked bare-metal derivation through the shared runtime, its recheck, and the
removal of the unbacked refusal (D1, D2, D3, D8, D11, D13, and D5's readers;
`storefront-publication` "Bare-metal publication derives unbacked listings", "Bare-metal
opening rechecks its listing against its source", "A bare-metal listing carries delivery
terms only when backed"; the removed "An unbacked pool yields no bare-metal listing";
`registry-discovery` "Compute listings publish their capacity backing"). Touches
`arkhai_bare_metal` and the bare-metal storefront.

- [x] 19.1 Delete `SitePoolReading.unbacked`, `read_site_pools`'s unbacked branch, and
      `_report_pools`' `pool_unbacked` report (`src/site_reading.py`, `src/publication.py`)
      (D11).
      Done: a pool is admitted when enabled and advertising bare metal, whatever its
      backing. Also, as the delta requires: a resource with `publication_view_problems` for
      `bare_metal.v2` is reported `publication_view_unbuildable` naming its site, pool,
      Physical Resource, and problems, the carrier keeping it in the generation's new
      `view_problems` (`BareMetalViewProblems`). An open listing of it is held, decided
      with the maintainer (decision 4's Section 19 paragraph); a disabled declaration or a
      pool no longer admitting bare metal still closes it.
- [x] 19.2 `arkhai_bare_metal/storefront_publication.py`: an unbacked candidate's dictionary,
      source envelope, and comparison sets carry no host fields; availability is never
      read for it, so an enabled, shaped resource is a candidate and a disabled one is
      withdrawn; the region, asking-rate, and override holds apply unchanged (D2, D3).
      Done; the comparison sets needed no change.
- [x] 19.3 `src/sqlite_client.py` `upsert_bare_metal_listing`: the source envelope omits
      absent host fields (D2).
      Done; a backed listing's envelope is unchanged.
- [x] 19.4 The remaining readers of the delivery terms: `src/negotiation.py`'s admission
      refusal reads absent `access_methods` as no access method listed, so a bargaining
      round against an unbacked listing is refused with
      `bare_metal_access_method_not_listed` rather than raising; confirm each other reader
      (`negotiation_runtime.py`, `deal_controls.py`, `fulfillment_service.py`,
      `settlement_service.py`, `load_bare_metal_fulfillment_context`) is reached only
      through a stage that fulfils through capacity or after Section 20's refusal, and
      record any that is not as a defect to fix here (D5).
      Done. Each reader is reached only through a stage fulfilling through capacity, the
      capacity-effects guard, or after Section 20's route order. Defect fixed: the
      administrator's settlement preview answered `would_submit: true` for an unbacked
      listing; it now asks the binding's delegate and answers `would_submit: false`. A
      bargaining round against a published unbacked listing is refused earlier, as naming
      no accepted escrow contract; the admission refusal is what a listing seeded with an
      escrow meets.
- [x] 19.5 Recheck: `arkhai_bare_metal/inventory_guard.py` is unchanged; tests confirm an
      unbacked listing is refused only by its declaration (shape, region, Physical
      Resource, or its resource now in another pool, as `declared_mismatch`), and a site
      not held or unconfirmed refuses openings as retryable for either backing (D8).
      Done; the guard gains one branch, for a resource the site built no view for
      (decision 8's Section 19 paragraph).
- [x] 19.6 Tests: unit `domains/bare_metal/tests/test_storefront_publication.py` and
      `test_inventory_guard.py` (the moved-pool case); library
      `tests/test_publication_cycle.py` — `test_an_unbacked_pool_yields_no_listing_and_is_reported`
      replaced by publication of an unbacked listing with `capacity_backing: unbacked`, no
      host fields, no `access_methods`, and only its admissible options; a withdrawn
      unbacked pool's listing closing on the next cycle (D13); application integration
      `tests/test_http_negotiation.py` through `StorefrontClient` — the unbacked recheck
      cases, and a bargaining round against an unbacked listing refused (D1, D2, D3, D8).
      Registry: `core/registry/tests/integration/test_capacity_backing_filter.py` already
      proves the exact filter; add a bare-metal listing case if it carries none.
      **Required here, carried from Section 18** (its notes): the bare-metal cycle test
      of the `storefront-publication` scenario "A pool override leaves no admissible
      clause", which Section 18 could not exercise while bare metal refused unbacked
      pools. In `tests/test_publication_cycle.py` (library), through the real pool
      override store (`SQLitePoolOverrideStore`) and the real payload builder and cycle:
      an unbacked pool's listing published and open with a contact-exchange option; a
      stored, valid, non-empty override naming only `alkahest.v1` written; the next
      cycle closes that listing as `no_settlement_option`, publishes nothing, and
      records a refusal naming its site, pool, Physical Resource, and no admissible
      mechanism; with the contact clause stored again, the next cycle reopens the same
      listing ID. Alkahest's chain unprobed throughout, so the test also shows an
      unknown mechanism the candidate cannot publish holds nothing. The override
      record's refusal of an empty clause list is unchanged. Two further bare-metal
      cycle tests are owed with it, for the same reason (Section 18 proved them only
      on backed candidates or through the payload builder): an **unbacked** candidate
      whose only admissible mechanism is contact exchange and whose origin has no
      contact yields no listing and is recorded as a refusal naming its site, pool, and
      Physical Resource ("An unbacked candidate's origin has no contact"); and an open
      unbacked contact listing whose origin loses its contact closes as
      `no_settlement_option` while Alkahest's chain is unreached ("An unreachable
      mechanism the candidate could never publish"). Section 19 is not complete
      without all three passing (D7).
      Done; each passed.
      - The three carried cycle tests (cycle orchestration over the production builder,
        composition, cycle, and database): `test_an_override_leaving_no_admissible_clause_closes_the_unbacked_listing`,
        `test_an_unbacked_candidate_whose_origin_has_no_contact_yields_no_listing`, and
        `test_an_unbacked_listing_whose_origin_loses_its_contact_closes`.
      - Cycle: an unbacked listing published `capacity_backing: unbacked` with no delivery
        term in the listing or its envelope; never judged against availability (the
        fixtures' taken case reports none of the capacity available in the site's ledger);
        closed when its pool is disabled or stops advertising; held for a missing region or
        unreadable rate; an unbuildable view reported and its open listing held.
      - Application integration through `StorefrontClient` (`test_http_negotiation.py`):
        a bargaining round against an unbacked listing refused
        `bare_metal_access_method_not_listed`; an exact contact selection accepted with no
        site call; declared mismatches (moved pool, shrunk shape, moved region) and
        retryable refusals (site not held, confirmation expired, poll failed, generation
        refused). `test_deal_controls.py`: the unbacked preview answers
        `would_submit: false`.
      - Unit: candidates and envelopes without host fields, view problems, and the unbacked
        recheck cases; the adapter's opt-in for an unbacked pool.
      - Registry (`test_capacity_backing_filter.py`, application integration): a backed and
        an unbacked bare-metal listing each found by the exact filter for its backing.
- [x] 19.7 Versions: `arkhai-bare-metal`, `arkhai-bare-metal-storefront`; `make lock`.
      Nothing owed: against `dev`, `arkhai-bare-metal` carries one minor bump (Section 15),
      covering `BareMetalViewProblems`, and the storefront 0.17.0 → 0.22.0, a minor bump
      reached through unreleased intermediate bumps, which `docs/development/RELEASING.md`
      says change nothing a release sees.
- [x] 19.8 **Verify.** `make test-bare-metal`; `make test-core` if the registry test
      changes; `make test`; `make check-packaging`. End-to-end:
      `e2e_bare_metal_unbacked_introduction` (Section 22), and `e2e_bare_metal_publication`
      for backed supply unchanged.
      Qualified with Sections 18 to 22 (18.7): `make test` (the Helm render unrun),
      `make check-packaging`, and `make check-change` passed.

Section 19 notes:

- The fresh-context check and its re-check are taken up in 19.4's and 19.6's results,
  decisions 7 and 8, and the delta (the buyer gets the reason code; the storefront's record
  names the site's problem). Declined: a kit helper for "a mechanism whose section is
  absent or disabled", one line in each of three places reading different sources.

## 20. A deal settled by introduction has no settlement or fulfillment, in both domains

Delivers the `completes_outside_settlement` stage declaration, the shared refusal in
`kit/storefront`, and the route order (D9; `storefront-publication` "A deal settled by
introduction has no settlement or fulfillment"). Touches `kit/storefront` and the VM and
bare-metal storefronts.

- [x] 20.1 `kit/storefront/src/market_storefront_kit/introduction_routes.py` (new, importing
      only `.lifecycle_routes`): the shared refusal, given the accepted stage's
      `completes_outside_settlement` and the domain's reason text, raising a
      `LifecycleRouteError` of 409 for a settle request and 404 for a fulfillment read or
      teardown; exported from `__init__.py`. Tests in
      `kit/storefront/tests/unit/test_introduction_routes.py` (new, unit) (D9).
      Done: `refuse_introduction_settle` (409) and `refuse_introduction_fulfillment` (404).
      Unit passed.
- [x] 20.2 Stage tables: every seller stage in VM (`settlement_stages.py`:
      `VmAlkahestSellerStage`, `VmPaymentsSellerStage`, `VmContactSellerStage`) and bare
      metal (`settlement_stages.py` `SellerStage` and its subclasses, keyword-only;
      `settlement_composition.py` `SELLER_STAGES`) declares `completes_outside_settlement`
      with no default, contact exchange `True`, beside `settles_from_agreement` and
      `release_models`. API credits composes no introduction and no refusal, and its stage
      table is unchanged (the delta's "every compute domain"). VM's `VmContactSellerStage.start`
      no longer raises its own 409 (D9).
      Done; `VmContactSellerStage` has no `start`, and bare metal's `verify` and
      `revalidate` are optional (decision 9's Section 20 paragraph).
- [x] 20.3 Routes: VM `controllers/settle_controller.py` `settle_escrow` applies the refusal
      after resolving the stage and before `stage.start`; bare metal `src/api.py` `settle`
      and `GET /api/v1/settle/{ref}/status` apply it after `accepted_stage` and before
      verification; bare metal's fulfillment status, access, result, and teardown routes
      check ownership and the accepted thread's terminal state in `_fulfillment_identity`,
      then resolve the stage, apply the refusal, and only then build the fulfillment
      service or load its context (D9).
      Done; bare metal resolves the stage through `settlement_service.accepted_seller_stage`,
      which refuses a thread not accepted; each domain names its own reason text.
- [x] 20.4 Bare metal stops recording the reveal as settlement evidence: delete
      `ContactStage.record_reveal`, `runtime.py`'s `_RevealRecordingRuntime` and
      `_record_collected_introduction`, and pass the settlement runtime to the
      contact-exchange composition as VM does. Its only readers were the contact stage's
      own revalidation (now behind the refusal) and the fulfillment lifecycle's
      `settlement_verified` precondition, which an introduction deal never reaches; the
      contact-exchange kit's retention, deletion, and re-delivery read the introduction
      store. `verify_contact` and `revalidate_contact` go if nothing else calls them (D9).
      Done; both went. An introduction deal's settlement record stays `accepted`, with no
      reference, after the reveal.
- [x] 20.5 Tests: VM unit `tests/unit/test_unbacked_settlement_options.py` (every stage
      declares the field; a stage omitting it cannot be constructed) and
      `test_settlement_start_authority.py`; VM application integration
      `tests/integration/test_introduction_origins.py` — settle answers 409. Bare metal
      application integration `tests/test_http_introductions.py` through the typed clients
      — settle and settle status answer 409, fulfillment status, access, result, and
      teardown 404, another buyer refused as for any deal, the settlement record still
      `accepted` after the reveal; an unbacked, host-less binding answering 404 without
      loading a context; `test_domain_runtime.py`, `test_selection_dispatch.py`,
      `test_app_composition.py` follow the stage table (D9).
      Done as listed. VM's settle refusal runs over a contact deal the storefront
      negotiated and accepted (`test_introduction_origins.py`, 160 F3). Bare metal: the 409s
      and 404s, another buyer's 403 before the stage is resolved, the record `accepted`
      after the reveal and a restart, and an unbacked listing published by the app's own
      cycle reaching an introduction whose fulfillment status answers 404 with no context
      loaded.
- [x] 20.6 Versions: `arkhai-kit-storefront` (exact pins in both storefronts), both
      storefronts; `make lock`.
      Nothing owed: each already carries one bump against `dev`.
- [x] 20.7 **Verify.** `make -C kit test-storefront`; `make test-storefront`, `make
      test-bare-metal`; `make test`; `make check-packaging`. End-to-end:
      `e2e_vm_introduction` and `e2e_bare_metal_introduction`; the fulfillment 404 in
      `e2e_bare_metal_unbacked_introduction` (Section 22).
      Passed with Sections 18 to 22 (18.7).

Section 20 notes:

- The fresh-context check of Sections 20 and 21: the permanent `buyer-orchestration` "Buyer
  mechanism utilities are namespaced" is modified by the delta to allow a domain's own
  `settlement` group.

## 21. Bare metal's settlement commands sit under its own command

Delivers the bare-metal buyer's `settlement` group under `market bare-metal` and the core
buyer's refusal of a root command two domains register (D14; `buyer-orchestration` "Two
domains may not register one root command"). Touches `core/buyer` and
`domains/bare_metal/buyer`.

- [x] 21.1 `core/buyer/src/core_buyer/cli.py` `build_app`: refuse at startup a root command
      name two installed domains register, naming the command and both domains, from each
      domain's registered names. Tests in `core/buyer/tests/unit/test_cli.py` (unit): two
      plugins registering `settlement` refuse; distinct names compose (D14).
      Done: `DuplicateRootCommandError`, the console script exiting 2; a nameless group's
      merged names are claimed too (160 F6). Unit passed.
- [x] 21.2 `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py` `register_commands`
      adds `settlement` to `bare_metal_app` beside `request-introduction`; VM's root
      commands stay. Tests in `domains/bare_metal/buyer/tests/test_buyer_composition.py`
      (unit) (D14).
      Done; the plugin registers one root command, `bare-metal`.
- [x] 21.3 Versions: `arkhai-core-buyer` (the bare-metal buyer's exact pin),
      `arkhai-bare-metal-buyer`; `make lock`.
      `arkhai-bare-metal-buyer` 0.5.1 → 0.6.0 (moving its commands is incompatible);
      `arkhai-core-buyer` already bumped.
- [x] 21.4 **Verify.** `make test-core`, `make test-bare-metal`, `make test-vms-buyer`; `make
      test`; `make check-packaging`. End-to-end: every VM-lane CLI scenario
      (`e2e_deal_buyer_cli`, `e2e_buy`, `e2e_vm_introduction`) runs with all three buyers
      installed, and Section 22's scenario uses the namespaced commands.
      Passed with Sections 18 to 22 (18.7). The VM and bare-metal plugins installed together
      are first exercised by the VM lane's CLI scenarios and Section 22's.

## 22. Unbacked bare-metal discovery reaches a usable introduction

Delivers the bare-metal Goal 7 evidence on shared introduction stages, VM's introduction
scenario moved onto them, and the bare-metal lane's mail sink (D14, D15, D12;
`storefront-publication` "Bare-metal publication derives unbacked listings";
`registry-discovery` "Compute listings publish their capacity backing"). Touches `e2e-tests/`,
the bare-metal lane's compose overlay, and the bare-metal storefront's development
configuration.

- [x] 22.1 `e2e-tests/tests/e2e/roles/helpers/introduction_stages.py` (new): the stages VM's
      introduction scenario runs, as non-`Test*` stage classes over a driver protocol each
      domain supplies for supply seeding and its CLI verbs, as `compute_deal_stages.py`
      does; `scenarios/vms/test_vm_introduction.py` moves onto them with a VM driver. A
      source check beside `tests/unit/test_compute_deal_stages.py` holds both domains to the
      shared stages (D14).
      Done: four shared stages (disclosure; supply, rate-bounded discovery, and the
      introduction-only option; the CLI reveal and the buyer's sink; the seller's mail) over
      `IntroductionDriver` and `IntroductionState`, each domain's driver its own module.
      `tests/unit/test_introduction_stages.py`, on readers shared with the compute deal
      check in `tests/unit/stage_sources.py`, holds each domain to subclassing every stage
      once in order and every test to the shared state's fields, each produced before it
      is read (decision 14's Section 22 paragraph).
- [x] 22.2 The lane's mail sink: a `mailpit` service in `compose.bare-metal-local.yml`, so the
      existing `MAILPIT.API_URL` setting applies; `domains/bare_metal/storefront/storefront.dev.toml`
      configures `[Delivery]` with a `seller-mail` SMTP sink to it, as VM's
      `storefront.bob.toml` does; `e2e-tests/tests/unit/test_domain_stack_configuration.py`
      asserts both (D14).
      Done; the storefront waits for Mailpit to be healthy, and the compose render test
      `scripts/tests/test_bare_metal_compose.py` expects the service.
- [x] 22.3 `scenarios/bare_metal/test_bare_metal_unbacked_introduction.py` (new), marker
      `e2e_bare_metal_unbacked_introduction`, holding the storefront's loops through
      Section 13's module hold, with a bare-metal driver: a backed pool with a host-bearing
      declaration and a rate, an unbacked pool (no deliverable mode, advertising
      `bare_metal`, a configuration-free provider) with a host-less declaration enabling
      bare-metal publication and a rate, and a listing publishing no rate; contact settlement
      on the unbacked pool through a storefront pool override; a rate-bounded `market
      bare-metal list` returning the backed and unbacked listings and excluding the rateless
      one; `capacity_backing=unbacked` returning only the unbacked one; the unbacked listing
      carrying `capacity_backing: unbacked`, no host fields, no `access_methods`, and
      exactly `contact-exchange.v1`; the reveal through `market bare-metal settlement contact
      introduce`, the buyer's file sink receiving the seller's contact and the seller's mail
      reaching the sink; the fulfillment status route answering 404 (D14, D12).
      Done, as the shared stages with bare metal's own between them, three machines each in
      a pool of its own, through the production `market bare-metal list --resource`. The
      bare-metal buyer's `request-introduction` failed three ways against a real storefront
      and is fixed (decision 14's Section 22 paragraph); application integration through
      the production commands
      (`test_http_introductions.py::test_the_buyer_commands_reach_an_introduction_over_their_own_run_log`),
      shown failing on each defect with its fix reverted.
- [x] 22.4 `e2e-tests/pyproject.toml` registers the marker; `e2e-tests/Makefile`'s
      `E2E_BARE_METAL_MODULE` includes it (D14).
      Done.
- [x] 22.5 Version: `arkhai-e2e-tests`; `make lock`.
      `arkhai-e2e-tests` stays 0.3.0; its floor on `arkhai-bare-metal-buyer` rises to 0.6.0.
- [x] 22.6 **Verify.** `make test-e2e-unit`; `make -C e2e-tests test-e2e-bare-metal` and
      `test-e2e-vm` (system); `make test`; `make check-packaging`. End-to-end:
      `e2e_bare_metal_unbacked_introduction` and `e2e_vm_introduction`.
      Checked from the owner's validation of `cbe39b4`, in their own environment: pipeline
      run 40486963495 succeeded, `e2e_bare_metal_unbacked_introduction` passing 9 tests on
      e2e-bare-metal and `e2e_vm_introduction` 6 on e2e-vm; local `check-packaging`,
      `make test`, and the Helm part passed. 22.7's `buy` change has no end-to-end
      coverage: the one scenario running `buy`, `e2e_bare_metal_deal`, is in no lane.
- [x] 22.7 `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py` `buy_bare_metal`:
      fix the three defects 22.3's correction fixed in `request_introduction`, which
      `buy` shares. It passes the listing's advertised settlement option, so the seller
      can accept; it records the publisher principals in the shape the run-log loader
      reads, so a later `market bare-metal` command can reload the run; and it decodes
      the provision terms the seller echoes. Added on the owner's word after round 3's
      implementation, ahead of triage. Tests: a bare-metal storefront test running
      `buy` over a real run log, beside 22.3's run of the production commands, failing
      on each defect with its fix reverted. Version: `arkhai-bare-metal-buyer` only if
      this branch has not already bumped it past `dev` (it has, to 0.6.0, in 21.3);
      `make lock` if a pin moves. **Verify.** `make test-bare-metal`; `make test`;
      `make check-packaging`.
      Done. Application integration through the production commands
      (`test_payment_settlement_client.py::test_the_buy_command_settles_over_a_run_log_a_later_command_reloads`):
      `market bare-metal buy` settles until delivery starts, then `teardown` reloads the
      run; reverting the decoder or the principals' shape fails it. The advertised option
      tells the opening policy the option bargains an amount, and the test cannot tell it
      apart (decision 14's Section 22 paragraph). The test replaces only the CLI's own
      factories (decision 27). Passed: `make test-bare-metal`, `make test` (the Helm render
      unrun), `make check-packaging`, `make check-change`.

Section 22 notes:

- Adjacent and left, owned by `bare-metal-and-credits-domain-stacks` (pre-closeout review
  176 F3): `e2e_bare_metal_deal`, the one scenario running `buy`, is in no lane and its
  later commands no longer match the CLI (4b.9); `buy` and `request-introduction` repeat
  the listing read, option match, and run start, which one helper would share (4b.10).
- Round 3's triage (reviews 159 and 160, owner's notes 157), against `88e5697`:
  159 F1 / 160 F2 — both compute buyers' delivered introductions name the Agreement's
  seller as counterparty through core's `accepted_seller_principal` (decision 12), and
  `Stage02_Reveal` asserts it in both lanes; 160 F1 — the VM status test's registry probe
  answers through `SystemService`'s injected `registry_probe_transport`; 160 F3 — decision
  27's factory seam in the bare-metal buyer CLI and `tests/buyer_commands.py`,
  `ListingService`'s optional `registry_publisher`, and the other CLIs' patches to 23.5's
  roadmap row; 160 F4 — decision 7 states migration's behaviour and the
  `settlement-configuration` delta adds "A publication clause's mechanism input is a
  mapping"; 160 F5 — superseded notes marked; 160 F6 — a nameless group's names are
  claimed; 160 F7 — the bare-metal reserve route asks the binding's delegate before
  building a claim. Evidence: every suite of `make test` passed up to the Helm render (no
  `helm`), with `make check-packaging`, `make check-comment-hygiene`, and `make
  check-change`. Validated at `8d5c46b` (validation 171).
- Pre-closeout triage (review 176), against `1e1eb7f`: 176 F1 — `ListingService`'s
  `publish_order_to_registry`, `escrow_cli`'s `make_create_escrow_fn`, and the kit test's
  `verify_escrow_against_plan` imported at module level, no cycle holding them local;
  176 F2–F4 — the proposal's lists, 23.7, 23.8, and the two adjacent `buy` items above.
  Evidence: `make test` up to the Helm render, `make check-packaging`, `make
  check-comment-hygiene`, `make check-change`. Validated at `c6e2108` (validation 184:
  local, Helm, and all three pipeline lanes in run 40547570647).
- Closeout fix round (23.2), against `32807f5`: the seven function-local imports 23.2
  named, all in tests the change added, moved to module level, none needing a reason to
  stay local and no cycle holding them; older local imports the change did not add are
  left. Evidence: `make test` up to the Helm render (API-credit storefront 241, VM
  storefront unit 1132 and integration 477, bare-metal storefront 502, e2e unit 169),
  `make check-change`, `make check-packaging`. Committed as `9497734`; its validation is
  waived by the owner.

## 23. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order,
replacing the placeholder 2.1. It edits documentation only; a part needing code returns the
change to implementation.

- [x] 23.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes, and read the
      comments and docstrings the change added (the diff from its branch point on `dev`)
      for fuzzier provenance: none names this change, a review, a round, or a migration,
      and none describes the removed preflights, init containers, `accepted_escrow_terms`,
      or unbacked refusal as history.
      *Closeout: `make check-comment-hygiene` passed at `c6e2108`. The added comment and
      string lines of the diff from `73d3760` (`dev`'s merge base) were searched for
      provenance wording (previously, formerly, moved, removed, review, round, migration,
      legacy, preflight, init container, `accepted_escrow_terms`): the matches state current
      behaviour — the chart's "no init container waits" rule, the API-credit startup
      refusing retired settings, operator error text naming a removed setting, and the
      change-workflow tests' own "round" vocabulary. Nothing to rewrite.*
- [x] 23.2 **Import placement.** Confirm every import each section added or touched is at
      module level, or has its reason beside it (a verified cycle or a deliberate lazy
      load) — in particular `compute_provisioning`'s and the bare-metal adapter's contracts
      imports, each storefront's chain-probe imports, and the e2e hold helpers. One that
      should move returns the change to implementation.
      *Closeout (returns the change to implementation): every indented import the diff from
      `73d3760` adds was read. The production ones are under `TYPE_CHECKING` or carry their
      reason (the API-credit and VM storefront CLIs import their config module only after
      `--config` runs). Seven import statements, all in tests the change added, are function-local with no
      reason beside them:*
      - *`domains/apicredits/storefront/tests/integration/test_publish_reconcile.py`,
        `test_supplied_escrows_are_judged_on_their_own_chains_beside_clauses`:
        `capacity_client as cc_module` and `ListingService`, both already imported at the
        module's top under the same names, so the local imports are redundant;*
      - *`domains/apicredits/storefront/tests/unit/test_settlement_fulfillment.py`,
        `test_a_listing_changed_since_acceptance_settles_against_the_committed_plan`:
        `settlement_stages` and `utils.config as config_module`; and
        `test_a_chain_with_no_client_is_retryable_only_when_configured`:
        `settlement_stages`, `AlkahestSellerStage`, and `SettlementRefusal`;*
      - *`domains/vms/storefront/tests/integration/test_settle_controller.py`, fixture
        `anvil_book`: `market_storefront.utils.config as storefront_config`, where the
        module already imports `market_storefront` modules at its top and fifteen VM test
        modules import the config module at module level.*
      *Fix round: move each to module level, or, where the move fails, write the real
      failure beside it (the API-credit unit file keeps many older function-local imports;
      only these, which the change added, are owed). Closeout resumes at 23.2 once that
      commit is validated.*
      *Fix round: all seven moved to module level, none needing a reason to stay local
      ("Closeout fix round (23.2)" above). Closeout confirms them and checks this task.*
      *Closeout (resumed): `9497734` deletes the two redundant `test_publish_reconcile.py`
      imports and moves the other five to their modules' tops; the diff from `73d3760`
      adds no other function-local import to those files, and `make check-comment-hygiene`
      passes again. Confirmed. The commit's validation is waived by the owner (workflow
      log seq 292).*
- [x] 23.3 **Documentation compliance.** Re-check D1–D27 against
      `openspec/README.md#documentation-placement` and `AGENTS.md`'s "Documentation
      ownership": behaviour in the `spec.md` deltas, rationale in the architecture
      companions, repository-wide principles in `ARCHITECTURE.md`, nothing durable left only
      in `design.md`, no production code citing `openspec/changes`. D24 (stage events) and
      D25 (upgrade order) owe no document; D26's edits to other changes are on the branch;
      D15 is 2.2.
      *Closeout: every decision has its home, listed in the design promotion record. D12's
      delivered counterparty is `introduction-delivery`'s existing requirement and D13
      predates the change. Only the change-workflow tooling under `scripts/` names
      `openspec/changes`; no market code does. Limits that the compression moved into
      `design.md` are also promoted: the streamed-response limit of the signing middlewares
      (D23) to the `physical-provisioning` companion, the disabled Arkhai-payments section
      reporting nothing (D19) to the `settlement-configuration` companion, and VM's
      unchecked pinned carrier and the duplicated unpinned predicate (D18) to the
      `negotiation-protocol` companion. Two placements left to judgement are kept as they
      stand: `publication_view_problems` stays specified in the `physical-provisioning`
      delta, which binds `kit/site` to carry it uninterpreted, with no `site-capacity`
      delta (pre-closeout reviewer 160 found none needed); and `marketplace-identity`
      already states that a response is signed after authentication, so its `kit/site`
      half is not restated there. One delta defect fixed: "API-credit listing creation
      waits for or names an unreachable mechanism" sat under MODIFIED in the
      `storefront-publication` delta although no permanent requirement has that name, so the
      archive would have refused it; it is now under ADDED.*
- [x] 23.4 **Narrative compression.** Shorten Sections 3–22's completed-task notes to final
      behaviour, material validation evidence, deferred work, and destinations; move any
      alternatives or debugging narrative into `design.md` first. 1.1–1.15 and 2.2 stay as
      they are.
      *Closeout: Sections 3–22 went from about 330 KB to about 110 KB, every task, checkbox,
      and instruction kept; each note now gives final behaviour, material evidence (the
      validated commits and pipeline runs), owner decisions, and each deferral's owner.
      Implementation settlements not yet in `design.md` moved there first, as "Settled in
      implementation" paragraphs under D9, D10, D14, D16, D17, D18, D19, D20, and D23.
      Kept as task notes, with no owner: test-coverage gaps (a typed-client VM settle after
      a listing change, contact exchange's blockers beside `disabled`, API credits'
      `negotiate` run-log recording and `--from` carry-forward), API-credit tests leaking
      dotted `settings_overrides` keys, API credits' own `_unknown` predicate beside
      `MechanismReadiness.unknown`, and VM's text `settlement status` omitting each
      blocker's kind.*
- [x] 23.5 **Roadmap currency.** `docs/development/ROADMAP.md`: Goal 7's "Current state"
      (bare metal publishes unbacked listings, settling by introduction; the "remains
      backed" sentence and the pointers to this change replaced by the present state), its
      gap row "Bare metal, the primary target domain, cannot publish an unbacked listing"
      struck through and closed with a link to the archived change, and its closing
      paragraph's bare-metal sentence stating the scenario as present; Goal 6's row "An
      escrow proposal naming no contract is priced …" struck through and closed (such a
      proposal is refused), a new Goal 6 row "An API-credit listing's options are fixed at
      creation, so an unready mechanism's option stays advertised until the seller closes
      it" owned by "Unowned — needs a new change", and Goal 6's "Current state" stating that
      settlement verifies against the committed plan, buyers fund only what they derive, and
      an unusable Alkahest section is unready. Goal 4 gains the row "A negotiation's
      continuation is resolved against the listing as currently stored in VM and against
      the opening's in bare metal, so a repriced option ends a VM negotiation that bare
      metal would continue" owned by "Unowned — needs a new change", unless a change owns it
      by closeout (round 1's triage, 85 F17). Goal 4 also gains the row (no goal is about
      test hygiene, and the CLIs are domain composition) "CLI tests replace library names,
      names a command module imports, or
      names inside core, rather than the module's own factories", owned by "Unowned —
      needs a new change" (round 3's triage, 160 F3, decision 27). Name each in the
      design-promotion record.
      *Closeout: done as listed. Goal 7's current state describes unbacked bare metal and
      the introduction answer, its gap row is struck through and closed against the archive,
      and its closing paragraph names `e2e_bare_metal_unbacked_introduction`; Goal 6's
      unpinned row is closed, its API-credit row added as unowned, and its current state
      gains the settlement paragraph; Goal 4 gains both rows as unowned, since no open
      change owns continuation semantics. The roadmap names this change as no open gap's
      owner. A stray table fragment at the end of Goal 4 predates this branch and is left.*
- [x] 23.6 **Campaign index currency.** `openspec/changes/README.md`: this change's row and
      notes current, the Goal 7 campaign graph naming it current, and the two-seller scenario
      still recorded as unowned; other rows' `Depends on` are left to archive cleanup; `make
      check-change-index` passes. Name the update in the design-promotion record.
      *Closeout: the row stays `in closeout`, its notes describing the closed-out change,
      and links the archive after 23.11; the Goal 7 campaign text says unbacked supply is
      in place for both domains and that the bare-metal scenario runs here; the graph and
      the unowned two-seller row are unchanged. No other row is touched. `make
      check-change-index` passed.*
- [x] 23.7 **Packaging.** `make check-packaging` passes with every failure resolved; `make
      check-architecture-change CHANGE=unbacked-bare-metal-listings` reports no exception or
      override row this change owns. `make check-agent-skills` passes: the change edits
      `.agents/skills/change-validate/SKILL.md` (pre-closeout review 176 F4).
      *Closeout, at `9497734`: `make check-packaging` passed (installs, locks, Python
      selection, layout, and the layer, scope, dependency, and kind rules); `make
      check-architecture-change` reports no row this change owns; `make check-agent-skills`
      passed.*
- [x] 23.8 **End-to-end pipeline.** Record a passing pipeline run of all three lanes on the
      closeout commit, its result, and the scenarios that exercise the change: VM lane
      `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_alkahest_escrow_codecs`, `e2e_non_erc20_settlement` (settlement against the plan,
      buyer derivation, pinned openings, readiness kinds, the chain probe),
      `e2e_compute_dynamic_listings` and `e2e_listing_shapes` (site derivation),
      `e2e_vm_introduction` (shared introduction stages, the settle refusal); API-credit lane
      `e2e_credits_deal` (`listing-seed`, the CLI through the typed client); bare-metal lane
      `e2e_bare_metal_unbacked_introduction` (unbacked discovery reaching a usable
      introduction; a rate-bounded query returning backed and
      unbacked bare-metal listings together, carried from `publish-indicative-listing-rates`
      7.13; the backing filter; the fulfillment 404), `e2e_bare_metal_introduction`,
      `e2e_bare_metal_publication`, and `e2e_bare_metal_mock_deal`; every lane on the module
      holds. Record `e2e_credits_payment_deal` and `e2e_bare_metal_payment_deal` as unrun, not
      as evidence: both skip in every lane, which runs no payments service (validation 175;
      pre-closeout review 176 F4). Record the local Helm topology evidence of D14 —
      `make helm-topology-up` and `make helm-topology-check` on the change's commit, Bob's lifecycle loops running after
      the check, no init containers on the VM storefront — run by the maintainer, or record
      it unrun. A pipeline that cannot run for a reason unrelated to the change is recorded
      as a blocker naming its cause and owner, and what it gates as unrun.
      *Closeout: the latest passing validation, `reviews/184-validation.md`, names
      `c6e2108`: local, Helm, and pipeline passed, run 40547570647 of `e2e.yml` succeeding
      in every lane (VM 135 passed; bare metal 60 passed, 3 skipped; API credits 1 passed, 3
      skipped). Every scenario listed above ran and passed in its lane,
      `e2e_bare_metal_unbacked_introduction` through its last stage. The skips are
      `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal`, which no lane can run
      without a payments target: unrun, not evidence. The run describes `c6e2108`; the one
      later code commit, `9497734`, moves test imports only, its validation waived by the
      owner (workflow log seq 292), and the closeout commit changes documentation only. No
      section owes a CI workflow. The local Helm topology run of D14 (`make
      helm-topology-up` and `make helm-topology-check`, Bob's loops running after it, no
      VM storefront init container in a live release) is recorded by no validation, so it
      is unrun; validation's Helm part deployed the default release and passed its
      scenario pod, and the chart render tests assert the init containers and test-pod
      labels.*
- [x] 23.9 **Promotion.** Write the permanent documents and complete the design-promotion
      record below:
      - `docs/development/ARCHITECTURE.md`: "Deciding which party is authoritative" (under
        "Authority boundaries") — anything a counterparty can send is handled on its own
        terms, whatever client produced it; "Settlement configuration" — what an Agreement
        and its listing determine each party derives for itself, a counterparty's copy
        compared, never used; and a configured mechanism whose section parses but cannot
        settle is unready, its options unpublished, while a section that does not parse
        stops startup; "Holding or closing a listing the storefront cannot fully derive" —
        a listing left with no option is held while any admissible mechanism's readiness is
        unknown and closed only when configuration rules every one out; "Composition from
        above and below" — where two domains handle one concern differently and nothing in
        their markets requires it, one behaviour is chosen for both; "Storefront capacity
        boundary" — the bare-metal commitment sentence and the delegate's decisions,
        delivery terms among them.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Kubernetes: ConfigMap and Secret
        mounting" — a deployment holds no service back with init containers that wait for
        or validate its external dependencies, the service reports them degraded, and no
        service waits in process either; "Storefront startup and site trust" — a service
        refuses to start when its own configuration or stored state is incoherent, the
        removed `fail_on_unreachable` and `preflight_timeout` settings, the Alkahest probe
        interval and timeout, that the probe reads a `ws://` or `wss://` chain URL over
        `http://` or `https://` on the same host (round 1's triage, 85 F7), the degraded
        start in "System status", and the rewritten
        `publication_derivation` passage; "Storefront listing shapes and pool overrides" —
        its `publication_derivation` passage; "Release topology" — Helm test pods carry no
        workload selector label; "Introduction delivery" — the bare-metal lane's mail sink
        and delivery configuration.
      - `docs/development/TESTING.md`: "Pause the loop, then advance it explicitly" — the
        module-hold guidance in the wording `design.md` records, replacing the opt-in
        `bare_metal_loops_held` passage and the "Scope the pause" trap, and the loop table's
        rows gaining `alkahest-chain-probe` (all three) and `listing-seed` (API credits) and
        the provisioning pause routes' gate state; "System Integration Tests (End-to-End)" —
        the new scenario, the shared introduction stages, and the hold source check; "Chart
        Render Tests" — the bounded topology assertion and the no-`wait-for-` and
        `startupProbe` assertions; the mocking convention — a command module builds its
        collaborators through factory functions it defines, its one seam, and a test
        replaces only those (decision 27, round 3's triage, 160 F3).
      - `openspec/specs/storefront-publication/architecture.md`: "Bare-metal listing
        shapes" — unbacked candidates, delivery terms, the one-unit commitment;
        "Reconciliation" — the recheck on the held projection and the no-option close or
        hold; "Settlement option reconciliation" — classification of the admissible clauses'
        mechanisms, and its release-condition paragraph rewritten (conditions derived only
        under a ready Alkahest; an undeliverable model unready rather than a startup
        refusal); "Autonomous publication" — the site-derivation log, and its paragraph
        saying a pool resolving no settlement clause "is held at compose" (such a pool's
        candidates are refused and their open listings closed; a pool resolving no lease
        bound is still held).
      - The other permanent passages that still describe a pool resolving no settlement
        clause as held (Section 18's fresh-context check): `docs/development/ARCHITECTURE.md`
        "Storefront capacity boundary" ("a pool that resolves none is held and reported");
        `docs/development/DEPLOYMENT_AND_CONFIG.md` "Storefront startup and site trust"
        (the pool "is held and reported in system status's `publication_derivation`") and
        "Storefront listing shapes and pool overrides" (`pool_settlement_clauses_missing`,
        no longer reported); `docs/bare-metal-seller-quickstart.md`'s two passages, in
        "Start and inspect" (a pool stating no settlement clause "is held and reported
        instead") and in its list of what each cycle does (it "Holds … a pool … that
        resolves no settlement clause"). Each now reads: the candidate is refused as
        `no_settlement_option`, its open listing closed through reconciliation and
        reopened once a clause resolves; a pool resolving no lease bound is still held.
        The `settlement-configuration` scenario "No enabled mechanism is ready", which
        said publication fails, is rewritten by that capability's delta at the archive
        (23.11), not by hand.
      - `openspec/specs/physical-provisioning/architecture.md`: "Compute composition" — the
        view contract, the resource pass's pool context, and view problems; "Canonical
        requests, durable replay, and signed responses" — the signed failure after
        authentication.
      - `openspec/specs/resource-pool-management/architecture.md`: "Advertisement, delivery,
        and backing" — delivery terms among the delegate's decisions, and the
        unserved-provider refusal.
      - `openspec/specs/market-composition/architecture.md`: "Settlement runtime
        composition" — `completes_outside_settlement` beside `fulfils_through_capacity`;
        "Storefront composition kit" — the introduction refusal as the kit's first shared
        stage convention.
      - `openspec/specs/settlement-configuration/architecture.md`: "Readiness, publication,
        and selection" — why the chain probe runs apart from readiness, and what each
        blocker kind tells the publication runner; that status judges every configured
        chain while publication judges the chains its clauses name, and the limit that
        one unreachable chain makes Alkahest unready for every chain a publication names
        together (round 1's triage, 85 F10).
      - `openspec/specs/buyer-orchestration/architecture.md`: "Persisted runs" — the
        run-log's opaque `listing_record`, written when negotiation starts and at
        acceptance and read back per listing on resume, and a resumed amount taken exactly
        from the Agreement; "Configured mechanism choice and buyer actions" — the plan check
        as a required port on the escrow settle hook, run where funds move, beside the
        selection-branch validator. `docs/development/ARCHITECTURE.md`'s `kit/alkahest`
        paragraph (under "Kit areas") — the kit writes and reads a buyer's record of a
        listing's release conditions, so core carries it opaquely.
      - `docs/bare-metal-seller-quickstart.md` "Start and inspect": the unbacked passage
        rewritten as how to list unbacked machines, and its `publication_derivation`
        passage; `docs/seller-quickstart.md`'s `publication_derivation` passages and its
        region passage naming the retired `regionless_pools` category (status now
        reports a `pool_region_missing` hold); `openspec/specs/storefront-publication/
        architecture.md`'s derivation passage ("each cycle replaces it": a cycle that
        derives no site leaves its last derivation, and a site held whole keeps its
        pools' entries).
      - Section 18's implementation decisions (design decision 7's Section 18
        paragraph): `docs/development/ARCHITECTURE.md` "Capacity publication and
        multi-domain storefront composition" — the kit's refused-candidate recording
        and close hook, which every storefront driving its cycle through the kit
        shares; `docs/development/DEPLOYMENT_AND_CONFIG.md` "Storefront listing shapes
        and pool overrides" — the derivation reason codes `settlement_mechanism_unknown`
        and `payload_unbuildable`, and that a clause naming a disabled mechanism is
        dropped wherever it is stated, closing a listing it alone priced, and that
        `storefront config migrate` accepts such a clause (round 3's triage, 160 F4); the
        `settlement-configuration` companion — a clause read apart from configuration
        before its mechanism's enablement is judged.
      - The `spec.md` files of the ten capabilities the deltas cover are written by the
        archive (23.11) and named in the record. `openspec/specs/README.md` gains nothing:
        no new capability or companion.
      *Closeout: every passage listed is written, each name checked against the code, and
      each location is in the design promotion record. Beyond the list: `ARCHITECTURE.md`'s
      `kit/storefront` item names the introduction refusal, and its `kit/alkahest` item
      the chain probe; `DEPLOYMENT_AND_CONFIG.md`'s "Bare-metal role configuration" reads
      a missing Alkahest input and `interruptible` as unready, and its retired-keys list
      gains the two provisioning keys; the `market-composition` and
      `settlement-configuration` companions no longer say no stage convention is
      implemented; the `physical-provisioning` companion drops the reveal as settlement
      evidence; the `buyer-orchestration` companion's limits name the root-command
      refusal; and the `negotiation-protocol` companion gains the listing-decides rule
      with VM's pinned carrier (23.3). `docs/configuration.md` states nothing the change
      made false.*
- [x] 23.10 **Documentation citations.** `make check-doc-citations
      CHANGE=unbacked-bare-metal-listings` after promotion, every match resolved; then
      `openspec validate unbacked-bare-metal-listings --strict`.
      *Closeout: `make check-change` passed after promotion — comment hygiene, agent
      skills, documentation citations (every cited path resolves, none a tombstone), task
      list, change index, and `openspec validate --strict` with the pinned 1.14.0.*
- [x] 23.11 **Archival.** Last: `openspec archive unbacked-bare-metal-listings -y`, merging
      the deltas into `openspec/specs/` (no `--skip-specs`: no `spec.md` was promoted by
      hand); the change's row then links the archive directory.
      *Closeout: archived with the pinned 1.14.0 as
      `openspec/changes/archive/2026-10-27-unbacked-bare-metal-listings/`, merging 19 added,
      15 modified, and 1 removed requirement across the ten capabilities, each once as its
      delta states it and nothing else changed but a blank line after one Purpose. The
      row links the archive and stays `in closeout` for archive cleanup.*

## Design promotion record

Completed at closeout (23.9). A `spec.md` anchor marked "(archive)" is written by the
archive from this change's delta (23.11), not by hand.

| Accepted decision | Permanent location |
|---|---|
| D1 Backing is decided by one delegate both domains share | `openspec/specs/resource-pool-management/spec.md#requirement-capacity-backing-is-interpreted-by-one-delegate` (archive); `openspec/specs/resource-pool-management/architecture.md#advertisement-delivery-and-backing`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| D2 An unbacked listing's identity is its site and Physical Resource, host fields absent | `openspec/specs/storefront-publication/spec.md#requirement-bare-metal-publication-derives-unbacked-listings` (archive); `openspec/specs/storefront-publication/architecture.md#bare-metal-listing-shapes` |
| D3 The site emits the bare-metal view for unbacked supply | `openspec/specs/physical-provisioning/spec.md#requirement-a-bare-metal-publication-view-is-built-from-its-capacity-declaration` (archive); `openspec/specs/physical-provisioning/architecture.md#compute-composition` |
| D4 Resource views receive their pool's context and never fail the projection; `publication_view_problems`; a declaration fault holds its listing | `openspec/specs/physical-provisioning/spec.md#requirement-domains-contribute-their-inventory-views` (archive); `openspec/specs/physical-provisioning/architecture.md#compute-composition`; `openspec/specs/storefront-publication/architecture.md#reconciliation` |
| D5 Delivery terms are the delegate's decision (`carry_delivery_terms`, `delivery_term_constraints`); no `["ssh"]` default | `openspec/specs/storefront-publication/spec.md#requirement-a-bare-metal-listing-carries-delivery-terms-only-when-backed` and `openspec/specs/resource-pool-management/spec.md#requirement-capacity-backing-is-interpreted-by-one-delegate` (archive); `openspec/specs/resource-pool-management/architecture.md#advertisement-delivery-and-backing`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| D6 The view carries no backing; the shared trusted carrier validates its terms against its pool's backing | `openspec/specs/storefront-publication/spec.md#requirement-a-bare-metal-listing-carries-delivery-terms-only-when-backed` (archive); `openspec/specs/storefront-publication/architecture.md#bare-metal-listing-shapes`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| D7 A candidate with no settlement option yields no listing; an open one closes or is held by its admissible mechanisms' classification | `openspec/specs/storefront-publication/spec.md#requirement-a-compute-candidate-with-no-settlement-option-yields-no-listing`, `#requirement-publication-derives-all-ready-settlement-options`, `#requirement-a-storefront-that-cannot-publish-refuses-to-start`, and `openspec/specs/settlement-configuration/spec.md#requirement-priority-orders-choices-but-never-changes-accepted-settlement` (archive); `docs/development/ARCHITECTURE.md#holding-or-closing-a-listing-the-storefront-cannot-fully-derive`; `openspec/specs/storefront-publication/architecture.md#settlement-option-reconciliation` |
| D7, Section 18: one refused-candidate recording and close hook (`RefusedCandidates`); a disabled mechanism's clause dropped wherever stated; `storefront config migrate` accepts it; a clause read apart from configuration; `mechanism_input` a mapping | `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides`; `openspec/specs/settlement-configuration/spec.md#requirement-a-publication-clauses-mechanism-input-is-a-mapping` (archive); `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection` |
| D8 An unbacked listing's recheck reads its held projection, never availability; a view-problem resource refused as a declared mismatch | `openspec/specs/storefront-publication/spec.md#requirement-bare-metal-opening-rechecks-its-listing-against-its-source` (archive); `openspec/specs/storefront-publication/architecture.md#reconciliation` |
| D9 A deal settled by introduction has no settlement or fulfillment; `completes_outside_settlement`; the refusal in `kit/storefront` | `openspec/specs/storefront-publication/spec.md#requirement-a-deal-settled-by-introduction-has-no-settlement-or-fulfillment` (archive); `openspec/specs/market-composition/architecture.md#settlement-runtime-composition` and `#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#kit-areas` |
| D10 One site-derivation summary, status, and log for both compute storefronts | `openspec/specs/storefront-publication/spec.md#requirement-a-compute-storefront-reports-and-logs-its-site-derivation` (archive); `openspec/specs/storefront-publication/architecture.md#autonomous-publication`; `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust` and `#storefront-listing-shapes-and-pool-overrides`; `docs/bare-metal-seller-quickstart.md#start-and-inspect`; `docs/seller-quickstart.md` (its region and system-status passages) |
| D11 Bare metal's refusal of unbacked pools is removed | `openspec/specs/storefront-publication/spec.md` — "An unbacked pool yields no bare-metal listing" removed (archive); `docs/bare-metal-seller-quickstart.md#start-and-inspect` ("Listing machines the marketplace does not deliver") |
| D12 Negotiation and settlement compose the existing kit runtimes; a delivered introduction names the Agreement's seller | No new location: `openspec/specs/introduction-delivery/spec.md` already requires the delivered counterparty |
| D13 Bare metal publishes on a loop over held projections | No new location: in place before this change (`openspec/specs/storefront-publication/architecture.md#autonomous-publication`) |
| D14 The bare-metal evidence is VM's introduction scenario on shared stages; no root command registered twice | `docs/development/TESTING.md#4-system-integration-tests-end-to-end` and `#the-canonical-compute-deal`; `openspec/specs/buyer-orchestration/spec.md#requirement-two-domains-may-not-register-one-root-command` and `#requirement-buyer-mechanism-utilities-are-namespaced` (archive); `openspec/specs/buyer-orchestration/architecture.md#current-limits`; `docs/development/DEPLOYMENT_AND_CONFIG.md#introduction-delivery` (the lanes' mail sink) |
| D15 Goal 7 closes on single-site evidence | `docs/development/ROADMAP.md#goal-7--sell-capacity-the-marketplace-cannot-admit-against`; the unowned two-seller row in `openspec/changes/README.md` |
| D16 Settlement verifies against the plan committed at acceptance; bare metal continues against its opening's listing record; the codec limit | `openspec/specs/settlement-servicing/spec.md#requirement-settlement-verifies-against-the-accepted-plan` (archive); `docs/development/ARCHITECTURE.md#settlement-configuration`; `openspec/specs/storefront-publication/architecture.md#bare-metal-listing-shapes` (bare-metal continuation); `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection` (limit) |
| D16, 85 F17: VM resolves a continuation against the listing as it now stands | `docs/development/ROADMAP.md#goal-4--make-a-domain-a-composition-of-kit` (unowned row) |
| D17 A buyer funds only what it derives; the accept reply carries no escrow terms; the run-log's opaque `listing_record`; the plan check on the escrow settle hook | `openspec/specs/buyer-orchestration/spec.md#requirement-a-buyer-funds-only-what-it-derives` and `openspec/specs/negotiation-protocol/spec.md#requirement-the-accept-reply-carries-no-escrow-terms` (archive); `openspec/specs/buyer-orchestration/architecture.md#persisted-runs` and `#configured-mechanism-choice-and-buyer-actions`; `docs/development/ARCHITECTURE.md#settlement-configuration` and `#kit-areas` |
| D18 An escrow proposal naming no escrow contract is refused; the listing decides what can settle | `openspec/specs/negotiation-protocol/spec.md#requirement-an-alkahest-obligation-uses-exactly-the-release-condition-its-listing-authorizes` and `#requirement-the-sellers-reference-amount-is-the-selected-options-rate` (archive); `openspec/specs/negotiation-protocol/architecture.md#terms-and-payment-acceptance` (with VM's unchecked pinned carrier and the duplicated unpinned predicate); `docs/development/ARCHITECTURE.md#deciding-which-party-is-authoritative`; `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` (row closed) |
| D19 An unusable Alkahest section is unready; blocker kinds; the chain probe; API credits' seed loop, retryable create, and CLI through the running storefront | `openspec/specs/settlement-configuration/spec.md#requirement-an-alkahest-section-that-cannot-settle-makes-alkahest-unready`, `#requirement-readiness-blockers-state-their-kind`, `#requirement-alkahest-probes-its-chains-apart-from-readiness`, and `openspec/specs/storefront-publication/spec.md#requirement-an-alkahest-listing-advertises-its-release-conditions`, `#requirement-complete-bare-metal-seller-lifecycle`, `#requirement-api-credit-listing-creation-waits-for-or-names-an-unreachable-mechanism` (archive); `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection`; `openspec/specs/market-composition/architecture.md#settlement-configuration-registration`; `docs/development/ARCHITECTURE.md#settlement-configuration` and `#kit-areas`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust` and `#bare-metal-role-configuration`; `docs/bare-metal-seller-quickstart.md#start-and-inspect`; `docs/seller-quickstart.md`; `docs/development/TESTING.md#2-integration-tests` (loop table) |
| D19 limits: removed Alkahest inputs or address-book entries with open obligations; a disabled Arkhai-payments section reports nothing | `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection` |
| D19 limit: an API-credit listing's options are fixed at creation | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` (unowned row); `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection` |
| D20 The VM storefront starts degraded; no init-container or in-process dependency waits; `startupProbe` | `openspec/specs/deployment-state/spec.md#requirement-a-deployment-does-not-wait-on-a-services-dependencies` and `#requirement-a-storefront-chart-passes-service-configuration-through` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting` and `#storefront-startup-and-site-trust`; `docs/development/TESTING.md#chart-render-tests` |
| D21 Helm test pods carry no workload selector label | `openspec/specs/deployment-state/spec.md#requirement-helm-test-pods-carry-no-workload-selector-labels` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md#release-topology`; `docs/development/TESTING.md#chart-render-tests` |
| D22 Scenarios hold shared services for the whole module | `openspec/specs/test-compatibility/spec.md#requirement-scenarios-hold-shared-services-for-the-whole-module` (archive); `docs/development/TESTING.md#2-integration-tests` |
| D23 Unserved stored providers stop startup; failures after authentication are signed | `openspec/specs/resource-pool-management/spec.md#requirement-a-service-refuses-to-start-while-a-stored-pool-names-an-unserved-provider` and `openspec/specs/physical-provisioning/spec.md#requirement-a-failure-after-authentication-is-answered-signed` (archive); `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation`; `openspec/specs/physical-provisioning/architecture.md#canonical-requests-durable-replay-and-signed-responses` (with the streamed-response limit); `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust` |
| D24 Stage events go to a follow-up change | No permanent document: `redesign-storefront-stage-events` in `openspec/changes/README.md` |
| D25 Upgrade order cannot matter in the supported deployment shape | No permanent document: a property of the one supported deployment shape, recorded in `design.md` |
| D26 Edits to other changes | On this branch, in those changes' own files |
| D27 A command module's factories are its test seam | `docs/development/TESTING.md#1-unit-tests` (command-module convention); `docs/development/ROADMAP.md#goal-4--make-a-domain-a-composition-of-kit` (unowned row) |
| Roadmap currency (23.5) | `docs/development/ROADMAP.md` Goals 4, 6, and 7 |
| Campaign index currency (23.6) | `openspec/changes/README.md`: this change's row and the Goal 7 campaign text |
