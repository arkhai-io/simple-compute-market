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
      Done: `ReadinessBlockerKind` exported. Unit, `make -C kit test-settlement-runtime`:
      110 passed.
- [x] 3.2 `kit/arkhai-payments/.../settlement_config.py` (`_blocker`) and
      `kit/contact-exchange/.../settlement_config.py` (`contact_preflight`): every blocker
      is a configuration blocker, since neither contacts anything during readiness. Tests
      in `kit/arkhai-payments/tests/test_settlement_config.py` and
      `kit/contact-exchange/tests/unit/test_settlement_config.py` (unit) (D19).
      Unit, `make -C kit test-arkhai-payments test-contact-exchange`: 84 and 127 passed.
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
      Done. The two resources the composing storefront supplies are
      `deliverable_release_models` and `signs_transactions`; new codes
      `alkahest.oracle_is_seller_wallet`, `alkahest.release_model_undeliverable`,
      `alkahest.wallet_key_missing`, `alkahest.chains_missing` (the existing
      `alkahest.interruptible_policy_invalid` already covered a missing interruptible
      oracle). The `wallet_ready` resource is no longer read; bare metal still passes it
      until 5.2. **Differed:** not every blocker is configuration. A contract probe that
      does not answer is the reachability blocker `alkahest.contract_probe_failed`, since
      it cannot tell a missing contract from an unreachable chain, and one that answers
      "not deployed" is the configuration blocker `alkahest.contract_missing`; both go with
      4.2. The oracle-equals-wallet check applies to the seller role only, since an escrow
      pays the seller's wallet (a buyer case asserts it). Blockers are built through `_configuration_blocker` and
      `_reachability_blocker`, so no Alkahest blocker takes a kind by default; a unit case
      asserts the kind of each pre-existing chain and input blocker too. A section
      selecting both models is not a blocker: it stays the startup refusal, which the
      preflight's docstring states. **Differed:** the release-model constants,
      `ReleaseModelError`, and `configured_release_model` moved from `release_conditions.py`
      into `settlement_config.py`, which `release_conditions.py` imports, so the preflight
      reads the model at module level rather than through a circular local import; the
      package's exports are unchanged.
- [x] 3.4 `kit/alkahest/src/market_alkahest/release_conditions.py`: delete the seller-wallet
      fallback for the oracle (and the docstring that describes it);
      `publication_release_conditions` takes the clauses' readiness and returns nothing
      for a clause whose mechanism is unready. `configured_release_model`'s refusal of a
      section that is both oracle-gated and interruptible stays a startup refusal:
      incoherent configuration stops startup (D19's retained refusals). Export changes in
      `__init__.py` (D19).
      Done: `publication_release_conditions(config, clauses, *, readiness, chains,
      wallet_address)`, `readiness` the `MechanismReadiness` tuple publication built its
      options under. `release_conditions` refuses an interruptible model with no oracle of
      its own, and an interruptible oracle equal to the wallet, as it refused the
      oracle-gated cases. `__init__.py` needed no change. Unit, `make -C kit
      test-alkahest`: 319 passed (3.5's kit cases included). The module docstring names
      both ways a composition checks the release model, at startup or at readiness, since
      every storefront still checks it at startup until Section 5.
- [x] 3.5 Tests (unit): `kit/alkahest/tests/unit/test_settlement_config.py` — one case per
      new blocker, each with its kind, and a buyer-role preflight unchanged;
      `test_release_conditions.py` — the fallback test inverted to a refusal, and
      `publication_release_conditions` yielding nothing for an unready clause. Update the
      direct `ReadinessBlocker` constructions in
      `domains/vms/storefront/tests/unit/cli/test_settlement.py` and
      `tests/unit/test_settlement_publication.py` (D19).
      Kit cases written and passing (in 3.4's run); the two VM files pass in VM's unit
      suite. Also changed: VM's `tests/unit/test_listing_settlement_config.py` reads the
      readiness `_derive_settlement_artifacts` now returns, and the publication harness's
      settlement double (`tests/publication_app.py`) reports Alkahest ready wherever it
      builds Alkahest options, as the real composition does, since demands are now derived
      only under a ready Alkahest.
- [x] 3.6 Versions: `arkhai-kit-settlement-runtime`, `arkhai-kit-alkahest`,
      `arkhai-kit-arkhai-payments`, `arkhai-kit-contact-exchange`; `make lock`.
      Bumped: settlement runtime 0.5.0, Alkahest 0.9.0, Arkhai payments 0.3.0, contact
      exchange 0.4.0 (minor: the blocker carrier and `publication_release_conditions` are
      changed contracts); VM storefront 0.17.1 and API-credit storefront 0.10.1 (patch,
      for the brought-forward edits below). Packages whose only change is a dependency
      bumped a patch so the new requirement ships: `arkhai-kit-config` 0.4.1,
      `arkhai-core-buyer` 0.5.1, `arkhai-vms-buyer` 0.7.1, `arkhai-bare-metal-buyer` 0.5.1,
      `arkhai-bare-metal-storefront` 0.17.1, with the exact pins on them updated. Every
      exact pin on the four kits moved; the Alkahest floor is `>=0.9.0` in every package
      that requires settlement runtime 0.5.0 (both storefronts beside VM's, both compute
      buyers), since Alkahest 0.8.0 builds blockers without a kind; and in the API-credit
      buyer (0.5.1), which runs the Alkahest preflight and reaches runtime 0.5.0 through
      `arkhai-core-buyer`. Packages that never build a readiness blocker keep their floors
      (`domains/apicredits`, `kit/storefront`, VM's settlement, negotiation, and listings
      packages); `e2e-tests` installs the buyers, whose floors carry the bound.
      `make lock` refreshed every lock (the two VM locks once the PyTorch index was
      reachable, below).
- [x] 3.7 **Verify.** `make -C kit test-settlement-runtime test-alkahest
      test-arkhai-payments test-contact-exchange` (unit); `make test-storefront`; `make
      test`; `make check-packaging`. End-to-end: `e2e_deal`, `e2e_alkahest_escrow_codecs`,
      and `e2e_credits_deal` read readiness through status once deployed; no scenario
      configures an unusable section, and none is owed (integration covers each blocker).
      Results: the four kit suites (above); `make test-storefront` unit 1101 passed,
      integration (application integration, the app through its typed client, plus the
      chain-backed `test_alkahest.py`) 446 passed and 2 failed, both `tests/integration/test_alkahest.py`
      (`test_rust`, `test_python`), which need host Node.js and Anvil this container lacks
      (`could not spawn node`), environmental and unrelated; `make test-apicredits` and
      `make test-bare-metal` all passed. `make test` was run by its components, since one
      run outlasts the session's ten-minute command bound: `test-core`, `test-kits`,
      `test-compute-provisioning-contracts`, `test-compute-provisioning-client`,
      `test-compute-provisioning`, `test-compute-provisioning-ansible`,
      `test-provisioning`, `test-provisioning-iac`, `test-registry`,
      `test-registry-client`, `test-provisioning-adapter`, `test-compute`,
      `test-vms-domain`, `test-vms-buyer`, and `test-e2e-unit` all passed;
      `test-deployment-packaging`'s Python checks passed (1079) and its chart render half
      did not run, since `helm` is not installed here. That half matters: the VM chart's
      render test (`helm/charts/storefront/tests/test_render.py`) probes
      `demands_for_publication_clauses` in the storefront's environment, and its probe now
      passes a ready Alkahest, since readiness turns on a reachable chain and the overlay's
      key, neither of which a render carries. The probe edit is **unrun**; run `make -C helm
      test-render` with `make init-storefront` done before this round is reviewed. After
      the review fixes, the Alkahest, core, kit, VM buyer, VM storefront (same two host-tool
      failures), bare-metal, API-credit, e2e unit, and provisioning suites were rerun and
      passed; `make check-packaging` passed; `make check-change` (comment hygiene, skills,
      citations, task list, index, strict validation) fails only on the two citations of
      files Sections 13 and 22 create. The repository has no typing target. End-to-end scenarios, confirmed by reading
      their source rather than by a run: `e2e_deal`, `e2e_alkahest_escrow_codecs`, and
      `e2e_credits_deal` read readiness through status; none configures an unusable section.

Section 3 notes (handoff):

- **Brought forward from Section 5,** because Section 3's kit changes reach these call
  sites and the section's commit must pass on its own: VM's demand derivation moved from
  `publication_loop._create_request` into `listing_service.derive_listing`, after
  `publication_artifacts`, through `demands_for_publication_clauses(..., readiness=)` (the
  loop's `wallet_address` argument went with it) — 5.1's derivation half; and the API-credit
  composition passes its seller wallet to the preflight as `wallet`, without which deleting
  the `has_composed_client` shortcut made API-credit Alkahest unready — 5.3's wallet half.
  Section 5 keeps the rest of 5.1 and 5.3. Since `derive_listing` also serves the
  operator's `POST /api/v1/listings`, a create carrying clauses now gets derived demands
  rather than the `demands` it was sent, as 5.1's "`listing_service.py` derives them"
  intends. Not covered by any section: a VM create carrying `accepted_escrows` and no
  clauses still publishes the `demands` its caller sent, unchecked against readiness,
  and a create carrying clauses ignores the `demands` it was sent rather than refusing
  them as it refuses `settlement_options` (decision 19 gates request-supplied escrows only
  for API credits). Recorded for the round's triage.
- **Declined from review:** the API-credit `release_conditions` docstring ("an unset
  wallet still derives a condition") is still true for escrows a listing request
  supplies, which 5.3 gates; and the derivation's reading of the process's settlement
  configuration and wallet rather than the composition's is as before (the loop read the
  same global wallet), both resolving the one configuration the process started on.
- **For closeout (23.9):** `openspec/specs/storefront-publication/architecture.md`
  "Settlement option reconciliation" says VM "can advertise a condition for a chain whose
  option readiness suppressed" and that a storefront refuses to start configured for an
  undeliverable model; both stop being true with Sections 3 and 5.
- **Left to 5.4, which owns them:** the storefront-level tests that an unready VM Alkahest
  yields no demands and refuses no candidate, and that an API-credit storefront with no
  `wallet.address` reports Alkahest unready; Section 3 proves both rules at kit level
  only. VM's publication harness double stands in for mechanism readiness (it reports
  Alkahest ready wherever it builds Alkahest options), so its tests do not exercise the
  real preflight; 5.4's unready case needs the real readiness or a double reporting a
  blocker.
- **For 5.2:** a wallet given as a bare string has no key, so once bare metal passes
  `signs_transactions` it must pass its wallet as a mapping carrying `private_key`, or it
  reports `alkahest.wallet_key_missing` whatever its configuration.
- **Not changed:** VM's human-readable `settlement status` lists blocker codes without
  their kind; the JSON output carries it.
- **Environment.** `domains/vms/storefront`, `domains/vms/buyer`, and `kit/policy` pin
  `torch` to `download.pytorch.org`; every lock refresh and `reinit` of them fetches that
  index, so a session whose egress refuses it can neither build their environments nor
  relock them. The owner widened this session's egress, after which both resolved.
- **Seam.** Tests run only through `make` targets here, so a single failing test is read
  from the target's log, not rerun alone.
- **Round 1's triage.** 85 F14: `require_deliverable_release_model` and its tests are
  removed, and the `release_conditions` docstring names readiness as the only check of a
  release model; nothing outside tests called it. 91 O1: the two chain-backed tests of
  `domains/vms/storefront/tests/integration/test_alkahest.py`, which drove the Alkahest
  SDK through a trusted-oracle settlement against a chain the SDK spawns and so failed
  wherever Node.js and Anvil are absent, move to the end-to-end tier as
  `scenarios/core/test_alkahest_trusted_oracle.py` (marker
  `e2e_alkahest_trusted_oracle`, in the VM lane's module list), which runs the same
  escrow, fulfillment, arbitration, and collection against the lane's Anvil with its
  funded buyer and seller and Anvil account #0 as the oracle. They exercise the SDK and the
  chain, not the storefront, so no integration test is owed in their place. It is in the
  Helm `e2e` step's served list as well: it passed against the charts at `9aa024e` under
  `HELM_ALL_SCENARIOS=1` (132 F1). Section 3's "Not covered by any section" note on a VM
  create's supplied `demands` is answered by 85 F9 (Section 5). Evidence: the round's note
  under Section 10.
- **Round 1's second triage.** 122 F3: `test_alkahest_trusted_oracle.py` no longer
  builds its arbiter and demand with the SDK alone. It derives the release condition an
  oracle-gated seller advertises through `kit/alkahest`'s `release_conditions`, and
  encodes it through `encode_authorized_release_condition`, as every plan is encoded, so
  the scenario proves the kit's condition against the deployed trusted-oracle arbiter. The
  arbitration request carries the condition's own inner data, which is empty; each run's
  fulfillment is new, so no unique demand is needed. Evidence: the second triage's note
  under Section 10.
- **Round 1's third triage.** 132 F1: the round-1 note's reason for keeping
  `e2e_alkahest_trusted_oracle` off the Helm `e2e` step, that the release may not fund the
  seller, did not hold: the Helm chain loads the same baked state as compose, and the
  scenario passed there at `9aa024e` under `HELM_ALL_SCENARIOS=1`. It joins
  `HELM_SCENARIOS` in `scripts/validate_slice.py`, and the note above states it. The same
  validation showed the all-scenarios selection incomplete: `PIPELINE_MARKER_VARIABLES`
  now reads `E2E_APICREDITS_MODULE` too, so the API-credit scenarios appear in a Helm
  summary's `not_run` map and run under `HELM_ALL_SCENARIOS=1`, and that mode now runs the
  served list beside the pipeline's scenarios, so `contracts`, in no lane, is no longer
  dropped. Unit cases in `scripts/tests/test_validate_slice.py`. Evidence: the third
  triage's note under Section 10.

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
      Done: `AlkahestChainProbe(chains, *, build_client, clients, interval_seconds,
      rpc_timeout_seconds, json_rpc, required_addresses, clock)` over `ProbedChain`s
      (`ProbedChain.from_config`), results as `ChainProbeResult(result, probed_at)`;
      `step()` probes every chain and returns them with every chain's public result; the
      loop's timer, not the step, spaces the calls, so an operator's explicit step always
      probes (the first version skipped chains probed within the interval, which made a
      step inside it a no-op; review caught it). A probe runs
      in a worker thread, address configuration first (its failure is
      `alkahest.address_config_invalid`, a configuration result), then `eth_chainId`, then
      `eth_getCode` at each required contract (`recipient_arbiter`, `eas`, and the ERC-20
      default escrow obligation), the address book's when one resolves and the SDK's
      defaults otherwise. Only `probe_addresses_sync` stays for the VM buyer; the async
      `probe_addresses`, `ChainProbeError`, and `fail_on_missing` went. Exported with
      `ALKAHEST_CHAIN_PROBE_LOOP` (`alkahest_chain_probe`) and `ALKAHEST_CHAIN_PROBE_ROUTE`
      (`alkahest-chain-probe`).
- [x] 4.2 `alkahest_preflight` reads the probe's results from a `chain_probe` resource and
      makes no chain call: per chain its clauses use, no result yet or an unreachable
      result is the reachability blocker `alkahest.chain_unreachable`; a mismatch or
      missing contract is the configuration blocker of the same name. Delete
      `alkahest.contract_probe_failed` and the `observed_chain_id`, `deployed_contracts`,
      `contract_probe`, and `required_addresses` resources. A preflight given no probe — a
      buyer's — reports no chain blocker, as before. Alkahest's `public_detail_keys` gains
      the per-chain result and when it was taken, so status reports both through the
      mechanism's readiness and core's status model stays mechanism-neutral (D19).
      Done: a chain's blocker comes from its probe result (`_chain_probe_blockers`), only
      for the chains the selected clauses use; the public detail `chain_probe` carries
      each chain's result and `probed_at`. **Differed:** "status reports both" needed a
      field: no storefront's status carried mechanism readiness, so each status gains a
      mechanism-neutral `settlement` list of the mechanisms' safe projections (core
      `HealthResponse.settlement` and the storefront client's model, bare metal's
      `BareMetalHealthResponse.settlement`), which is how the integration tests in 4.6 read
      the probe result through the typed client.
- [x] 4.3 Settings: `[Settlement.alkahest]` gains a probe interval (30 seconds by default)
      and an RPC timeout (5 seconds by default), positive seconds refused by key otherwise,
      as every storefront duration is (D19).
      Done: `probe_interval_seconds` and `rpc_timeout_seconds`, `PositiveSeconds` from
      `kit/config` (a new declared dependency of `kit/alkahest`, which also retires the
      `ARCHITECTURE.toml` exception row excusing that edge as undeclared), seller-only. The
      three values schemas carrying the generated definition were edited by hand to the
      generator's output, since `make helm-values-schema` was not permitted in this
      session; VM's and bare metal's drift tests pass against them.
- [x] 4.4 `kit/storefront/src/market_storefront_kit/alkahest_clients.py`: expose the
      factory's per-chain construction as a constructor the probe calls, so a chain whose
      construction fails is no longer dropped for the life of the process; the kit gains
      no probe, schedule, or other Alkahest behaviour. Confirm whether the SDK's
      construction opens the RPC connection and say so in the constructor's docstring;
      either way the probe rebuilds a missing client, and an address-configuration failure
      remains `alkahest.address_config_invalid` (D19, D20).
      Done: `alkahest_client_constructor(policy)` returns the per-chain constructor, or
      `None` when the policy is missing a requirement (the wallet key, or what the caller's
      policy names); a policy with no chains gets a constructor with nothing to construct.
      `build_alkahest_clients` uses
      it. Confirmed: an HTTP `rpc_url` builds without contacting the RPC, and a websocket
      one connects at construction, so only a websocket chain's client is missing while it
      is unreachable. A test pins that behaviour against the installed SDK
      (`kit/storefront/tests/integration/test_alkahest_sdk_construction.py`). It connects
      to a refused loopback port, so it is not a pure unit test: it was written in
      `tests/unit/` under a scratch name and moved, with Section 8, to the kit's new
      `tests/integration/`, which the kit's `make test` and `testpaths` now run beside
      `tests/unit/`.
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
      Done. VM and API credits build the probe in `server.py` over the client map, hold it
      on the container (`resolved_alkahest_chain_probe`), and pass it to the settlement
      composition, which hands the same map to every consumer; bare metal builds it in
      `build_runtime_from_configuration`, whose new `build_chain_client` parameter (the
      kit constructor by default) is a seam no test uses yet. Bare metal's consumers read
      the map through `BareMetalStorefrontSettlementComposition.chain_clients`, the map
      itself even while empty; an `or {}` there had handed servicing a fresh dict whenever
      no client was built at start (review caught it). A storefront with no Alkahest
      section composes no probe and registers no probe loop (VM's step reports the loop
      disabled). VM and bare metal also probe a configured but disabled section, whose
      accepted obligations are still serviced over its chains; API credits builds neither
      clients nor a probe for a disabled section, as it built no clients before. VM's
      `_token_transfers_available` and `_alkahest_available` are properties read per call.
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
      Done. Unit: `test_chain_probe.py` — each result, `eth_getCode` failing after
      `eth_chainId` answers, the configured timeout reaching every call, the required
      contracts read from the development address book through the default
      `required_contract_addresses`, readiness making no chain call however often it runs,
      every step probing, readiness reporting a held result however old, and a client
      rebuilt into the live map; the probe-result blocker cases and the two settings in
      `test_settlement_config.py`; the constructor in `test_alkahest_clients.py`; VM's
      `tests/unit/test_alkahest_chain_probe_composition.py` (the probe composed over the
      map with the section's interval and timeout, none without a section); bare metal's
      `test_app_composition.py` (the composition and servicing hold the probe's map, an
      empty one included, and see a client added to it). Application integration through
      `StorefrontClient`, one per storefront, with a stub JSON-RPC transport at the probe's
      boundary: the loop is listed and steppable, an unanswering chain reports
      `alkahest.chain_unreachable` and the probe result in status, and a stepped probe once
      it answers makes Alkahest ready without a restart. **What these do not cover:** VM's
      and API credits' tests replace both the container's probe and its settlement
      composition with doubles whose readiness hands the probe in by hand, so the
      production hand-off of `chain_probe` in their settlement compositions, API credits'
      `_build_alkahest_chain_probe`, and VM's per-call client availability are untested at
      that level. Bare metal's is the same shape: it hands its probe by hand to a
      test-built composition and runtime, and the production hand-off in
      `build_runtime_from_configuration` is covered only by `test_app_composition.py`'s
      identity assertions. The three tests step the probe twice with no clock advance
      between, so each also shows a step inside the interval acts. No storefront test
      shows a rebuilt client reaching a consumer through a real step; the kit's test and
      bare metal's identity test together stand for it. The "every loop" tests in all three
      list the probe loop.
- [x] 4.7 Versions: `arkhai-kit-alkahest`, `arkhai-kit-storefront` (exact pins in the
      storefronts), and the three storefronts; `make lock`.
      Bumped: Alkahest 0.10.0, kit storefront 0.9.0, `arkhai-core-storefront` 0.16.0 and
      `arkhai-core-storefront-client` 0.27.0 (the status field), VM storefront 0.18.0,
      bare-metal storefront 0.18.0, API-credit storefront 0.11.0; patch bumps for pins
      only: capacity publication 0.10.2, compute provisioning service 0.17.3. Every exact
      pin on them moved, and the floors of the packages that need the new versions (the
      storefronts' Alkahest and status-model floors); floors in packages that read neither
      the new field nor the probe were left (`kit/storefront`'s core floors, bare metal's
      runtime core floors, `e2e-tests`, the provisioning service's dev group). `make lock`
      refreshed every lock. The publish
      manifest (`manifests/published-distributions.json`) now lists `arkhai-kit-config`
      before `arkhai-kit-alkahest`, and `docs/development/RELEASING.md` names the new
      dependency, as the release-tooling tests require.
- [x] 4.8 **Verify.** `make -C kit test-alkahest test-storefront`; `make test-storefront`,
      `make test-bare-metal`, `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: every lane's Alkahest scenario (`e2e_deal`, `e2e_buy`,
      `e2e_alkahest_escrow_codecs`, `e2e_bare_metal_mock_deal`, `e2e_credits_deal`)
      publishes only after the first probe, so each passing proves the loop runs.
      Results, rerun after the review fixes: `make -C kit test-alkahest` 347 passed and
      `test-storefront` 127 (unit); `make test-storefront` unit 1103 passed, integration 447
      passed and the same two environmental `test_alkahest.py` failures (`test_rust`,
      `test_python`: no host Node.js or Anvil); `make test-bare-metal` (storefront 440) and
      `make test-apicredits` all passed. Before the fixes, `make test`
      by its components, as in Section 3: `test-core`, `test-kits`, the four compute
      provisioning suites, `test-provisioning`, `test-provisioning-iac`, `test-registry`,
      `test-registry-client`, `test-provisioning-adapter`, `test-compute`,
      `test-vms-domain`, `test-vms-buyer`, and `test-e2e-unit` passed (the fixes touch only
      `kit/alkahest`, `kit/storefront`, and the three storefronts, rerun above);
      `test-deployment-packaging`'s Python checks passed (1079) after the manifest fix, and
      its chart render half is **unrun** (no `helm` here), as is Section 3's render-probe
      edit. After the review fixes, `make check-packaging` passed, and `make check-change`
      (comment hygiene included) fails only on the two citations of files Sections 13 and
      22 create. End-to-end, confirmed by reading the
      scenarios rather than a run: the VM and bare-metal lanes configure Alkahest on their
      dev chain with publication clauses, so `e2e_deal`, `e2e_buy`,
      `e2e_alkahest_escrow_codecs`, and `e2e_bare_metal_mock_deal` publish their Alkahest
      options only once the probe has seen the chain. `e2e_credits_deal` is **not**
      evidence for the loop: API credits seeds its listing during startup, before its loops
      start, from escrows the seed supplies rather than clauses, and that path does not
      read readiness until 5.3 gates it (Section 6 then moves the seed onto a loop step).
      None steps the probe: its first cycle runs as its timer starts, before any scenario's
      stage-0 pause, so a lane whose chain is not yet answering at that first cycle and
      whose loops are then held reads Alkahest unready until the probe is stepped. The
      pipeline run validation makes is the evidence of whether that happens.

Section 4 notes (handoff):

- **The loop's first cycle runs as its timer starts,** then every interval (30 s by
  default); a stepped `alkahest-chain-probe` run-cycle probes at once, whenever it is
  sent. Until the first cycle has run, Alkahest
  is unready with a reachability blocker, which Section 18's hold rule reads; Section 6's
  `listing-seed` step waits on it.
- **The probe owns the one client map,** created by the composition root and handed to
  the probe and every consumer by reference; nothing may copy it, or a rebuilt client
  never reaches the copy.
- **The constructor is `None`** when the policy is missing a requirement (the wallet key),
  so a storefront in that state probes reachability but never builds a client; bare
  metal's missing-input refusals still stop startup before that until 5.2.
- **For 5.1/5.3:** VM's settlement composition supplies the `wallet` resource only when
  the section is enabled or the client map is non-empty at composition, a decision taken
  once on a map that may be empty at start; Section 5's wallet change supplies it whenever
  a section is configured.
- **Status's `settlement` field** is new in all three storefronts; Section 5's tests can
  read a blocker through it.
- **Not done here:** `ARCHITECTURE.md`'s note that `kit/alkahest` "reads a user
  configuration file" still stands (the aggregation timeout), owned elsewhere; only the
  undeclared-import row went, recorded in `design.md` decision 26.
- **Fresh-context review, findings declined:** status readiness in VM and API credits is
  evaluated without clauses, so only the default chain raises a blocker there, while the
  `chain_probe` detail reports every chain's result (kept; the same readiness the
  `settlement status` command shows); the constructor test patches the kit's dependency
  loader and VM's composition test replaces settings, both the existing patterns of those
  files; the hand-edited values schemas stand on the drift tests, since the generator is
  not permitted here; `chain_probe.py` imports `_sdk_addresses_for_chain` from its own
  package's `alkahest` module, which is within one package; the disabled-section probe is
  kept as recorded under 4.5, since the permanent "only when invoked or enabled" sentence
  governs the status command's checks and a disabled section's servicing already uses its
  chains.
- **Round 1's triage.** 85 F7: a chain whose client the probe could not construct reads
  `alkahest.chain_unreachable` whatever its RPC answers (`_probe` in `chain_probe.py`);
  a probe with no constructor reports what the chain answers; the module docstring states
  the `ws`→`http` probe mapping. 85 F8: `_construct_missing_client` builds a client in a
  worker thread under `asyncio.wait_for` with the probe's timeout, and only a construction
  that finished in time enters the map. 85 F10: with no `accepted_escrows` and no
  `chain_name`, readiness judges every configured chain (`_selected_chain_names`;
  `default_chain` no longer selects there), and every storefront's status asks with no
  publication input — bare metal's status now passes `clauses=()` rather than its
  clauses. 85 F3: VM's `VmCompositionSeams` and API credits' new
  `ApiCreditCompositionSeams` carry the Alkahest client constructor and the JSON-RPC
  call, and bare metal's `build_runtime_from_configuration` takes `chain_json_rpc`;
  `build_alkahest_clients` takes `constructor=`. Tests: kit unit
  (`test_chain_probe.py`: a construction failure reads unreachable, no constructor, a
  hung construction across two chains; `test_settlement_config.py`: no publication input
  judges every chain, with and without `default_chain`); VM unit composition
  (`test_alkahest_chain_probe_composition.py`: the probe, its client map, and the loop
  registered through the real `_build_settlement_composition`, stepped through
  `lifecycle_steps.alkahest_chain_probe_step` — VM has no harness starting its whole
  application with seams, so this is the composition boundary, not the started app); API
  credits integration (`test_alkahest_release_conditions.py`: the started application
  through `StorefrontClient`, its probe and seed sharing one map, status naming an
  unanswering second chain); bare metal composition (`test_app_composition.py`: the
  configured runtime's registered probe loop run through `loops.run_cycle`, and status
  naming an unanswering second chain). Evidence: the round's note under Section 10.
- **Round 1's second triage.** 122 F1: 85 F8's fix bounded the wait but started a new
  construction, on the loop's default executor, at every probe, so a construction that
  never returns would fill that executor, which every database call shares, within
  minutes. `AlkahestChainProbe` now keeps each chain's pending construction: it runs on a
  daemon thread of its own (`_start_construction`), a probe waits for it no longer than
  the RPC timeout (`asyncio.wait`, which leaves it running), a probe finding it still
  running starts no other and reads the chain unreachable, and a probe finding it
  finished adopts its client or, if it failed, reads the chain unreachable, and the next
  probe builds again. The `settlement-configuration`
  delta's requirement says so, with the scenario "A client's construction never returns";
  decision 19's timeout bullet records it. Tests: kit unit (`test_chain_probe.py`: five
  probes over a never-returning constructor start one construction, with the loop's
  default executor reduced to one worker and still answering; a construction finishing
  after its probe's wait is adopted by the next probe, which reads the chain reachable).
  122 F4 is planned in 11.5. Evidence: the second triage's note under Section 10.

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
      Note: the derivation after readiness landed with Section 3 (its notes); this task
      keeps the startup call's removal, the deliverable models, and 5.4's tests.
      Done: `require_vm_release_model` became `require_coherent_release_model`, which
      refuses only a section selecting contradictory models (`configured_release_model`),
      in `server.py` before anything is built and in the composition. The composition
      hands the preflight `deliverable_release_models` (the domain's Alkahest entry's) and
      `signs_transactions`, and supplies the wallet, key included, whenever a section is
      configured rather than only when enabled or when clients exist. **Beyond the plan:**
      `groups/settlement.py`'s `settlement status` command reads the wallet and chains of
      any configured section and passes `signs_transactions` and VM's deliverable models,
      as the server's composition does, since it is an explicit
      check and a disabled section now reports its own blockers (below).
- [x] 5.2 Bare metal `src/runtime.py` `build_runtime_from_configuration`: a configured
      section missing `[Wallet].address`, `[Chains]`, or `[Wallet].private_key` starts with
      the named configuration blockers rather than refusing; a `ReleaseModelError` for an
      undeliverable model no longer refuses startup; `settlement_service()` no longer
      refuses every settlement service when Alkahest lacks an address (Arkhai payments'
      reconciliation keeps running); Alkahest inputs supplied with no section are still
      refused. `settlement_composition.py` calls `publication_release_conditions` with
      readiness and passes the deliverable models (D19).
      Done. Missing inputs no longer refuse; clients are built only with a key and chains,
      and the probe is composed over the configured chains either way. The composition's
      `wallet` is a mapping carrying the key, beside `signs_transactions` and
      `deliverable_release_models`; `wallet_ready` is gone. The composition refuses only a
      contradictory section (`configured_release_model`), which the runtime still turns
      into a startup refusal naming it. `settlement_service()` no longer refuses when the
      address is missing. `publication_payload` derives `demands` through
      `publication_release_conditions` over its clauses and the readiness it published
      under. **Beyond the plan:** "enabled or not" needed `kit/settlement-runtime` and
      `kit/alkahest`. The runtime built a disabled section's readiness itself and never
      ran its preflight, so a disabled section could name nothing missing. It now reports
      `disabled` followed by the preflight's configuration blockers (reachability ones
      dropped). Alkahest's seller preflight for a disabled section reports what would stop
      servicing its accepted deals: wallet, key, chains, address configuration, release
      model. A buyer's disabled section reports nothing. Arkhai payments returns no
      blockers when disabled; contact exchange's seller preflight now also lists its own
      configuration blockers beside `disabled`.
- [x] 5.3 API credits: `settlement_composition.py` and `services/listing_service.py`
      derive release conditions after readiness, gating the escrows a listing request
      supplies as well as those its clauses compile, so an unready Alkahest yields no
      escrow option on either path; `require_api_credit_release_model`'s startup call goes;
      the preflight is given the wallet and the deliverable models (D19).
      Note: the wallet landed with Section 3 (its notes); the deliverable models remain.
      Done: `require_coherent_release_model` replaces the startup call. The preflight
      also gets the wallet's key and `signs_transactions`, since the storefront submits
      issuance evidence with that key. The composition's `mechanism_resources` is
      excluded from its repr, as VM's now is. `readiness(accepted_escrows=)` judges
      Alkahest on the supplied escrows' chains. The listing service always judges
      supplied escrows on that readiness, clauses or not, and drops them while Alkahest is
      unready on their chains. `release_conditions(escrows, readiness=)` derives nothing
      while it is unready. The clause path was already gated by `publication_artifacts`.
      (Review caught a first version that judged supplied escrows on the clauses'
      readiness whenever clauses were present.) A clause-only create with
      an unready Alkahest still raises `RuntimeError` ("no enabled settlement mechanism is
      ready"), which the route answers 500; Section 6 owns that status (6.2).
- [x] 5.4 Tests (application integration through the typed client): bare metal
      `tests/test_app_composition.py` — the release-model and missing-input refusal tests
      inverted to unready-with-blocker starts, and the no-section refusal kept; VM
      `tests/integration/test_release_model_startup.py` — an undeliverable model starts
      unready, the both-models refusal kept; VM `tests/integration/test_publication_loop.py`
      — an unready Alkahest publishes the other mechanisms' options and refuses no
      candidate; API credits `tests/integration/test_alkahest_release_conditions.py` — an
      undeliverable model or missing oracle yields no Alkahest option on the clause and the
      supplied-escrow paths; each storefront's status reporting the blocker (D19).
      Done.
      - Bare metal `tests/test_app_composition.py`:
        - each missing input, enabled and disabled, starts with Alkahest unready naming
          it, and contact exchange stays ready. This reads the composition's readiness
          over a runtime built from the files (composition level).
        - an undeliverable model starts unready, at the same level.
        - application integration through `StorefrontClient`: a storefront started from
          its files, with an undeliverable model, reports the blocker in the
          administrator's status while contact stays ready.
        - the contradictory-model refusal, which before was covered only through the
          section model, gets a file-level case and the lifespan case (rewritten from the
          interruptible refusal); the no-section refusal is kept unchanged.
        - the missing-input and undeliverable-model cases stay at composition level
          rather than through the typed client, one typed-client case standing for them.
          Each blocker is the kit's unit case; what bare metal adds is that it starts,
          which the files-built runtime shows.
      - VM:
        - `tests/integration/test_release_model_startup.py` keeps the both-models refusal
          unchanged.
        - **Differed:** VM's Alkahest entry delivers every model, so "an undeliverable
          model starts unready" cannot happen in VM's production contract. It is a unit
          case in `tests/unit/test_settlement_composition.py` instead: a contract whose
          entry declares only `recipient` composes without refusal, and the real
          readiness names `alkahest.release_model_undeliverable`.
        - `tests/integration/test_publication_loop.py`: an unready Alkahest publishes the
          contact option and no escrow or demand, and refuses no candidate. The harness
          double gained `alkahest_blocker` to report Alkahest unready as the real
          composition does, so this exercises the publication path's handling of an
          unready readiness, not the real preflight.
        - VM has no test of its status reporting the blocker: VM's status serves the
          composition's readiness (Section 4's test) and the unit case above shows that
          readiness names it.
      - API credits `tests/integration/test_alkahest_release_conditions.py`, through the
        real app and settlement composition. The chain probe is replaced by patching
        `server._build_alkahest_chain_probe` to return a probe over a stub JSON-RPC
        transport, with no client constructor and the default interval, stepped
        directly rather than through its loop: the production probe wiring is Section
        4's test, not this one's.
        - the positive case now needs a wallet key and a probed chain.
        - an undeliverable model and a missing oracle each report the blocker in the
          administrator's status, and refuse a create whose only options are supplied
          escrows with 400 naming the blocker.
        - `tests/integration/test_publish_reconcile.py`, the listing service over a
          settlement double (library-integration level, real database): a supplied
          escrow judged unready on its own chain is dropped while the clause's escrow,
          judged ready on its chain, publishes. A real clause cannot compile here, since
          its option builder resolves the token on chain.
        - on the clause path, the composition's `publication_artifacts`, called
          directly, compiles no option; the condition check reads the supplied-escrow
          derivation, since the clause path raises before deriving one.
        - the contradictory-model refusal is kept.
      - Kit (unit):
        - `kit/settlement-runtime`: a disabled section reports `disabled` and then its
          configuration blockers.
        - `kit/alkahest`: a complete disabled section reports nothing more, each missing
          input names itself, and a buyer's disabled section reports nothing. The
          existing "disabled touches no client" case now expects `wallet_missing`.
- [x] 5.5 Versions: the three storefronts; `make lock`.
      Bumped: VM storefront 0.19.0 (its exact pin on bare metal moved), bare-metal
      storefront 0.19.0, API-credit storefront 0.12.0; `make lock` refreshed every lock.
      **Not bumped:** `kit/settlement-runtime` (0.5.0) and `kit/alkahest` (0.10.0) changed
      at versions this branch has not released (Sections 3 and 4), and the section's plan
      names only the storefronts. The storefronts' versions were unreleased too and were
      bumped because 5.5 names them; the kits were not, since a runtime bump cascades
      through every exact pin on it for nothing a release would see. `make
      check-packaging` passes on the rebuilt wheels. One policy for repeat bumps inside an
      unreleased change is the round's triage to settle.
- [x] 5.6 **Verify.** `make test-storefront`, `make test-bare-metal`, `make
      test-apicredits`; `make test`; `make check-packaging`. End-to-end: `e2e_deal`,
      `e2e_listing_shapes`, `e2e_bare_metal_mock_deal`, and `e2e_credits_deal` publish their
      Alkahest options through the reordered derivation.
      Results:
      - Unit kit suites: `make -C kit test-settlement-runtime` 111, `test-alkahest` 353,
        `test-arkhai-payments` 84, `test-contact-exchange` 127.
      - `make test-storefront`: unit 1104; integration 448 passed, with the same two
        environmental `test_alkahest.py` failures.
      - `make test-bare-metal` (storefront 442) and `make test-apicredits` (storefront
        189): all passed, rerun after the review fixes with the kit suites and
        `make test-storefront` (same counts and the same two environmental failures).
      - `make test`, by its components touched: `test-kits` (every kit), `test-core`,
        `test-vms-buyer`, and `test-e2e-unit` passed. The compute-provisioning and
        registry suites were not rerun, since nothing they install changed in this
        section.
      - `make test-release-tooling`, `make check-packaging`: passed.
      - `make check-change`: fails only on the two citations Sections 13 and 22 create.
      - End-to-end, by reading the lanes rather than a run: each lane supplies its
        storefront's wallet key (the compose overlays and the bare-metal secrets overlay),
        so `signs_transactions` leaves their Alkahest ready. `e2e_deal`,
        `e2e_listing_shapes`, and `e2e_bare_metal_mock_deal` cover the reordered
        derivation once deployed. `e2e_credits_deal` does only from Section 6 on (see the
        handoff below).

Section 5 notes (handoff):

- **For closeout (23.9):** `DEPLOYMENT_AND_CONFIG.md`'s "Bare-metal role configuration"
  still says a configured section "requires" the address, chains, and key, and that the
  storefront "refuses to start configured as `interruptible`". Both are now readiness
  blockers, and only a contradictory section refuses. The `settlement-configuration`
  architecture companion should state the disabled-section readiness rule.
- **For Section 6:** API credits' clause-only create with an unready mechanism answers
  500 today. 6.2's distinct error replaces it.
- **Between this section and Section 6, the API-credit seed publishes nothing.** The
  configured seed still runs during startup (`startup.py` `_seed_demo_listing`), before
  the loops start. So the chain probe has no result yet, Alkahest reads unready, the
  seed's supplied escrows are now gated out, and the seed logs "no settlement alternative
  is ready" and creates no listing. `e2e_credits_deal` would fail on a commit between the
  two. 6.1's `listing-seed` step, which waits for the probe, is the fix; the design
  rejected a startup probe pass before the seed (decision 19). Sections 5 and 6 are one
  round, validated together, so the gap is accepted between their commits rather than
  6.1 folded in here; the round's triage may decide otherwise.
- **Surprise:** the settlement runtime is where "enabled or not" had to land; no
  storefront could report a disabled section's missing inputs without it. Recorded in
  `design.md` decision 19 and the `settlement-configuration` delta (a disabled section's
  readiness lists its configuration blockers after `disabled`). At closeout, the
  companion's "evaluates every enabled registration" and the requirement "Common seller
  status covers enabled mechanisms" need reading against it.
- **Operator-visible:** VM and API credits now pass `signs_transactions`, so an enabled
  Alkahest with no `[Wallet].private_key` or no chain is unready and its options are
  withdrawn on the next cycle (VM) or refused at create (API credits). Before, it
  published options no deal could settle. Every lane and the local Helm release supply
  the key.
- **Not covered by a test in this section:** contact exchange's new blockers beside
  `disabled`; Arkhai payments reports nothing for a disabled section, though bare metal
  services its accepted payment deals whatever `enabled` says, so a missing credential
  there stays silent; bare metal's settlement service no longer refuses as a whole when
  the address is missing, and each Alkahest verification refuses its own deal instead
  (`settlement_stages.py`), which no new test exercises.
- **Declined from review:** the API-credit test patches `server._startup_tasks` and
  `server._build_alkahest_chain_probe`, as that file already patched its startup tasks.
  A server-level seam for the probe transport is a testability refactor no task names,
  so it is left for the round's triage. The integration parametrizations (two cases over
  three API-credit tests, three inputs times enabled and disabled in bare metal) were
  kept, since each case is a distinct configuration path at that level. The disabled
  readiness's repeated ID and secret checks and its extra preflight per readiness call
  were kept, since a disabled preflight reads only configuration and one address file.
- **Round 1's triage.** 85 F9: a VM create derives its release conditions from the
  storefront's `[Settlement.alkahest]` configuration whenever it publishes Alkahest
  options, supplied escrows or clause-derived alike
  (`publication_terms.demands_for_published_escrows`, called from
  `listing_service.derive_listing`), and a create carrying `demands` is refused with 400;
  the request model keeps the field, and the listing's `demands` and a buyer proposal's
  `demand` are unchanged on the wire. That also answers 88 V1: the multi-registry
  listings, created with supplied escrows and no `demands`, now advertise the derived
  condition. The four VM scenarios that passed `demands=` at create no longer do. The
  API-credit test's module patches of `_build_alkahest_chain_probe` are replaced by
  `ApiCreditCompositionSeams` (85 F3, Section 4). Tests: VM integration
  (`test_listings_api.py` `TestCreateListingReleaseConditions`: supplied escrows with no
  clauses get the derived condition under a ready Alkahest, none under an unready one, and
  supplied `demands` are refused with 400, through the typed client). The Helm
  render probe (`helm/charts/storefront/tests/test_render.py`) derives through
  `demands_for_published_escrows`. Evidence: the round's note under Section 10.

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
      Done.
      - The seed moved out of `startup.py` into `src/listing_seed.py` (`ListingSeed`,
        `register_seed_quota`, `capacity_authority_site`, `configured_listing_seed`).
        `server.py` installs it on the container (`resolved_listing_seed`).
        `lifecycle_steps.py` registers the step and the loop only while a seed is
        configured.
      - Waiting: a registration or availability read the credits service did not answer
        (no response, or a 5xx), or any mechanism the seed uses is unknown. The seed
        creates with `wait_for_every_mechanism`, so it waits whenever a mechanism it
        uses is unknown, even if another would publish: a listing's options are fixed
        at creation. Waiting is logged at INFO when its reason changes. A registration
        the ledger accepted is not sent again while the seed waits.
      - Given up: anything else. The cycle that gives up raises `ListingSeedGivenUp`, so
        the loop controller records a failed cycle with that type and logs it once at
        ERROR; later cycles do nothing and complete.
      - Done: an open listing derives from the resource, found or created.
      - The report names a reason code (`credits_service_unanswered`,
        `settlement_mechanism_unreached` with the mechanisms) or, given up, the error's
        type, never an error's text, which can carry the credits service's URL.
      - **Differed:** the loop retries every 2 s (`LISTING_SEED_INTERVAL_SECONDS`, or the
        probe's interval if shorter) rather than at the probe's 30 s. The lanes' scenarios
        discover once, right after the stack is healthy, so a seed that missed the probe's
        first result would otherwise be a whole interval late.
- [x] 6.2 `services/listing_service.py` and `controllers/listings_controller.py`: a create
      refused only because a mechanism is unknown raises a distinct error the route answers
      with 503, naming the unreached mechanism and that the create can be retried; a
      configuration refusal stays a 400 with its blocker codes (D19).
      Done:
      - `SettlementMechanismUnreachable(mechanisms, chains=)` is raised when no option
        publishes and every enabled, unready mechanism the request uses has only
        reachability blockers. A mechanism is used when a clause names it, by ID or
        configuration key (`canonical_mechanism` on the composition), or, for
        Alkahest, when escrows are supplied, judged on their own chains; and only when
        the pool's backing admits it. The refusal comes after the resource and its pool
        are read, so a create refused as retryable is one that publishes once the
        mechanism answers. Its message names each mechanism and the chains the request
        uses it on, as the spec scenario requires. The route answers it 503.
      - **Changed beside it:** the composition's `publication_artifacts` no longer raises
        `RuntimeError` when nothing is ready. It returns no artifacts and the readiness,
        so a clause-only create with an unready mechanism is now this 503, or the 400
        with its blocker codes, rather than the 500 Section 5 noted.
- [x] 6.3 `listing_publication.py`: `ApiCreditListingClient` and
      `SyncApiCreditListingClient` gain a list method over the listing route, in both
      variants. `cli.py` `publish` and `listings` call the running storefront through them
      and no longer build services or open the database in their own process (D19).
      Done. `list_listings(status, limit, offset)` on both clients delegates to the
      transport's own `list_listings`. `publish` signs as the storefront's principal
      (`resolve_identity_signer`) through `SyncApiCreditListingClient`, to
      `--storefront-url`/`-a`, else the configured `base_url`, else
      `http://localhost:<port>`. `listings` reads through
      `SyncApiCreditListingClient.list_listings` over an unsigned client, given the
      configured public principal, since the route is public and reading it should not
      need the signing credential. A refusal exits 1 with the storefront's reason, and
      no answer exits 1 naming the URL and the transport error's type.
- [x] 6.4 Tests: unit `tests/unit/test_listing_publication_client.py` (parity of the new
      method) and `tests/unit/test_listing_publication_entry_points.py` (inverted: the CLI
      uses the typed client); unit `tests/unit/test_startup_seed_quota.py` moved onto the
      step — waits on an unreachable credits service and on an unprobed chain, gives up on
      configuration, finishes once found; application integration
      `tests/integration/test_publish_reconcile.py` through `ApiCreditListingClient` — a
      create against an unprobed chain answers 503 naming Alkahest, a configuration refusal
      400, and a stepped probe then lets the same create succeed; `tests/unit/test_server_composition.py`
      lists `listing-seed` (D19).
      Done.
      - Unit, `tests/unit/test_listing_publication_client.py`: the sync and async
        clients' public methods match, and both list through the transport's listing
        method.
      - Unit, `tests/unit/test_listing_publication_entry_points.py`, with the storefront
        client replaced at `cli._open_storefront`, and constructing the services or the
        storefront's `SQLiteClient` failing the test:
        - `publish` opens the client with the storefront's signer and sends the create
          the listing client builds, as the seller; the signed transport itself is the
          fake's, so its signing is not exercised here;
        - `listings` opens an unsigned client and reads through the listing client;
        - no answer and a refusal each exit 1 with their message.
      - Unit, `tests/unit/test_startup_seed_quota.py` (rewritten in place; its name is
        kept because this step cannot rename a file):
        - the registration request through the typed client over a stub transport,
          given its site and signer; a ledger refusal and an unanswering ledger each
          raising the client's error, the second with no status;
        - each cycle run through the storefront's loop controller: waiting on no
          response or a 5xx to the registration, then finishing; waiting on an
          unanswered availability read without registering again, then finishing;
          waiting on an unknown mechanism, then finishing, every create asking to
          wait for every mechanism; none of these logging at ERROR;
        - giving up on a configuration refusal and on a ledger refusal: the cycle
          fails with `ListingSeedGivenUp`, one ERROR record, and a later cycle does
          nothing;
        - finishing on a listing already there, registering nothing.
      - **Differed:** the 503 case is application integration in
        `tests/integration/test_alkahest_release_conditions.py` rather than
        `test_publish_reconcile.py`, because that file has the real app and composition.
        Through `ApiCreditListingClient`:
        - a supplied-escrow create and a clause create, naming Alkahest by ID or by
          configuration key, against an unprobed chain are each refused 503 naming
          `alkahest.v1 (chain anvil)`; after an `alkahest-chain-probe` run-cycle
          through the administrator's typed client the supplied-escrow create
          succeeds;
        - a clause create while Alkahest is unready for its configuration answers 400
          naming the blocker, as the supplied-escrow unsettleable cases do, and so does
          a supplied-escrow create unready for its configuration before any probe
          (the test asserts the 400 and the configuration blocker, not the
          reachability blocker beside it);
        - the seed, stepped as `listing-seed` through the administrator's typed client
          in the started storefront, with its quota registration replaced on the
          storefront's seed: it waits naming `alkahest.v1` while the chain is
          unprobed, and after a probe run-cycle publishes its listing on `anvil`,
          registering once. This stands for the spec scenario "A storefront starts
          with its chain down" with a chain not yet probed rather than one a probe
          failed to reach, which reads the same way at readiness; "… with its
          dependencies up" is the same step after a probe, not tested separately.
          Alkahest is the seed's only mechanism here, so this does not show the seed
          waiting where another mechanism would publish; the unit test of the rule
          and the seed's own unit tests (the flag reaches the create) cover that
          between them, not against the real listing service.
        - The composition-level clause case asserts no artifacts and the
          configuration blocker.
      - Unit, `tests/unit/test_unreached_mechanisms.py`: which mechanisms are unknown,
        with every and with any: a mechanism with only reachability blockers, one
        with both kinds, an unknown one beside a misconfigured one (no refusal as
        retryable; the seed waits), and ready or disabled ones.
      - `tests/unit/test_server_composition.py` lists `listing_seed` among every loop.
- [x] 6.5 Versions: `arkhai-apicredits-storefront`; `make lock`.
      0.13.0; `make lock` refreshed every lock.
- [x] 6.6 **Verify.** `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: `e2e_credits_deal` runs on the seeded listing, so its passing proves
      the step publishes once dependencies answer (`e2e_credits_payment_deal` skips
      without a payments target, and the seed offers only Alkahest; corrected in round
      1's triage, 85 F2).
      Results:
      - `make test-apicredits` all passed (storefront 215, after both reviews' fixes).
      - `make check-packaging` passed.
      - `make check-change`: fails only on the two citations Sections 13 and 22 create.
      - `make test`: **not run.** Only the API-credit project changed, and no other
        project's pyproject or lock depends on it, so no other suite could see the
        change. The VM and bare-metal storefronts gained comment changes only (below).
      - End-to-end, unrun. `e2e_credits_deal` and `e2e_credits_payment_deal` are the
        scenarios that would show the step publishing once dependencies answer, but
        each discovers once, right after the stack is healthy, so it passes only if the
        seed has published by then: the probe's first cycle, then a seed cycle at most
        2 s later. The pipeline run is the evidence, and it may lose that race (handoff
        below).

Section 6 notes (handoff):

- **Residual race for validation:** before this section the seed published before the
  storefront served; now it publishes up to a couple of seconds after the chain probe's
  first cycle. If the credits lane's discovery runs inside that window it finds nothing.
  The remedy, if the pipeline shows it, is the scenario stepping `listing-seed` (or
  waiting on its state) before discovery, not a longer storefront startup.
- **Startup still preflights the credits service** (`_preflight_credits_service`), which
  Section 11 removes.
- **For closeout:** `TESTING.md`'s API-credit loop row gains `alkahest-chain-probe`
  (Section 4) and `listing-seed`, as the design's promotion list says.
- **Comments from Section 5 corrected here:** the storefronts' Alkahest stage
  comments (`settlement_stages.py`) still said composition refuses an undeliverable
  release model; bare metal's and API credits' now say it makes Alkahest unready.
  VM's same correction is committed with Section 7, which changes that file and was
  already in the worktree when this section was committed, since this step cannot
  stage part of a file. Comment-only, so no suite was rerun for bare metal. The seed's
  configuration and compose comments (`storefront.credits.toml`,
  `domains/apicredits/compose.yml`) no longer say it seeds at startup.
- **From the fresh-context review, fixed:** the seed published without an unknown
  mechanism's option whenever another mechanism was ready (now
  `wait_for_every_mechanism`); a given-up seed recorded a completed cycle; raw error
  text in the report; the registration re-sent every cycle while waiting; `listings`
  bypassing the typed client; `ListingSeed` and `register_seed_quota` reading their
  listing service, signer, site, and database from the container (the server now
  builds the seed from its own services, and the seed module reads no container); a
  private `_capacity_settings` import (now `configured_sites`); the seed interval's
  dead fallback; import order; the notes above. **Declined:** the CLI tests still
  replace `cli._open_storefront`, a module function, since a Typer command has no
  constructor to inject through; `listing_service.py` keeps its direct
  `ALKAHEST_MECHANISM_ID` import (it already treats supplied escrows as the Alkahest
  form) and the `"reachability"` literal, which `ReadinessBlockerKind` types; the
  test file's name (it cannot be renamed here).
- **From the second fresh-context review, fixed:** a clause naming Alkahest by its
  configuration key was refused 400 rather than 503 (mechanisms are now
  canonicalized); the 503 named no chain, against the delta scenario "names
  Alkahest's unreached chain" (it now names the chains); a 503 could precede the
  resource and pool checks, telling the caller to retry a create that would then fail
  (the refusal now follows them and counts only mechanisms the pool's backing
  admits; no test sends an unknown-mechanism create to a missing resource or an
  unbacked pool); the waiting rule had no unit test and the seed loop no
  integration test (both above); `list_listings` returned `Any` (now
  `ListingListResponse`).
- **Deliberate, from the third check:** a create that publishes nothing, with one
  mechanism unknown and another unready for its configuration, answers 400, though
  it would publish the first once it is reached: "refused only because a
  mechanism's readiness is unknown" is read as every unready mechanism being
  unknown. The seed waits in that case. The 503 names every chain the request uses
  Alkahest on, since Alkahest's readiness covers its chains together. **Declined:** the listing client still takes a `seller`
  identity its public list does not use, since the one client serves both routes; the
  CLI's `listings` resolves the configured public principal for it. The loop
  controller's ERROR record carries the given-up seed's chained traceback, which can
  name the credits service's URL; it is a log, not status, which is what the
  controller's disclosure rule governs.
- **A given-up seed's failure stays in status only until its next cycle**, 2 s later,
  which completes as a no-op; the controller has no way to stop a timer loop. The
  ERROR record and the step's report (`state: given_up`, the error's type) remain.
  A controller that lets a step end its loop would keep it visible; no task names one.
- **Round 1's triage.** 85 F2: the credits deal's discovery no longer races the seed.
  `test_credits_deal_buyer_cli.py`'s `_seed_published` steps `alkahest-chain-probe`, then
  `listing-seed`, through the storefront's administrator `run-cycle` before discovering,
  as the residual-race note above proposed; the lane's configuration
  (`e2e-tests/config/config-docker.yml`) gains the API-credit storefront's identifier and
  administrator credential, the credential being the development dev-env identity
  already committed for it, and the API-credit conftest a `credits_storefront_admin`
  fixture. 6.6's evidence line now names only `e2e_credits_deal`. 85 F13: the seed's
  lookup of its own listing pages through the storefront's listings (`_LISTING_PAGE`,
  500 at a time) rather than reading one page. Tests: API credits unit
  (`test_startup_seed_quota.py`: the seed resolves its configured site, and finds its
  listing past the first page); integration (`test_alkahest_release_conditions.py`: a
  restarted storefront's seed finds the listing it published and publishes no second);
  end-to-end, `e2e_credits_deal` (unrun here). Evidence: the round's note under
  Section 10.

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
      Done. `verify_escrow_against_plan(escrow_uid, settlement_plan, alkahest_client,
      chain_name, escrow_address, alkahest_address_config_path)` matches the escrow to
      one of the plan's Alkahest obligations on that chain and escrow contract
      (`settlement_obligation_to_escrow_terms` per obligation, so its index is the
      plan's), obligation data and expiry exactly, and returns that index. It and
      `verify_escrow_for_settlement` share `_escrow_codec` and `_match_on_chain` (the
      chain read, the envelope checks, the comparison, the diff). The address book is
      read only for the escrow contract's codec. The registration's
      `settlement_verifier` is the plan form; the package exports both. Unit tests
      (`make -C kit test-alkahest` 360): an escrow funding the committed plan verifies;
      after the listing's condition pays another wallet, and separately after the
      address book moves the arbiter, the plan still verifies while the listing form
      refuses the same escrow, naming `release_condition_not_authorized` and the
      arbiter respectively; an escrow differing in amount, recipient, or expiry does
      not verify and the error names the field; a plan with no obligation on the
      escrow's contract refuses. **Correction:** no test changes the release model
      itself (recipient to oracle-gated, say); the plan form reads no listing, so the
      wallet and arbiter cases stand for any listing change.
- [x] 7.2 VM `settlement_composition.py` `prepare_vm_settlement` verifies and builds its
      obligations from `thread["settlement_plan"]`, as `failure_actions.py`'s refund does;
      `settlement_stages.py` `AlkahestStage.recover_evidence` re-derives from the plan, not
      the evidence's stored `order` (D16).
      Done. A thread with no committed plan refuses settlement; `_settlement_plan_obligations`,
      which rebuilt the plan from the listing, is gone. The listing is still loaded for
      the deal's delivery facts and fulfillment input, which this section does not
      change. `accepted_alkahest_proposal(thread, mechanism=)` is now a module function
      in `settlement_stages.py`, so the dry-run reads the accepted proposal exactly as
      settlement does; the stage's `accepted_proposal` calls it. VM's
      `settlement_stages.py` also carries Section 6's release-model comment correction
      (see Section 6's notes).
- [x] 7.3 VM heartbeat and interrupt: `controllers/deals_controller.py` reads the cadence
      from the committed plan's `service_terms.heartbeat.interval_seconds`, and a plan with
      no heartbeat term (a deal that is not oracle-gated) reports no expected heartbeat;
      `controllers/admin_controller.py` `_deal_is_interruptible` reads the plan's
      `interruptible` term, never the current listing or chain address configuration (the
      listing is still loaded for its capacity binding) (D16).
      Done. The heartbeat answers `next_expected_by_unix: null` for a plan with no
      positive heartbeat interval. The `heartbeat_interval_seconds` setting is still
      read at acceptance, where the plan's term is written.
- [x] 7.4 Bare metal `settlement_stages.py` `verify_alkahest` and `revalidate_alkahest`
      verify against the committed plan. Acceptance builds its plan from the listing record
      the opening authorized: today every round reloads the listing and `build_artifacts`
      re-authorizes against the reloaded record, and no snapshot of the opening's record is
      kept, so `negotiation_runtime.py`'s `persist_opening` persists the authorized record
      with the opening and acceptance (`build_artifacts`, force-accept included) builds from
      it (D16).
      Done. Both call the runtime's `escrow_verifier` (the registration's plan form) with
      the thread's committed plan and the accepted proposal's chain and contract; both
      still call `physical_terms`, which checks the machine the deal delivers against
      its listing, and no longer pass the listing to verification.
      - `persist_opening` saves the opening's `listing_record` in a new table,
        `bare_metal_opening_listings` (migration `bare-metal-storefront-0015-opening-listings`,
        one row per negotiation, written once; `save_`/`load_bare_metal_opening_listing`).
      - **Differed:** acceptance reads it through `resolve_continuation`, which returns
        the opening's record with the current record's `status`, since
        `build_artifacts` is synchronous and takes the record the runtime resolved, and
        force-accept resolves the same way. So every continuation round, not only
        acceptance, reads the opening's record: the seller's reference amount and the
        Agreement's listing hash come from it as well, consistent with the escrow the
        opening pinned under it. The record carries the current `status`, and the
        listing-source check still reads the current source. **Correction:** the
        runtime checks that a listing is live and unpaused only at the opening, never on
        continuation, so carrying the current status preserves no check, and no test
        closes or pauses a listing mid-negotiation. A thread with no recorded opening
        record continues against the current record. Recorded in `design.md` decision
        16, and named among the `storefront-publication` companion's promotions there.
- [x] 7.5 VM administrator dry-run verify: `VerifyEscrowRequest`
      (`core/storefront/.../models/settle_models.py`) gains `negotiation_id`, as
      `EvaluateSettleRequest` has, since the escrow row exists only at settle;
      `services/admin_settle_service.py` loads that accepted deal's committed plan and
      verifies against it with the 7.1 form; `storefront_client`'s async and sync
      `verify_settle` send it; bare metal's twin (`deal_controls.py`
      `settlement_admin_routes.verify`, `BareMetalVerifyEscrowRequest`) does the same; e2e
      Stage07b (`helpers/compute_deal_stages.py`, `vms/test_full_deal_buyer_cli.py`) names
      the negotiation (D16).
      Done. **Differed:** the request is `negotiation_id` alone. Its former fields
      (`seller_wallet`, `agreed_price`, `agreed_duration_seconds`, `listing_id`,
      `chain_name`) are removed rather than kept beside it, since the plan determines
      every one and a field the dry-run ignored could disagree with what settlement
      verifies; the chain and escrow contract come from the accepted proposal, as at
      settle. `verify_settle(escrow_uid, *, negotiation_id)` on both clients. A
      negotiation not accepted answers 404; a deal not settled by Alkahest, or on a
      chain the storefront does not configure, is `valid: false` with the reason. VM's
      unused `Uint256Amount` import in `settle_models.py` went with the fields.
- [x] 7.6 API credits `settlement_stages.py` `_prepare_alkahest_settlement` verifies and
      builds against the committed plan rather than `order` (D16).
      Done. A thread with no recorded escrow proposal now refuses settlement (it was
      verified through the listing form's legacy path), and the chain and escrow
      address come from the proposal, the fallback to the listing's first accepted
      escrow going with it. The obligations' principals are checked before the chain
      read.
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
      Done.
      - VM unit:
        - `test_settlement_composition.py`: `prepare_vm_settlement` verifies the
          committed plan (the verifier, replaced, receives it and the accepted contract)
          and registers its obligations, and a plan builder that fails if called is never
          called, so nothing is rebuilt from the listing;
        - `services/test_admin_settle_service.py`: the dry-run refuses an unaccepted
          negotiation, passes the committed plan, chain, contract, and address book to the
          verifier, maps its refusal to `valid: false`, and refuses a deal not settled by
          Alkahest;
        - `test_interrupt_deal_admin.py`: a deal whose plan carries the interruptible
          term is interrupted though its listing is not marked interruptible, and one
          whose plan lacks it, or that has no plan, is refused though the listing is.
        - `test_heartbeat_gated_listings.py` needed no change: it covers the plan's
          heartbeat and interruptible terms at acceptance, which this section reads.
      - VM application integration:
        - `test_settle_controller.py`, through `StorefrontClient`, with the Alkahest
          client, the chain boundary, replaced by one answering as the SDK decodes an
          ERC-20 escrow, and a plan materialized from a real proposal against the
          development address book: after the listing is rewritten to pay another wallet,
          an escrow funding the committed plan is valid and an underfunded one is not,
          naming the amount; an unknown negotiation is 404; a chain the storefront
          configures but holds no Alkahest client for is `valid: false`; nothing is
          written.
        - This shows the dry-run verifying the plan; that it and settlement agree rests
          on both calling `verify_escrow_against_plan` with the same accepted proposal
          and plan, which the unit tests above show, not on one test running both.
        - **Not delivered:** the planned application-integration case of a deal
          settling after its listing changed. VM has no integration test of settle
          through the typed client at all, and building one is beyond this section;
          settle after a listing change is shown only by the unit test above, in which
          the plan builder fails if called.
        - `test_deals_controller.py`: the cadence is the committed plan's (45 s, not the
          setting), and a plan with no heartbeat term expects none. This file drives the
          route with raw signed requests, as it already did; the heartbeat route has no
          typed client method.
      - Bare metal application integration:
        - `test_http_negotiation.py`: the listing is rewritten in place between a
          countered opening and its acceptance, by the buyer and by force-accept; the
          plan builder receives the record the opening authorized, still open.
        - `test_http_settlement.py`: every verification call, at settle and at status and
          fulfillment recovery, receives the thread's committed plan; the settle call's
          contract is asserted, and recovery's only on its last call, and no test asserts
          the listing is absent from the call, though the plan form takes none;
          `test_verify_registers_exactly_the_committed_plan` (unchanged) shows settle
          registering that plan.
        - `test_deal_controls.py`: the dry-run, through `StorefrontClient`, verifies the
          committed plan on the proposal's chain and contract, refuses an unknown
          negotiation 404, and writes nothing; a deal accepted on a chain with no
          Alkahest client is `valid: false` naming the chain, without a chain read.
      - API credits unit, `test_settlement_fulfillment.py`: settlement verifies the
        committed plan; after the listing's release condition and the seller wallet
        change, a deal still settles, the verifier receiving the committed plan and the
        runtime registering its obligations.
- [x] 7.8 Versions: `arkhai-kit-alkahest`, `arkhai-core-storefront`,
      `arkhai-core-storefront-client` (and the exact pin in `provisioning/compute/service`),
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
      Bumped: VM storefront 0.20.0 (its exact pin on bare metal moved), bare-metal
      storefront 0.20.0, API-credit storefront 0.14.0, `arkhai-e2e-tests` 0.3.0, whose
      floor on `arkhai-core-storefront-client` rises to 0.27.0 for the new
      `verify_settle`; `make lock`. **Not bumped:** `arkhai-kit-alkahest` (0.10.0),
      `arkhai-core-storefront` (0.16.0), and `arkhai-core-storefront-client` (0.27.0)
      were each bumped earlier on this branch and are unreleased, so the provisioning
      service's exact pin is unchanged; the same policy as 5.5, for the round's triage
      to settle.
- [x] 7.9 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make
      test-storefront`, `make test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`;
      `make test`; `make check-packaging`. End-to-end: `e2e_deal` and
      `e2e_deal_buyer_cli` (Stage07b's dry-run and settle), `e2e_non_erc20_settlement`,
      `e2e_bare_metal_mock_deal`, and `e2e_credits_deal` settle against the plan.
      Results:
      - `make -C kit test-alkahest` 360 passed.
      - `make test-core` passed (its four projects 123, 134, 217 with 2 skipped, 62).
      - `make test-storefront`: unit 1107 passed; integration 449 passed with the same
        two environmental `test_alkahest.py` failures (no Node.js or Anvil here).
      - `make test-bare-metal` (storefront 445), `make test-apicredits` (storefront 216),
        `make test-e2e-unit` (38): all passed.
      - `make test`: not run whole. Beside the suites above, the changed packages are
        `kit/alkahest`, whose other dependants (the buyers) import nothing this section
        changed, and `core/storefront-client`, whose `verify_settle` only the
        storefronts' tests and the e2e stages call.
      - `make check-packaging` passed; `make check-change` fails only on the two
        citations Sections 13 and 22 create.
      - End-to-end, unrun: `e2e_deal` and `e2e_deal_buyer_cli` run Stage07b's dry-run
        with the new request and settle; `e2e_non_erc20_settlement` and
        `e2e_credits_deal` settle. Each exercises the plan form once deployed; the
        pipeline run is the evidence. **Correction:** `e2e_bare_metal_mock_deal` does
        not settle at this commit. Its buyer opens with the escrow contract unpinned (the
        shared Stage05b with no selection, and Stage12b, pass no escrow address, so the
        client sends the zero address), the committed plan's obligation names the zero
        address as its contract, and the plan form finds no codec for it: Stage07b's
        dry-run answers `valid: false` and settle 400. Section 8, which refuses an
        unpinned opening and pins the lane's openings, is what makes it settle again,
        so this commit alone would fail the bare-metal lane.

Section 7 notes (handoff):

- **The listing form of verification has no production caller now.** Every domain
  settles, recovers, and previews through `verify_escrow_against_plan`. The listing form
  stays because the task keeps it and its tests read the release-authorization rules
  through it; Section 8 removes its default-kind branch, and whether the form stays at
  all is a question for the round's triage.
- **A deal accepted with its escrow contract unpinned cannot be verified now.** The
  listing form resolved such an escrow's codec from the chain's default kind; the plan
  form looks the codec up from the plan's contract, the zero address, and finds none
  (7.9's correction). That is what decision 18 intends for new deals, which Section 8
  refuses at the opening, but neither decision says what becomes of an unpinned deal
  accepted, and perhaps funded, before this release: it can now only wait for reclaim.
  Every bare-metal lane deal opened this way, so the case is real. Left for the round's
  triage: accept it as a disposable-state cutover, or resolve such a deal's codec from
  its plan.
- **The fresh-context review's findings this section declined:** moving
  `accepted_alkahest_proposal` out of `settlement_stages.py` into a leaf module (the
  dry-run service importing the stage module is no boundary breach, and the move is
  churn); and making the opening record's write atomic with the opening's other writes
  (a lost write falls back to the current record, as a thread opened before the
  migration does, and `persist_opening` writes through the same repository).
- **Bare metal's continuation reads the opening's record** (7.4's differed note). If the
  round's review prefers acceptance alone to read it, the runtime's `Acceptance` would
  need a domain-supplied record, a `kit/negotiation-runtime` change no task names.
- **A new bare-metal migration**, `bare-metal-storefront-0015-opening-listings`, adds a
  table and changes nothing else, so rolling back leaves it unread.
- **The dry-run request lost fields**: an older caller of `verify_settle` sending the
  terms is refused 422. The only callers are the storefronts' tests and the e2e
  Stage07b, all updated.
- **Round 1's triage.** 85 F5: the two handoff questions above are settled in
  `design.md` decisions 16 and 18. Verification keeps finding the escrow's codec through
  the current address book, and the `settlement-servicing` delta now guarantees only
  what that allows (a policy, wallet, or release-condition address-book change after
  acceptance changes nothing; an address book that stops naming the funded contract
  leaves the deal unverifiable, its escrow reclaimable), with a scenario moving the
  arbiter after acceptance; an unpinned deal accepted before this release is a cutover,
  bare metal never having been released; the module docstring states the address-book
  limit. 85 F14 settled the first note: the listing form of verification
  (`verify_escrow_for_settlement`, its token extraction, and its legacy recipient
  helper) is removed with its tests, its release-authorization cases carried by
  `authorize_escrow_proposal`'s, and VM's `utils/escrow_verification.py` re-exports only
  the plan form. Tests: kit unit
  (`test_native_escrow_verification.py`: an arbiter moved after acceptance still
  verifies against the plan); VM unit (`test_escrow_verification.py`, now over the plan
  form). Evidence: the round's note under Section 10.

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
      Done. An escrow proposal is one stating a `chain_name` or an `escrow_address`
      (`is_escrow_proposal`), whether or not it also carries a selection; one naming no
      contract (`escrow_contract_unpinned`: missing, empty, or all-zero digits) is refused
      as `escrow_contract_unpinned`, before and whatever the listing accepts. A round
      carrying none (no proposal, fields only, selection only) passes. The module's
      `_ZERO_ADDRESS` went, with VM's `arkhai_vms_negotiation.policies` re-export of it.
      **Also changed:** an escrow proposal against a listing accepting no escrow is refused
      as `escrow_not_in_accepted_set` rather than passed, since the seller prices it from no
      entry (8.3; recorded in design D18). **Added:** `pinned_proposal(history)`, the
      buyer's opening, which VM and API credits now price from in every round (8.3), as
      `negotiation-protocol` requires and as acceptance settles; `buyer_counter_guard`
      reads from it whether the round bargains an amount. Unit (`make -C kit test-policy`
      92): the four unpinned shapes (zero, empty, no address, zero beside a selection) are
      refused against a listing accepting the escrow and one accepting none; an escrow
      against a listing accepting none (absent, empty, empty JSON text) is refused;
      selection-only and fields-only rounds pass; `pinned_proposal` is the opening whatever
      a later counter or the seller's own round names, and None for an opening carrying
      none; a counter selecting an unpriced option after a bargained opening is still
      scalar and refused as `counter_missing_amount` (`test_selection_scalar.py`).
- [x] 8.2 `kit/alkahest`: `proposals.py` `authorize_escrow_proposal` and `alkahest.py`
      `materialize_escrow_terms_from_proposal` refuse an unpinned proposal through the
      existing `ReleaseConditionError` family, which every caller already translates, with
      its own code; `escrow_verification.py`'s default-kind branch goes. Tests in
      `test_release_authorization.py` and `test_native_escrow_verification.py` (unit) (D18).
      Done. `release_authorization.py` gains `UnpinnedEscrowError(ReleaseConditionError)`
      (message `escrow_contract_unpinned: …`) and `require_pinned_escrow`, which both entry
      points call first; `proposals` exports the error. The listing form of verification
      refuses an unpinned proposal as `EscrowVerificationError` before any chain read, and
      reads every proposal's escrow through its own contract's codec; `escrow_kind` remains
      only for a legacy thread with no proposal. Unit (`make -C kit test-alkahest` 396), all
      in `test_release_authorization.py`: four unpinned shapes refused by
      `authorize_escrow_proposal` whatever condition they select, including the listing's
      own; by each of the five materializers called directly; and by the listing form's
      verification without reading the chain. Four `test_escrow_kind_codec.py` cases that
      materialized at the zero address now use a development address the book does not
      name, which keeps what they tested (no codec decides the amount).
      `test_native_escrow_verification.py` needed no change.
- [x] 8.3 First-entry pricing goes: VM `storefront_round.py` (`_selected_option`,
      `_seller_reference_amount`) and `domains/vms/listings/.../pricing.py`; API credits
      `pricing.py`'s first-escrow and first-option fallbacks; bare metal
      `negotiation_runtime.py` `_priced_acceptance`'s chain-blind fallback (D18).
      Done, in three shapes, because the domains run their guards at different points:
      - **VM and API credits** price from the buyer's pinned opening (8.1's helper), never
        from another entry's rate or the floor. An escrow proposal selecting nothing the
        listing offers has reference amount zero: their pricing runs before the policy
        chain, and every default chain of theirs composes the escrow-shape guard, which
        then refuses it at the opening by its own reason (`escrow_contract_unpinned`,
        `escrow_not_in_accepted_set`, the latter now including a listing accepting none);
        a raised pricing error would have pre-empted it. A selection matching no option is
        priced at zero in VM, whose opening guard refuses it, and refused by API credits'
        extractor as before. Every round prices the pinned opening, which round zero
        checked, and reads from it whether the round bargains an amount, so a counter
        naming another option or escrow changes neither, and acceptance settles the same
        opening. A zero reference is safe only if a guard refuses before any decider, so
        both domains now put their default guards first in their fixed order wherever an
        operator's chain names one; before, a named guard kept the operator's position,
        and VM's shipped `settings.toml` chain put `accept_unpriced_selection` ahead of
        the shape guard. `extract_initial_price_from_order` takes
        `selected_option` as a required argument and refuses None;
        `extract_unit_price_from_order` refuses a proposal selecting nothing; neither falls
        back to the floor for one, which applies only to a selected option advertising no
        rate. Its unused `_accepted_escrows` reader went.
      - **Bare metal**'s guard is a configurable default, so its opening refuses before
        any policy: `_priced_acceptance` raises `escrow_contract_unpinned` (through the
        kit's `require_pinned_escrow`) or `escrow_not_in_accepted_set`, 409.
        `_matching_acceptance` serves the continuation's reference amount, read on every
        resumed round including exit, where an unmatched escrow prices from nothing
        rather than refusing, so a buyer can always leave.
      - Unit: VM `test_extract_initial_price.py` and API credits `test_concept_modules.py`
        name the escrow each case selects, and a parametrized case shows no proposal, an
        unpinned one, an unlisted one, and (VM) another chain's are priced at zero with a
        floor configured, and refused by the extractors themselves; a listing accepting no
        escrow prices a pinned escrow at zero; a selection matching no option is priced at
        zero in VM and refused by API credits' pricing. VM's `TestRoundReference` runs
        hand-built rounds through `_run_default_seller_round_policy` and its default chain:
        on a two-escrow listing, a counter naming the second, amountless escrow, with an
        amount or without, keeps the opening's reference and scalar bargaining and is not
        accepted; an opening naming an escrow the listing does not accept is priced at zero
        and refused as `escrow_not_in_accepted_set`. No test runs those rounds through
        `NegotiationRuntime` or the typed client, and no API-credit test runs a round
        through its hook and chain; the guard-order change has no test of its own beyond
        the suites still passing.
      - **Also changed:** both compute storefronts' negotiation-strategy status probes
        (`system_service.py`, bare metal `negotiation.py`) used the zero address to slip
        past the guard with no listing; they now open with a placeholder contract and
        condition on a synthetic listing that accepts and advertises them, since the
        guard refuses both an unpinned escrow and one a listing does not accept.
- [x] 8.4 `core/storefront-client/src/storefront_client/client.py` `_negotiate_new_proposal`
      no longer fills a zero escrow address or token for an escrow opening, which would
      build exactly the refused shape: an escrow opening requires its escrow address, and a
      caller with no escrow uses the selection-only opening. Tests in
      `core/storefront-client/tests/test_negotiate_new_payload.py` (unit) (D18).
      Done: an escrow opening with no `escrow_address` raises `ValueError` before any
      request, and the token appears only when given; the chain and expiry defaults stay.
      Both clients' `negotiate_new` docstrings say so, and the module's usage example names
      an address. Unit (`make -C core/storefront-client test` 65): an empty or omitted
      address is refused before HTTP; an opening given no token names none; the legacy-envelope refusal now matches
      the envelope's own message, so it cannot pass on the address refusal instead.
      An explicit zero address still reaches the server, which is how 8.6 tests the
      server's refusal through the typed client.
- [x] 8.5 Callers that opened unpinned move to a pinned or selection-only opening: VM
      `tests/unit/test_escrow_fields_policy.py`, `unit/test_escrow_verification.py`,
      `integration/test_negotiate_controller.py`, `integration/test_listings_api.py`; bare
      metal `tests/test_http_negotiation.py` (its `_UNPINNED` cases become refusals); e2e
      `helpers/compute_deal_stages.py` (the opening and the evaluate-negotiate dry-run),
      `vms/test_full_deal_buyer_cli.py`, `vms/test_multi_registry.py`,
      `vms/test_non_erc20_settlement.py`, `bare_metal/test_bare_metal_mock_deal.py` (D18).
      Done.
      - **A second carve-out surfaced.** With its escrow pinned, the guard also requires
        the proposal to select one of the listing's advertised conditions
        (`selected_demand_not_allowed` otherwise); the unpinned openings had skipped that
        check too. So every pinned opening names the listing's condition as well as its
        contract and literal fields, as a buyer deriving its proposal from the option
        does (`escrow_proposal_from_accepted_entry`).
      - VM: `test_escrow_fields_policy.py` (the zero-address pass becomes a refusal);
        `test_escrow_verification.py` (the default-kind fallback becomes a refusal before
        any read); `test_order_pause_state.py`, not in the plan: the retryable-source test
        opened unpinned, so the fixture listing gains a condition and the test names it;
        `test_negotiate_controller.py`'s openings take `_PINNED` (the seeded listing's
        escrow, token, and condition), so each refusal under test is its own;
        `test_listings_api.py`'s dry-runs name the seeded listing's escrow and no
        condition, which they need not, because those tests patch the chain to bisection
        alone and no guard runs.
      - Bare metal `test_http_negotiation.py`: the two unpinned pricing tests became 8.6's
        refusal; the plan-materialization test of an opening naming no condition now runs
        without the guard, which is the only way such an opening reaches materialization;
        the unreadable-condition test selects the listing's (unreadable) condition.
      - e2e: `compute_deal_stages.py` gains `alkahest_opening(listing)`, the listing's
        Alkahest option and the escrow an opening names (contract, literal fields, the
        listing's condition on its chain), read from the registry's copy; Stage05a's
        dry-run and Stage05b's opening use it, as do bare metal's Stage12b,
        `test_full_deal_buyer_cli.py`'s Stage05a dry-run, and `test_multi_registry.py`'s
        two openings (through registry A). `test_non_erc20_settlement.py` already
        opened pinned with its condition and needed no change.
- [x] 8.6 Application integration through `StorefrontClient`: in VM's
      `tests/integration/test_negotiate_controller.py` and bare metal's
      `tests/test_http_negotiation.py`, an unpinned escrow opening is refused naming the
      reason, with the seller's guard composed and with it omitted (the kit chokepoint
      refuses it) (D18).
      Done.
      - Bare metal: an opening at the zero address at the listed rate, under the default
        chain and under `["listed_price"]` alone: the dry-run reports it refused naming
        `escrow_contract_unpinned`, the opening is 409 naming it, no thread is listed,
        and nothing is accepted. By the code, the refusal under either chain is the
        opening's pricing, through the kit's check, before any policy, so bare metal's
        shape guard never sees an opening's escrow; the test asserts the refusal and its
        reason, not which of the two checks produced it.
      - The kit chokepoint itself (`authorize_escrow_proposal` and the materializers) is
        evidenced by 8.2's unit tests only; neither domain's application test reaches it
        with an unpinned proposal, since each refuses earlier.
      - VM: an opening at the zero address under the default chain, and under a seller
        hook that accepts as proposed, is 409 naming `escrow_contract_unpinned`, with no
        Agreement or plan recorded.
      - **Differed:** VM's Alkahest entry funds the escrow its selected option names, so
        the buyer's carrier beside the selection was never materialized, and without the
        guard the zero-address opening was accepted against the option's real contract.
        `VmAlkahestSellerStage.accepted_artifacts` now runs the kit's
        `require_pinned_escrow` over an escrow carrier the buyer sends, so the acceptance
        is refused as materializing it would be. The carrier is still not compared with
        the option's entry; a pinned carrier naming another contract is accepted against
        the option's, as before.
- [x] 8.7 Versions: `arkhai-kit-policy` (and the exact pin in `kit/negotiation-runtime`),
      `arkhai-kit-alkahest`, `arkhai-core-storefront-client`, `arkhai-vms-listings`,
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
      Bumped: `arkhai-kit-policy` 0.6.0; `arkhai-kit-negotiation-runtime` 0.5.2, whose
      exact pin on policy moved and whose exact pins in the three storefronts moved with
      it; `arkhai-vms-listings` 0.7.0 (`extract_initial_price_from_order`'s argument is
      required); `arkhai-vms-negotiation` 0.5.0 and `arkhai-apicredits-domain` 0.7.0, not
      in the plan but both changed, with policy floors at 0.6.0; VM storefront 0.21.0 (its
      exact pin on bare metal moved), bare-metal storefront 0.21.0, API-credit storefront
      0.15.0, with floors on the packages above; `arkhai-e2e-tests` 0.3.1; `make lock`.
      **Not bumped:** `arkhai-kit-alkahest` and `arkhai-core-storefront-client`, already
      bumped and unreleased on this branch (7.8's policy); `arkhai-kit-storefront`, whose
      wheel is unchanged (only its test layout and `testpaths` moved).
- [x] 8.8 **Verify.** `make -C kit test-policy test-alkahest test-negotiation-runtime`;
      `make test-core`; `make test-vms-domain`, `make test-storefront`, `make
      test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`; `make test`; `make
      check-packaging`. End-to-end: `e2e_deal`, `multi_registry`,
      `e2e_non_erc20_settlement`, and `e2e_bare_metal_mock_deal` open
      pinned and negotiate as before.
      Results, on the branch merged with dev's Helm render repair:
      - `make -C kit test-policy test-alkahest test-negotiation-runtime`: 89, 396, 61
        passed; `make -C kit/storefront test` 127 passed, the moved SDK test among them.
      - `make test-core` passed (123, 134, 217 with 2 skipped, 65).
      - `make test-vms-domain` 53 and `make test-vms-buyer` 202 passed.
      - `make test-storefront`: unit 1113 passed; integration 450 passed with the two
        environmental `test_alkahest.py` failures (no Node.js or Anvil here).
      - `make test-bare-metal` (storefront 448) and `make test-apicredits` (storefront
        219) passed; `make test-e2e-unit` 38 passed, which parses `compute_deal_stages.py`.
      - After the fresh-context checks' fixes (`make dist` first): `make -C kit test-policy
        test-negotiation-runtime` 92, 61, and `test-alkahest` 396; `make test-core` (123,
        134, 217 with 2 skipped, 65); `make test-vms-domain` 53; `make test-vms-buyer` 202;
        `make test-storefront` unit 1119 (1 skipped), integration 450 with the same two
        environmental failures; `make test-bare-metal` storefront 446 (the
        unpinned-opening test lost its amount parameter); `make test-apicredits` storefront
        221; `make check-packaging` passed; `make check-change` fails only on the same two
        citations. `make test-e2e-unit` was not rerun: no e2e file changed after its run.
      - **Also changed by the fixes:** both compute storefronts' negotiation-strategy status
        probes now run against a synthetic listing accepting their placeholder escrow and
        advertising its condition, since the guard refuses an escrow against a listing
        accepting none; `docs/configuration.md`'s `escrow_shape_guard` and `bisection` rows
        describe the refusals and the selected option's floor.
      - `make test`: not run whole, as in Section 7; the suites above cover every project
        whose code or locks changed.
      - The changed e2e scenario modules were not byte-compiled: `python3 -m py_compile`
        was refused here, and no lane runs locally.
      - `make check-packaging` passed; `make check-change` fails only on the two citations
        Sections 13 and 22 create.
      - End-to-end, unrun: `e2e_deal` (Stage05a, Stage05b), `e2e_deal_buyer_cli` (its
        Stage05a), `multi_registry` (06a, 06b), and `e2e_bare_metal_mock_deal` (the
        shared Stage05a and Stage05b, and Stage12b) now open pinned with the listing's
        condition; `e2e_non_erc20_settlement` is unchanged. Bare metal's lane also needs
        this section to settle at all (Section 7's correction to 7.9). The pipeline run is
        the evidence.

Section 8 notes (handoff):

- **Decision 18's premise was wrong.** It says no buyer in this repository sends an
  unpinned proposal; the client filled the zero address for any caller naming none, and
  every bare-metal lane deal, the shared stages, and the multi-registry openings sent one.
  The outcome the decision chose (refuse) is unaffected; the round's triage may want the
  rationale corrected.
- **The zero address was a second carve-out.** Pinned, an escrow proposal must also
  select one of the listing's advertised conditions, which the unpinned openings had
  skipped; every opening this section pinned names the listing's condition.
- **Pricing differs by domain on purpose** (8.3): VM and API credits price an unselected
  escrow proposal at zero and let their always-composed guard refuse it; bare metal, whose
  guard a seller may omit, refuses it before policy. The design records it under D18.
- **What the fresh-context checks caught in pricing.** The first draft priced at zero on a
  listing accepting no escrow, where the guard then passed the proposal, so a negotiation
  ran against a zero reference; a second draft priced it from the floor, which the
  permanent spec forbids (the floor applies only to a selected option without a rate).
  The resolution is the guard refusing an escrow against a listing accepting none. The
  checks also caught that pricing from the buyer's latest selecting proposal let a
  counter change the option priced while acceptance settled the opening, which
  `negotiation-protocol` already forbids ("the buyer's pinned proposal"); every round
  now prices the pinned opening. Before this section VM and API credits priced the
  latest buyer proposal, with the same exposure. A third check caught the scalar
  switch still following the latest proposal and operator-named guards running after a
  decider; both are fixed (8.3).
- **Not rechecked:** the third check's fixes (default guards first in fixed order, and
  `buyer_counter_guard` reading scalar bargaining from the opening) had no fourth
  fresh-context check; the round's implementation review is the next reader.
- **Declined from the third check:** removing VM's two guard tests in
  `test_escrow_fields_policy.py` as duplicates of the kit's, since each replaced an
  existing VM test that asserted the old pass and the file is VM's check of the guard it
  re-exports; sharing the two storefronts' probe constants, which would need a kit for
  six lines; a typed-client application test of the pinned reference, left to the
  round's review.
- **Declined from the fresh-context check:** the unpinned-escrow predicate exists twice,
  `kit/policy`'s `escrow_contract_unpinned` and `kit/alkahest`'s `require_pinned_escrow`,
  because the scope rule forbids the mechanism-neutral policy kit from importing the
  Alkahest kit and the guard must not depend on it; and the design-promotion record is
  completed for the whole change at closeout, as the plan's closeout task says.
- **VM checks the buyer's carrier beside a selection only for a contract** (8.6's
  differed note): a carrier naming a contract other than the option's is still accepted
  against the option's.
- **Accepted unpinned deals** remain Section 7's open question for triage: they can no
  longer verify, and this section removes the last path that accepted them.
- **`kit/storefront` now has `tests/integration/`**, holding Section 4's SDK
  construction test, moved with `git mv` under a permanent name.
- **Round 1's triage.** 85 F1: `accept_unpriced_selection` judges and accepts the pinned
  opening, and `accept_exact_listing`'s selection branch settles the opening's option
  at the latest proposal's amount, so a counter selecting an unpriced option after a
  priced opening is no longer accepted at its own amount. 85 F6: `kit/alkahest`'s
  `authorize_escrow_proposal`, which the acceptance's plan materialization runs, holds an
  escrow proposal to the listing's accepted entry, `escrow_not_in_accepted_set` or
  `escrow_field_mismatch` (`require_accepted_escrow`), whatever policies ran; bare metal
  runs `escrow_shape_guard` beside `has_matching_inventory_guard` as a required guard
  ahead of its configured policies, and its default policies are `("listed_price",)`. A
  plan materialized without a seller plan's input (`derive_accepted_escrow_terms` given
  none) refuses `seller_plan_missing` (85 F12, Section 9). 85 F17: VM's round hook refuses
  a continuation whose opening's option the listing no longer offers,
  `pinned_option_withdrawn`, before any policy. Decision 18's rationale is corrected
  (85 F4). Tests: kit unit (`test_selection_scalar.py`: an unpriced counter after a priced
  opening is not accepted, and the exact-listing branch settles the opening;
  `test_release_authorization.py`: an escrow outside the accepted set, another token,
  and a listing accepting none; `test_plans.py`); VM integration
  (`test_negotiate_controller.py` `TestCounterNamingAnotherOption`: the unpriced counter,
  which answered `accept` against the old kit, and a continuation after a repriced
  option, through `NegotiationRuntime` and the typed client); bare metal integration
  (`test_http_negotiation.py`, through the typed client: with only `listed_price`
  configured, a substituted recipient is refused `selected_demand_not_allowed` and
  another token `escrow_field_mismatch`, and nothing is accepted). Evidence: the round's
  note under Section 10.
- **Round 1's second triage.** 122 F6: the `negotiation-protocol` delta attributes the
  refusal of an escrow outside the listing's accepted entries to the seller's acceptance,
  through which every plan a seller materializes passes, rather than to plan
  materialization in general: `materialize_escrow_terms_from_proposal` and the plan forms
  built on it hold an escrow to its pin and release condition only, since a buyer's
  derivation carries no accepted entries, and their docstring now says that a seller
  authorizes the proposal with `authorize_escrow_proposal` before materializing it.
  Documentation only; no test changes.

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
      Done. The kit's artifacts are now the proposal, the accepted proposal, and the plan,
      with no escrow terms; `escrow_terms_to_settlement_obligation` builds the envelope field
      by field; core's
      `_ALKAHEST_MECHANISM` went with the coercions, and `deal_helpers.py`'s pre-plan back-fill
      went rather than being rewritten, since nothing reads flat terms any more. A flat terms
      dict or a bare list no longer parses as an obligation or plan, in core or the kit.
      **Also changed:** `docs/development/ARCHITECTURE.toml`'s exception row excusing
      `arkhai-core`'s `alkahest.v1` vocabulary for those coercions excused nothing and the
      architecture check required its deletion; the row was `move-escrow-into-alkahest`'s,
      recorded in design D26. Unit: core `test_settlement_plan.py` (rewritten: the flat
      shapes are refused, the envelope round-trips); kit `test_plans.py` (a bare terms list
      is refused as a plan and flat terms as an obligation; the artifacts carry exactly the
      proposal, the accepted proposal, and the plan).
- [x] 9.2 `core/buyer`: `negotiation_client.py` (`NegotiationOutcome`,
      `parse_accepted_terms_from_reply`, `ResumeState`, the reply parse and resume, the three
      accept branches), `orchestration.py` (`_settle_one` always derives through
      `build_escrow_terms`; the negotiate hook), and `deal_helpers.py` (`DealContext`,
      `load_deal_context` and its back-fill, `NegotiationResumePoint`) stop reading the
      field. `AdvertisedPlanValidatorFn` runs on every branch that receives a plan and on
      resume, not only the selection branch; its callable receives what a derivation needs
      (the accepted proposal or selection, the agreed amount and duration), and
      `core/buyer` gains no import of `kit/alkahest` (D17).
      Done, with the plan check placed where funds move rather than as written:
      - **Differed:** `AdvertisedPlanValidatorFn` is unchanged and still runs on the selection
        branch at acceptance. The requirement is a check "before funding, on every path that
        funds an escrow", and every such path now runs one: `make_escrow_settle_hook` takes a
        required `check_escrows_fund_plan` port, which `_settle_one` runs over its own
        derivation whenever the seller sent a plan, refusing as `seller_plan_mismatch` before
        `create_escrow`; the resume paths (9.3, 9.4) check through the kit's derivation. A
        negotiation-time check on the escrow branch would repeat the same derivation earlier
        without guarding anything the funding-time check does not.
      - `parse_accepted_terms_from_reply` returns four values and never reads the field;
        `negotiate_with_seller` and `make_negotiate_hook` lose `decode_escrow_terms`.
      - `make_negotiate_hook` takes `accepted_listing_record(listing, proposal)`, the
        selected entry's record of the listing, written opaquely as `listing_record` in
        `negotiation_started` and an agreed `negotiation_completed` (9.3). `core/buyer`
        imports nothing from `kit/alkahest` and names no release condition.
      Unit: `test_orchestrator.py` (the helper funds exactly what it derives after checking it
      against the plan, and funds nothing, exiting `seller_plan_mismatch`, when the check
      refuses); `test_settlement_acceptance.py` (the reply parse ignores escrow terms an
      accept reply carries, well formed or not, and the outcome has no field for them; no
      round or accept branch is driven with them). No test drives
      `_negotiate_matches` itself: it calls `negotiate_with_seller` with no injection seam,
      so the hook's recording is covered only through the domains' stage records (9.4).
- [x] 9.3 The run-log: `negotiation_completed` and both negotiate CLIs' `run_ended` record
      the selected listing's advertised release conditions; `load_deal_context` and the
      resume point read them; a resumed run derives from the Agreement's selected option and
      those conditions and checks any recorded seller plan against them; a run-log accepted
      without recorded conditions and not yet funded is refused before funding, naming that
      a new run is needed; a run whose escrow exists resumes (D17).
      Done.
      - Recorded as one opaque `listing_record`, which `kit/alkahest` writes and reads:
        `release_conditions_record(listing)` holds the listing's advertised conditions,
        read by `advertised_release_conditions` (a list or stored JSON text; unreadable
        records none, which then authorizes nothing), and `recorded_release_conditions`
        reads them back, refusing a record that is not an object or conditions that are not
        a list. Core names no release condition. `market buy` writes the record in
        `negotiation_started` as well as an agreed `negotiation_completed`, and both
        negotiate CLIs in `run_started` as well as `run_ended`, so a run resumed
        mid-negotiation still holds it; a resumed negotiation carries its first run's record.
      - `DealContext.listing_record` reads it from the accepted events, refusing conflicting
        records. `NegotiationResumePoint.listing_record` keeps one record per listing and
        returns the resumed listing's, since a `market buy` run records every listing it
        tries and those may advertise different conditions.
      - The kit's `derive_accepted_escrow_terms` takes the record, derives a resumed escrow
        from the accepted proposal and its conditions, and holds it to the recorded plan
        (`require_escrow_terms_fund_plan`, new in `plans.py`: maker, chain, contract,
        expiry, and every obligation field, `0x` hex case-insensitively and every other
        string exactly). No record, or one without the conditions key, raises
        `ReleaseConditionsUnrecordedError` (`release_conditions_unrecorded: … start a new
        run`); a record holding an empty list, as for a listing advertising none, is
        refused as `release_condition_not_advertised`. A run whose escrow exists skips
        derivation and resumes, as before.
      - **Differed:** a resumed run derives from its recorded accepted proposal, not from
        the Agreement's selected option, as the task and the delta word it; design D17's
        Section 9 paragraph says why the inputs suffice.
      - **Also changed:** a resumed derivation takes the agreed amount exactly from the
        recorded Agreement, through core's new `exact_agreed_amount`: the run-log's
        `agreed_amount` passes through a float, which cannot hold an 18-decimal amount and
        would have failed the plan check.
      Unit: kit `test_plans.py` (the derivation funds the seller's plan; a plan paying another
      recipient, another amount, or no escrow is refused naming the field; a resumed run
      derives from its record, refuses a plan it does not derive, and refuses a run with no
      record or no conditions in it; the record round-trips and an unreadable one is
      refused; the conditions reader); core `test_identity_recovery.py` (a deal carries its
      record and an older run none; conflicting or non-object records are refused; a resume
      point carries the record made at the run's start, and a `market buy` resume carries the
      record of the listing it resumes, not another's; the exact amount of an 18-decimal
      Agreement survives where the float does not).
- [x] 9.4 VM buyer (`settlement_stages.py` `enrich_deal`, `_accepted_proposal_chain`,
      `_resume_alkahest`, `_refuse_without_release_condition`; `escrow_client.py`;
      `escrow_cli.py`; `buyer_client.py`; `negotiate_cli.py`; `buy_cli.py`;
      `buy_orchestrator.py`) and API-credit buyer (`settlement_stages.py`
      `AlkahestBuyerStage.enrich`, `settle_cli.py`, `negotiate_cli.py`, `buyer_client.py`,
      `buy_cli.py`, `escrow_client.py`) stop reading the field; API credits supplies a plan
      validator over `kit/alkahest`'s `validate_selected_escrow_plan` as VM does (D17).
      Done.
      - Both domains' Alkahest stages gain `listing_record` (the kit's
        `release_conditions_record`) and their payment stages an empty one; both settle hooks
        pass the kit's `require_escrow_terms_fund_plan` as the plan check. Each domain's
        `accepted_listing_record` dispatches to the selected entry: VM through the match's
        selected option, API credits through the proposal's kind (an escrow proposal is
        Alkahest's, a selection names its mechanism).
      - VM's `_resume_alkahest` and `escrow_cli create` share `derive_resumed_escrow_terms`
        (`settlement_stages.py`), each with its own refusal; API credits' `settle_cli`
        derives the same way. Both `resumed_proposal_refusal` helpers went, now unused.
      - **Differed:** API credits supplies the plan check through its settle hook, not a plan
        validator: its buyer opens with escrow proposals, which the selection-branch validator
        never sees (9.2).
      - `escrow_cli.py` imports `derive_resumed_escrow_terms` at module level: no import
        cycle prevents it, since `settlement_stages` imports none of `escrow_cli`'s importers.
      Unit: VM `test_release_condition_refusals.py` (a run recording no conditions is refused
      as `release_conditions_unrecorded` on both resume paths, `escrow create` and `settle`;
      `escrow create` funds exactly the seller's plan derived from recorded conditions; both
      paths refuse a plan paying another recipient as `seller_plan_mismatch`, `escrow
      create` funding nothing); VM `test_negotiate_stage_dispatch.py` (`market negotiate`
      records the selected stage's listing record at run start and end, the Alkahest
      conditions or an empty record for payments); API credits `test_settle_credentials.py`
      (the three settle cases through `run_settle_from_log`) and
      `test_settlement_composition.py` (an escrow proposal records the listing's conditions,
      a payment selection nothing). These CLI tests patch the commands' module attributes,
      as the files' existing tests do: the commands take no injected collaborators. No test
      drives API credits' `negotiate` CLI recording, or the carry-forward of a resumed run's
      record by VM's `negotiate --from` or `buy --from`; only the resume point's reading of
      it is tested (9.3). `escrow_cli create` keeps its pre-existing call-time import block,
      `make_create_escrow_fn` among it, which the file's tests patch through.
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
      Done, as listed under 9.1 to 9.4, plus the application-integration replies: VM
      `test_negotiate_controller.py` (two accepts, the plan's obligation now asserted on its
      own fields) and `test_publication_loop.py`, and bare metal `test_http_negotiation.py`'s
      materializing accept, all assert no `accepted_escrow_terms` (no API-credit storefront
      test asserts it of its reply; the kit producer test covers what it sends); bare metal's
      `test_domain_runtime.py`, `test_settlement.py`, and `test_http_negotiation.py` fakes no
      longer return the field. **Differed:** `test_resume_helpers.py`,
      `test_buy_resume_cli.py`, `test_buy_orchestrator.py`, `test_buyer_client*.py`,
      `test_negotiation_flow.py`, and `test_negotiate_cli.py` needed no change and pass. The
      mismatch is refused at funding (`test_orchestrator.py`, the kit, VM's `escrow create`
      and `settle`, API credits' `settle`), not at the selection branch's acceptance, where
      the existing validator still runs (9.2). "A funded run resumes" keeps its existing
      coverage (a run whose escrow exists skips derivation; VM
      `test_vm_settlement_helpers.py`). No test drives a whole `market buy` against a
      mismatching seller through `_negotiate_matches`, and the live API-credit escrow path
      (`buy_cli`'s settle hook) is covered only by `e2e_credits_deal`, unrun here.
- [x] 9.6 Versions: `arkhai-kit-alkahest`, `arkhai-core`, `arkhai-core-storefront`,
      `arkhai-core-buyer` (and the exact pin in `domains/bare_metal/buyer`),
      `arkhai-vms-buyer`, `arkhai-apicredits-buyer`, the three storefronts; `make lock`.
      Bumped: `arkhai-core` 0.5.0 (a flat shape no longer parses), whose exact pin moved in
      `arkhai-core-registry` (0.4.1) and `arkhai-core-registry-client` (0.12.3), bumped for
      it, and in `arkhai-kit-settlement-runtime`, `arkhai-kit-contact-exchange`, and
      `arkhai-kit-arkhai-payments`, already bumped and unreleased here; the registry-client
      pin moved in `arkhai-core-buyer` and `arkhai-bare-metal-buyer`. VM storefront 0.22.0
      (its bare-metal pin with it), bare-metal storefront 0.22.0 (`arkhai-core-storefront`
      floor 0.16.0), API-credit storefront 0.16.0. `arkhai-core-buyer` 0.6.0,
      `arkhai-vms-buyer` 0.8.0, and `arkhai-apicredits-buyer` 0.6.0: this section's changes
      to them are incompatible (a removed field and keyword, a new required hook argument, a
      four-value reply parse, removed helpers), which before 1.0 takes a minor bump, though
      each was already patch-bumped and unreleased here; bare metal's exact
      `arkhai-core-buyer` pin moved with it. Floors: both buyers on
      `arkhai-core-buyer>=0.6.0` and `arkhai-kit-alkahest>=0.10.0`. **Not bumped:**
      `arkhai-kit-alkahest` (already minor-bumped to 0.10.0), `arkhai-core-storefront`, and
      `arkhai-bare-metal-buyer`, already bumped and unreleased on this branch. `make lock`.
- [x] 9.7 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make test-vms-buyer`,
      `make test-apicredits`, `make test-storefront`, `make test-bare-metal`; `make test`;
      `make check-packaging`. End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, and
      `e2e_credits_deal` fund through the buyer's own derivation, and
      `e2e_bare_metal_mock_deal` through the typed client.
      Results (`make dist` and `make lock` first; the last six rerun after the fresh-context
      fixes):
      - `make -C kit test-settlement-runtime test-contact-exchange test-arkhai-payments`:
        111, 127, 84 passed; `make test-registry` 128 and 125 passed.
      - `make -C kit test-alkahest` 413 passed; `make test-core` passed (120, 144, 217 with
        2 skipped, 65).
      - `make test-vms-buyer` 207; `make test-apicredits` passed (buyer 30, storefront 221,
        the rest unchanged); `make test-bare-metal` passed (storefront 446); `make
        test-e2e-unit` 38.
      - `make test-storefront`: unit 1119 (1 skipped); integration 450 with the two
        environmental `test_alkahest.py` failures (no Node.js or Anvil here).
      - `make test`: not run whole; the suites above cover every project whose code, pins, or
        locks changed. Core's mypy typecheck (`make -C core typecheck`) was denied in this
        unattended run and is unrun. `make check-packaging` passed; `make check-change`
        fails only on the two citations Sections 13 and 22 create.
      - End-to-end, unrun: `e2e_deal_buyer_cli` and `e2e_buy` (VM, selections) and
        `e2e_credits_deal` (API credits, escrow proposals) are expected to fund the escrow
        the buyer derives and checks against the seller's plan; `e2e_bare_metal_mock_deal`
        funds through the typed client and is unaffected but for the reply. No scenario
        changed.

Section 9 notes (handoff):

- **The plan check sits at funding, not at acceptance** (9.2's differed note). A reviewer
  may want the escrow branch checked at acceptance too; it would add a second derivation
  in `negotiate_with_seller` that funding already performs.
- **Release conditions are recorded through a domain hook, as one opaque record.** Core
  writes and reads the selected entry's `listing_record` whole; `kit/alkahest` owns both
  its writer and its reader, so no release condition is named in core. The first draft
  recorded `release_conditions` as a core-named field; the fresh-context check flagged it
  as Alkahest knowledge in core, and also that merging every event's record would refuse a
  `market buy` resume whose earlier listings advertised other conditions.
- **Old run-logs.** A run accepted but unfunded before this section records no listing
  record and is refused with `release_conditions_unrecorded`; one with a plan in the
  pre-plan flat shape no longer loads at all, since the coercions went. Neither has funds
  at stake.
- **The exception row deleted from `ARCHITECTURE.toml` belonged to
  `move-escrow-into-alkahest`** (design D26); that change's other rows and its content
  divergence stand.
- **Fresh-context checks.** Two ran; the second, after the record and version fixes,
  found no layering, comment, or version breach, and its accuracy points are fixed: plan
  comparison lowercases only `0x` hex, core's hook docstring and fixtures name no Alkahest
  concept, and the notes above state what their tests do not cover. Declined from both:
  replacing the CLI tests' module patches with injection, since the commands have no seam
  and the files' existing tests patch the same way, which the round's triage may want as a
  testability refactor; moving `escrow_cli create`'s `make_create_escrow_fn` import out of
  its pre-existing call-time block; and the three storefronts' bump in this section
  although each was already bumped and unreleased, which is harmless.
- **Round 1's triage.** 85 F12: a seller's accept reply carrying no settlement plan is
  refused before funding on every path: `core/buyer`'s `_settle_one` ends the run naming
  `seller_plan_missing` (event `escrow_create_failed`) and the plan check is no longer
  conditional on a plan being present, and `kit/alkahest`'s
  `derive_accepted_escrow_terms` raises `seller_plan_missing` for a resume with no
  recorded plan. 85 F4: decision 17's superseded bullet is rewritten to what was built,
  and the `buyer-orchestration` delta requires the plan on every funding path with a
  scenario for a reply carrying none. Tests: core unit (`test_orchestrator.py`: a reply
  with no plan creates no escrow); kit unit (`test_plans.py`: a resume with no recorded
  plan). Evidence: the round's note under Section 10.
- **Round 1's second triage.** 122 F5: decision 17's resume bullet, which 85 F4's
  correction missed, now says a resumed run derives from its recorded accepted proposal
  and the recorded conditions at the Agreement's exact amount, held to the recorded seller
  plan, as the delta and the decision's own settled paragraph do.

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
      Done. `stored_provider_problems(db)` lists `(pool, provider)` for every stored pool,
      enabled or not, whose provider no handler serves; `require_served_stored_providers()`
      raises `PoolValidationError` naming each and the registered providers. The startup
      step runs it after the declaration check, so a pool with both problems reports its
      declarations first. Library integration: `TestStoredDeclarations` (served providers
      pass; an enabled and a disabled pool naming an unserved provider are named with the
      registered providers, and a served pool is not). **Differed:** the startup test is
      not application integration as the task labels it: it drives
      `app_runtime.verify_pool_declarations` over migrated file-backed SQLite with the
      container's pool service replaced by one over the two real handlers the test lists,
      not the running application or the composition's own handler map. It shows the
      same case, enabled and disabled, refused naming the pool and those providers.
      The API-credits service, which also stores its pool, gets no provider check: it
      composes no pool service or handlers and reads a pool's provider only as metadata,
      so no handler can be missing.
- [x] 10.2 `src/middleware/auth.py` `ProvisioningAuthMiddleware.dispatch`: a route failure
      after authentication is logged and answered as a signed 500 with a fixed,
      non-revealing detail, following VM's `admin_identity.py`, and recorded as the
      request's outcome so an exact retry replays the same signed answer. Tests:
      `tests/unit/middleware/test_auth.py` (unit) and an application-integration case
      through `ProvisioningClients`: the typed client receives a signed 500, not a
      response-authentication error, and an exact retry gets the same answer rather than
      "in progress" (D23).
      Done: the route call and its body read are one `try`; a failure logs with its
      traceback and becomes `{"detail": "Provisioning request failed"}`
      (`ROUTE_FAILURE_DETAIL`), recorded and signed as any outcome is. `test_auth.py`
      (filed as unit, though like the rest of that file it runs a FastAPI app over a real
      SQLite replay store): under both response-signing schemes, the 500 verifies, its
      exact retry verifies with the same body, the route runs once, and the error is
      logged and absent from the body. The route is administrator-only, so its requests
      are always Ed25519-signed. Application integration `test_pools_api.py` `TestRouteFailureAfterAuthentication`:
      a stored pool naming an unserved provider (service-internal setup) makes the pool
      list raise; the typed client raises `ComputeProvisioningError` 500, not the
      authentication error, and an exact retry under the same request ID replays the 500
      after the row is gone, though the route would now succeed.
      **Also changed:** `test_host_capacity_derivation_api.py` asserted the in-process
      transport re-raised the route's exception; it now asserts the signed 500.
- [x] 10.3 `kit/site/src/market_site/auth.py` `SiteAuthMiddleware.dispatch`: the same signed
      500, recording nothing; an exact retry of a retry-safe route runs again, and of an
      unsafe one is refused as today. Tests:
      `kit/site/tests/integration/test_site_auth_middleware.py` (library integration);
      `domains/apicredits/service/tests/integration/test_credits_signed_roundtrip.py`
      (application integration through the typed client) (D23).
      Done, with `ROUTE_FAILURE_DETAIL` `"Site-authority request failed"`. Library
      integration: a failing reserve answers a signed 500 with the fixed detail and logs
      the error; its exact retry runs again (two calls, two signed 500s) when the route is
      retry-safe, and is refused with the 409 when it is not (one call). The envelope is
      checked by this file's own signed-header assertion, as its other cases are, not
      verified by a client. **Differed:** the application-integration case is in
      `test_signed_authority.py`, which runs the service's real `main.app`, rather than in
      `test_credits_signed_roundtrip.py`, whose gate fronts stub handlers: the storefront
      client's issuance read of a committed grant whose key row is gone (removed directly,
      as no route can produce it) gets `CreditsServiceError` 500 after verifying the
      response, not `CreditsServiceAuthenticationError`, and the service logs the error.
- [x] 10.4 Versions: `arkhai-kit-resource-pools`, `arkhai-kit-site`, the provisioning
      service, the API-credits service; `make lock`.
      `arkhai-kit-resource-pools` 0.8.0 (new public API), `arkhai-kit-site` 0.10.2,
      `arkhai-apicredits-service` 0.6.1 with its `arkhai-kit-site` floor 0.10.2; the
      provisioning service, already bumped and unreleased here, is not bumped again and
      raises its `arkhai-kit-resource-pools` floor to 0.8.0. `make lock`.
- [x] 10.5 **Verify.** `make -C kit test-resource-pools test-site`; `make
      test-provisioning`; `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: none exercises an unserved provider or a route failure, and none is owed;
      every lane's provisioning traffic passes through the changed middleware.
      Results (`make dist` and `make lock` first; the first three rerun after the
      fresh-context fixes): `make -C kit test-resource-pools test-site` 127 and 282
      passed; `make test-provisioning` unit 664, integration 488; `make test-apicredits`
      passed (service 73). Before those fixes, which touch no other project: `make -C kit
      test-fulfillment` 171; `make test-compute-provisioning` 231, `-ansible` 92,
      `-client` 50; `make test-provisioning-adapter` 29; `make test-compute` 5; `make
      test-bare-metal` passed (storefront 446); `make test-storefront` unit 1119 (1
      skipped), integration 450 with the two environmental `test_alkahest.py` failures;
      `make test-e2e-unit` 38; `make test-core`, `test-registry`, `test-vms-buyer`, and
      `-C kit test-alkahest` passed. `make test`: not run whole. `make check-packaging`
      and `make check-comment-hygiene` passed; `make check-change` fails only on the two
      citations Sections 13 and 22 create. End-to-end: the pipeline was not run in this
      section, and no scenario exercises either refusal.

Section 10 notes (handoff):

- **A failure after a streamed response has started is not caught.** A route that fails
  before starting its response is answered with the signed 500. Once a route has sent
  its response start, Starlette's `BaseHTTPMiddleware` stores the route's exception and
  ends the body stream instead of raising into `call_next`'s caller, and re-raises it
  only after sending, so the middleware would sign, and the provisioning service record,
  a truncated body under the original status. No route streams; one that does needs the
  middleware to check for that failure or to refuse streamed responses (corrected in
  round 1's triage, 85 F15).
- **Fresh-context check.** Fixed: the startup and site-kit test labels and claims above,
  the API-credits case moved onto the real application with its log asserted, the
  provider check's docstring and startup log line, and `ResourcePool` imported from its
  owner. Not rechecked after those fixes. Recorded rather than changed: `test_auth.py`
  runs an application over a real store although filed under `unit/`, as the whole file
  does; and `marketplace-identity` already holds the rule that a response is signed
  whether a refusal comes during authentication or after, which the `physical-provisioning`
  delta's site-kit half restates; closeout may prefer to promote that half there.
- **A pool with both an invalid declaration and an unserved provider** reports only the
  declarations at its first refused start; the provider refusal follows once those are
  repaired. Reporting both at once would need one combined check; neither refusal
  changes state.
- **Signed 500s replace a behaviour other tests may have leaned on**: an in-process
  transport re-raising a route's exception. Only the one provisioning test did, among the
  suites run; a suite outside them that drives the provisioning service or a `kit/site`
  gate and expects the exception would now see a 500.
- **Round 1's triage: fixes concerning no section, and the round's evidence.** 85 F15
  corrected the first note above. 85 F11: `docs/development/RELEASING.md` states that a
  change bumps each package at most once against the branch it merges into; every package
  this round touched already carries a minor bump over `dev`, so none is bumped again and
  no lock changed. 73 R2: `docs/agents/change-workflow.md` names the two call shapes the
  harness refuses on its own. 77 R1: the workflow wrapper turns SIGTERM into a `stopped`
  outcome naming the signal (`scripts/change_workflow/wrapper.py`), with a unit test.
  83 R1: `round-done` rebuilds the index from the round head after its reset
  (`scripts/round_view.py`), with a unit test of a round adding an empty file. Each
  section's own fixes are in its round-1 note (Sections 3–9). Test fixtures the fixes
  invalidated were updated: VM buyer unit fixtures now carry the seller's plan their
  stubbed derivation funds, as Alkahest-kit `EscrowTerms` (85 F12); VM unit and API-credit
  unit listing fixtures accept the escrow they propose (85 F6); a VM unit test unpacks the
  create parser's three values (85 F9); an API-credit unit test stubs the services builder
  with its seams argument (85 F3).
  **Evidence** (`make dist` first; no lock refresh owed): unit and library tests —
  `make -C kit test-policy test-alkahest test-storefront` 95, 413, and 127 passed;
  `make test-core` 120, 145, 217 (2 skipped), and 65 passed; `make test-vms-domain` 53;
  `make test-vms-buyer` 207; `make test-e2e-unit` 38; `make test-release-tooling` 1081 (11
  skipped). Unit and integration — `make test-bare-metal` passed (storefront 449, the
  others 134, 11, 40); `make test-apicredits` passed (storefront 229, service 73, the
  others 41, 30, 8, 1, and the middleware ports). `domains/vms/storefront/tests/unit/test_listing_token_extraction.py`,
  which tested only the removed listing form's token extraction, and
  `tests/integration/test_alkahest.py`, moved to `e2e_alkahest_trusted_oracle`, are
  deleted; `make test-storefront` then passed, unit 1099 (1 skipped) and integration 455.
  `make test` then passed every suite and failed only at `make test-deployment-packaging`'s
  Helm render (`helm: No such file or directory`); Helm is absent here, so the Helm render
  probe's edit is unrun. `make check-packaging` and
  `make check-comment-hygiene` passed; `make check-change` fails only on the two citations
  Sections 13 and 22 create. End-to-end: unrun here; the fix commit's validation runs the
  lanes, including `multi_registry` (88 V1), `e2e_credits_deal` (85 F2), and the new
  `e2e_alkahest_trusted_oracle` (91 O1).
  **Fresh-context check** of the diff against `da1929a`: no comment-hygiene, layering, or
  public-repository finding. Fixed: function-local imports the round's tests added
  (`test_chain_probe.py`, bare metal's `test_app_composition.py`, the wrapper test); a VM
  integration fixture replacing `publication_terms.CHAINS` (now `patch.dict` on the one
  shared mapping) and the API-credit seed-site tests replacing `listing_seed`'s module
  names (now `settings_overrides` over `[capacity]`); the `negotiation-protocol` delta
  still saying the escrow-shape policy runs only "where it runs" and two scenarios
  starting from a seller omitting the guard, which no domain can now configure (now:
  plan materialization refuses whatever the policies would accept); bare metal's status
  test not asserting the unanswering chain's own result. Its point that these
  round-1 notes pointed at a Section 10 note that did not exist was read before this note
  was written. The kit Alkahest, bare-metal, API-credit, VM integration, and release
  tooling suites were rerun after these fixes.
- **Round 1's second triage: the round's evidence.** The fixes for 122 F1, F3, F5, and F6
  are in the second-triage notes of Sections 4, 3, 9, and 8; 122 F2 is task 11.9 and
  122 F4 is in 11.5. No package is bumped (`docs/development/RELEASING.md`) and no lock
  changed. **Evidence** (`make check-packaging` first, which rebuilds the wheels): unit —
  `make -C kit test-alkahest` 415 passed, with the two new probe cases; `make test` passed
  every suite (among them `kit/alkahest` 415, the VM storefront unit 1099 (1 skipped) and
  integration 455, the bare-metal storefront 449, the API-credit storefront 229,
  `make test-e2e-unit` 38) and failed only at `make test-deployment-packaging`'s Helm render
  (`helm: No such file or directory`), as in the first triage. `make check-packaging` and
  `make check-comment-hygiene` passed; `make check-change` fails only on the two citations
  Sections 13 and 22 create. End-to-end: unrun here; `e2e_alkahest_trusted_oracle`'s kit
  derivation (122 F3) is proven by the fix commit's validation.
  **Fresh-context check** of the diff against `e15a5b2`: no concurrency defect, the
  scenario's kit calls matching their signatures, and both new probe tests failing on the
  old code. Fixed: a hung-construction test docstring still saying a late result is
  discarded; this note's Section 4 entry claiming a failed late construction is rebuilt in
  the same probe (the next probe rebuilds it); the delta's "rebuilt at each probe"
  contradicting "start no other"; a constructor raising a `BaseException` leaving the chain
  "still being constructed" for good (now delivered as an error); the materializer's
  docstring saying a seller materializes "through" `authorize_escrow_proposal`, which only
  authorizes; the late-adoption test's wait raised to one second. Declined: guarding
  `_constructions` against two concurrent steps, which the loop's cycle lock already
  excludes, and a probe stepped on a second event loop starting a second construction,
  which no storefront does. `make -C kit test-alkahest`, `make test-storefront`,
  `make check-packaging`, and `make check-comment-hygiene` were rerun after these fixes
  and passed.
- **Round 1's third triage: the round's evidence.** The validation of `9aa024e`
  (`134-validation`) passed: local, the served Helm scenarios, and all three pipeline
  lanes, the kit-derived trusted-oracle scenario (122 F3) passing in the VM lane and on
  Helm. The fix for 132 F1 is in Section 3's third-triage note; it changes only the
  validation tooling and a note. **Evidence:** unit — `make test-release-tooling`
  (`scripts/tests`, with the updated `test_validate_slice.py`) 1081 passed, 11 skipped;
  `make test` passed every suite and failed only at `make test-deployment-packaging`'s
  Helm render (`helm: No such file or directory`), as in the earlier triages.
  `make check-packaging` and `make check-comment-hygiene` passed; `make check-change`
  fails only on the two citations Sections 13 and 22 create. End-to-end: the served list's
  new entry runs in the fix commit's Helm validation.
  **Fresh-context check** of the diff against `9aa024e`: no correctness defect; the
  selection has no duplicates, and the trusted-oracle scenario leaves `not_run`. Fixed:
  the marker variables put in the pipeline's lane order (VM, bare metal, API credits), as
  `pipeline_markers` promises; the selection's comment overstating that the served list
  lies outside the lanes (only `contracts` does); `change-validate`'s instruction still
  saying the all-scenarios run replaces the served list; this triage's note in Section 3
  reflowed. Declined: refreshing `helm-e2e-pipeline-parity`'s proposal, which describes
  the Helm run's selection as it was; that change's design owns its account of the current
  system. `make test-release-tooling`, `make check-packaging`, and
  `make check-comment-hygiene` were rerun after these fixes and passed.

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
      Done. The liveness and readiness probes now name the container port `http`, as bare
      metal's do, rather than repeating the agent's port number; the port they reach is
      unchanged. The comment in place of the init containers states why none waits; it
      cites no spec heading, since "A deployment does not wait on a service's
      dependencies" exists only in the delta until the archive.
- [x] 11.2 Render tests (`docs/development/TESTING.md` "Chart Render Tests"):
      `helm/charts/storefront/tests/test_render.py` replaces every `wait-for-*` assertion
      with one test, over every fixture, that no container named `wait-for-` renders and
      that `startupProbe` does; the tests that a chain's RPC is or is not waited for go.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts its `startupProbe`.
      `helm/scripts/test-render.sh`: the EVM fixture's chain-readiness assertion goes and
      its `CHAIN_ID|RPC_URL` check stays (D20).
      Done (chart render). The VM test renders the chart defaults, the local release, every
      committed fixture that renders (the `invalid-*` ones exist to be refused), and a
      two-agent release, and asserts of every agent's Deployment: no `initContainers`, no
      `wait-for-` container, a `startupProbe` on `/health` at port `http`, and no
      `initialDelaySeconds`. Bare metal's asserts the same over its example, its defaults,
      and an umbrella release. Removed: the two "a chain's RPC is or is not waited for"
      tests; the differently-spelled-section test now proves the spelling is read by the
      service-peer check, which refuses the same peer without the release's principal.
      `test-render.sh`: the EVM `wait-for-rpc` assertion goes, and the wallet-free
      assertion keeps only `CHAIN_ID|RPC_URL` (the task's "its" read as the remaining
      chain check, which is the wallet-free deployment's).
- [x] 11.3 VM `src/startup.py`: delete `_preflight_provisioning` and its step, and correct
      the step list's docstring; `settings.toml` and `groups/config.py`'s template lose
      `[seller.provisioning].fail_on_unreachable` and `preflight_timeout`; both join
      `retired_settings.py`'s removed settings, so a configuration stating either is
      refused by key as every retired setting is; regenerate the values schema with `make
      helm-values-schema` and update `tests/unit/test_values_schema.py` and
      `tests/integration/test_publishable_startup.py` (D20).
      Done. The settings live at `[provisioning]`, not `[seller.provisioning]` (the old
      error text's name), so the retired keys are `provisioning.fail_on_unreachable` and
      `provisioning.preflight_timeout`. **Differed:** `make helm-values-schema` was denied
      in this unattended session, so the two generated schema files
      (`helm/values.schema.json`, `helm/charts/storefront/values.schema.json`) were edited
      by hand with the two refused patterns `config_definition` adds for a nested retired
      key; the drift test (`test_committed_values_schemas_carry_the_generated_definition`,
      which compares the parsed definition with the generator's) passes, so the files equal
      the generator's output up to key order; byte equality with a regeneration is unshown,
      so `make helm-values-schema` is owed when it can run. Tests: unit
      `test_startup_refusal.py` (each key refused naming why, in two spellings),
      `cli/test_config.py` (`config set` refuses both, each in two spellings),
      `test_values_schema.py` (the definition refuses both, each in two spellings and as
      `null`, and accepts the section's other keys); application integration
      `test_publishable_startup.py` (the real lifespan refuses both under the retired
      heading before opening the database).
- [x] 11.4 API credits `src/startup.py`: delete `_preflight_credits_service` and its call;
      the refusal of an unset `[credits].service_url` stays, run with the storefront's other
      configuration refusals. `settings.toml`, `storefront.credits.toml`, and
      `docs/cookbooks/vllm-apicredits-seller.md` lose `[credits].fail_on_unreachable` and
      `preflight_timeout`; the storefront refuses both by key, as it refuses
      `claims_sweep_interval`. `tests/unit/test_server_composition.py` stops patching the
      preflight (D20).
      Done. `startup_refusal.py` gains `credits_configuration_problems` under its own
      heading, "the storefront has no credits service to sell for", so an unset
      `service_url` is now refused before the signer or database, with the capacity
      refusals, where it had been refused at the end of startup. `retired_settings.py`
      gains `REMOVED_SETTINGS`, and `retired_setting_problems` names removed keys after
      renamed ones. Unit `test_server_composition.py`: both keys, each in two spellings, and
      an unset `service_url` refuse startup before anything is composed.
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
      Done. VM `test_degraded_startup.py` (application integration: the real app, its full
      lifespan and every startup step, read through `StorefrontClient`): the registry, the
      site, and the provisioning service point at a port nothing listens on; the chain is
      reached only through the two Alkahest seams, a stub refusing until switched (the
      configured chain is set through the configuration module's own `CHAINS` mapping, as
      the unit composition test does; its URL is never dialled). It starts and answers
      `/health`; the pause holds every loop; status reports the registry check
      `unreachable` and the status `degraded`, both site projection families
      `unavailable`, and Alkahest unready with exactly `alkahest.chain_unreachable`
      (reachability); once the stub answers, a stepped probe constructs the client the
      start could not and Alkahest is ready, with no restart. The registry and the site are
      never brought back, so their recovery without a restart is not shown here.
      **Differed from the task's wording:** the stepped publication cycle does not fail.
      With the site unloaded it holds the site (`site_projection_unknown`), closes nothing,
      and catches the unreachable availability read; with nothing to publish it never calls
      the registry, so its outcome is completed. The test asserts that. The registry's
      unreachability reaches status through the registry check alone, so the delta
      scenario's "a failed publication cycle" holds only for a storefront with something to
      publish; triage should decide whether the scenario's wording changes. The storefront
      DB starts empty, so "no listing closed" is shown as a cycle that holds the site and
      records no close, not over an existing listing. Reverting the preflight would fail
      this test (the old step raised after its timeout with the provisioning service
      refused); that was reasoned from the deleted code, not run.
      API credits `test_lifecycle_status.py`
      `test_startup_does_not_wait_for_an_unreachable_credits_service` (application
      integration over the app's routes; the lifespan is not run, as the rest of that file,
      and the storefront's own `_startup_tasks` runs instead): with `[credits].service_url`
      and the configured quota site — the credits service hosts the ledger — refused, the
      seed `configured_listing_seed` builds from a configured `[seed]` table registers
      through the real capacity-administration client at that site; startup reaches its
      loops, `/health` answers, and two stepped `listing-seed` cycles each report `waiting`
      / `credits_service_unanswered` (the second with two attempts); status records the step
      completed and names no URL. A call succeeding once the service answers is not shown.
- [x] 11.6 The `deployment-state` delta: the permanent requirement "A storefront chart
      passes service configuration through" still permits a chart to wait for a configured
      chain's RPC or the internal registry before the storefront starts, which D20 and the
      delta's added requirement forbid. Add to `specs/deployment-state/spec.md` a MODIFIED
      block for that requirement, copied whole with that example removed, so the archive
      leaves no contradiction; `openspec validate unbacked-bare-metal-listings --strict`
      passes (D20; a correction of the delta to the reviewed decision).
      Done: the block is the permanent requirement and all its scenarios, word for word,
      without the sentence "The chart MAY read the passed-through configuration to make a
      Kubernetes decision, such as waiting …". The whole sentence goes rather than its
      example alone: waiting was its only instance, and the chart makes no other
      Kubernetes decision from the configuration. Strict validation passes (inside
      `make check-change`).
- [x] 11.7 Versions: `arkhai-vms-storefront`, `arkhai-apicredits-storefront`; the chart
      versions per the charts' own convention; `make lock`.
      Neither package is bumped: both already carry this change's minor bump over
      `origin/dev` (`arkhai-vms-storefront` 0.17.0 → 0.22.0, `arkhai-apicredits-storefront`
      0.10.0 → 0.16.0), and `docs/development/RELEASING.md` bumps a package at most once per
      change. The storefront chart, unbumped on this branch, goes 0.3.0 → 0.4.0 (its
      Deployment changed shape), with the umbrella's dependency pin on it and the umbrella
      itself 0.3.0 → 0.4.0, as the last chart change did; the bare-metal chart changed only
      its tests and is not bumped. No dependency changed, so no lock is owed (see the
      section's handoff note on the locks a local environment refresh rewrote).
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
      Done. Bare metal passes the escrows its ready clauses built, so its conditions name
      the chains of what it publishes rather than of every Alkahest clause, which is the
      same set while Alkahest is ready. VM keeps reading the section from configuration,
      now through `publication_terms.configured_alkahest_section()`, since the derivation
      runs on paths whose composition is a test double without a settlement config.
      `alkahest_ready` stays: API credits' listing service still reads it to drop request-
      supplied escrows. API credits' refusal of an unconfigured chain now carries the kit's
      message ("settlement clause references unknown chain …"); no test named the old one.
      The VM chart render test's storefront probe derives through the kit function too.
      Tests: kit unit `test_release_conditions.py` — conditions per named chain, none for
      no escrow, an unconfigured chain refused, and nothing while Alkahest is unready or
      absent from readiness even with an unusable section and an unconfigured chain; each
      domain's existing unready case is unchanged.
- [x] 11.8 **Verify.** `make -C helm test-render` (chart render); `make test-storefront`,
      `make test-apicredits`; for 11.9, `make -C kit test-alkahest` and
      `make test-bare-metal`; `make test`; `make check-packaging`. End-to-end: every VM-lane
      and API-credit-lane scenario starts on the changed startup. The local Helm topology
      run of D14 — `make helm-topology-up` and `make helm-topology-check` on this round's
      commit, no init containers on the VM storefront — is the maintainer's at this round's
      validation, recorded unrun if not done.
      Results (`make dist` after the kit change, so every storefront ran on the rebuilt
      `kit/alkahest` wheel): `make -C helm test-render` passed on Helm v3.21.0 (not CI's
      pinned v4.3.0), with both storefront environments present, so the loader, startup
      refusal, and release-condition probes ran rather than skipped. `make test-storefront`
      unit 1108 (1 skipped), integration 457; `make test-apicredits` passed (storefront
      235, the others 41, 73, 30, 1, 8, and the Rust middleware port) — one earlier run
      failed `test_payment_settlement.py::test_a_refund_recorded_before_issuance_start_stops_issuance`,
      which races an `asyncio.sleep(0.05)`, while the VM suite loaded the machine, and passed
      in four other runs; `make -C kit test-alkahest` 416; `make test-bare-metal` passed
      (storefront 449; 134, 11, 40). `make test` stopped at `test-provisioning`'s unit
      suite on one environment-dependent failure (handoff note) and `make -k` was denied, so
      the targets after it were run singly: provisioning service integration 488,
      `test-provisioning-iac` 65, `test-registry` 128 and 125, `test-registry-client` 25,
      `test-provisioning-adapter` 29, `test-compute` 5, `test-vms-domain` 53,
      `test-vms-buyer` 207, `test-e2e-unit` 38, the targets above, and
      `test-deployment-packaging`, whose release tooling failed four tests — three
      `test_the_current_tree_passes` reading a gitignored local directory, and
      `test_change_next_step.py::test_an_earlier_rounds_token_does_not_decide_a_triage_in_progress`,
      which builds its own repository and exercises `scripts/`, which this section does not
      touch — and whose Helm render then passed when run alone. `make check-packaging`
      fails, but every finding of its five checks (`check-uv-setup` 51, `check-locks` 37,
      `check-python-version` 25, `check-project-layout` 28, `check-architecture` 22) is a
      project under that local directory; no repository project is named, and the architecture
      check reports the scope rules holding. `make check-change` fails only on
      comment hygiene (all 485 findings under that local directory) and the two citations Sections
      13 and 22 create; its strict OpenSpec validation passes. End-to-end: the pipeline was
      not run in this section; the VM and API-credit lanes start every storefront on the
      changed startup and so exercise it, and no scenario starts one with a dependency down.
      The local Helm topology run is the maintainer's, unrun here.

Section 11 notes (handoff):

- **The unattended session's limits.** `make helm-values-schema`, a single test file run
  (`pytest`, `uv run`, or `PYTEST_ADDOPTS` through make), `make -k`, `make reinit` (but
  not `make init`), and chained shell commands were denied; each suite was run whole
  through its make target. The VM integration suite takes about 14–23 minutes, so a
  failing new test costs a whole run to read its traceback.
- **Locks the environment refresh rewrote.** Every `make init`/`reinit` here (and so
  `make test`) rewrote the touched projects' `uv.lock` files: per-dependency platform
  markers and extra greenlet wheels (s390x, riscv64), with no version change. The locked
  uv on this machine evidently differs from the one that wrote the committed locks.
  Restoring them (`git checkout --`, `git restore`) was denied, so the section's commit
  names its files and leaves the nineteen rewritten locks uncommitted in the worktree;
  nothing in this section changes a dependency, and `check-locks` reports no repository
  lock either way. The owner restores or keeps them; a later session should not commit
  this churn with a section.
- **A local directory trips comment hygiene.** A gitignored directory of third-party
  package sources sits in the working tree, and
  `scripts/check_comment_hygiene.py`, which walks the tree with a fixed exclusion list,
  reports its RFC "Section" references (485 lines). No finding is in repository code.
  Moving the directory out of the tree, or excluding it in the script, is the owner's
  call; this section did neither.
- **A provisioning-service test fails here at `HEAD` too.** `make test` stopped at
  `provisioning/compute/service` `tests/unit/test_config.py::
  test_provisioning_bootstrap_dotenv_uses_environment_layer_without_dotenv_local` (the
  test's `.env` value is not read: `'settings' == 'dotenv'`). This section changes nothing
  in that project but its lock's wheel list, which was restored, so the failure is this
  environment's; it passed in Section 10's runs. The targets after it were run one by one.
- **Dotted `settings_overrides` keys leak in the API-credit storefront.** Overriding
  `capacity.sites` through `settings_overrides` in an integration test left the site in
  the configuration for a later unit test (`capacity.seed_site is required with multiple
  sites`). Replacing `[capacity]` whole and restoring it, as
  `test_server_composition.py`'s `_capacity_sites` does, does not leak; the integration
  test now has its own copy of that helper.
- **The degraded-start scenario's publication wording.** See 11.5: a VM storefront with
  nothing to publish completes its publication cycle while the registry is unreachable.
  Triage decides whether the delta scenario says "the registry check failing" instead.
- **Fresh-context check** of the diff against `1df44f4c0`: no layering, import-placement,
  test-level, documentation-placement, versioning, or public-repository finding. Fixed:
  evidence claims that overstated their tests (registry and site recovery, which neither
  degraded-start test shows; the API-credit seed now built by `configured_listing_seed`
  from configuration rather than injected; "nothing patched in a module"; "in any
  spelling", now tested in two spellings per key), the lock note this handoff now makes,
  the refusal messages and test docstrings phrased as history ("no longer waits"), and the
  unchecked 11.5 and 11.9 boxes. Declined: import-order nits in files that are not sorted
  today; regenerating the schemas, which the session cannot run (owed, below).
- **Owed beyond this section:** `make helm-values-schema` once it can run (byte equality
  of the hand-edited schemas); the local Helm topology run (11.8); `TESTING.md`'s loop
  tables still list neither `alkahest-chain-probe` nor `listing-seed`, which closeout's
  promotion (decision 22's and 19's `TESTING.md` items) adds.
- **Corrections after Section 13** (a repair pass on uv 0.11.17 and Helm v4.3.0, the
  versions `.github/workflows/tests.yml` pins, and Node 22):
  - `make helm-values-schema` has run. It rewrote `helm/values.schema.json`,
    `helm/charts/storefront/values.schema.json`, and
    `helm/charts/bare-metal-storefront/values.schema.json`, each byte-identical to the
    committed file, so 11.3's hand edit equals the generator's output.
  - `make -C helm test-render` (inside `make test-deployment-packaging`) passed on Helm
    v4.3.0 with both storefront environments present, so the loader and startup-refusal
    probes ran.
  - The provisioning failure in "A provisioning-service test fails here at `HEAD` too" was
    the test's, not only the environment's. Dynaconf's `.env` discovery returns the first
    `.env` it finds walking up from the invoked script, before it tries the working
    directory, so a `.env` in any ancestor directory of the test runner shadowed the test's
    own. The test now roots discovery at its own directory (`ROOT_PATH_FOR_DYNACONF`); its
    assertions are unchanged, and the service's discovery is as `DEPLOYMENT_AND_CONFIG.md`
    describes. The service's unit suite then passed (666) within `make test`.
  - `test_change_next_step.py::test_an_earlier_rounds_token_does_not_decide_a_triage_in_progress`
    depended on the clock: two files written back to back usually share a modification
    time, which `change_next_step.governing` reads as triaged together. The test now sets the
    earlier triage's time before the later review's; `scripts/change_next_step.py` is
    unchanged.
  - The locks the environment refresh rewrote (the note above) are a uv version's: with the
    pinned uv, every committed lock passes `make check-locks`, while each project's `reinit`
    still rewrites some of them (wheels for platforms outside a project's declared
    `environments`, or dependency markers). They were left as committed; whether to relock
    with the pinned uv is the owner's.
  - The degraded-start scenario now states what the start shows: the registry check
    unreachable and the storefront degraded, Alkahest unready for reachability, the unloaded
    site's listings held with none closed, and Alkahest ready and publication reaching the
    registry once each answers, without a restart. Recovery evidence added, each at
    application integration through the typed clients, and passing on first run:
    - VM `test_publication_loop.py::test_a_listing_every_registry_refused_is_published_once_they_answer`.
      With a candidate and every registry refusing, the listing is recorded and stays open,
      each registry's record is read back unpublished and diverged, and the next cycle after
      they answer publishes it to both, with no divergence left.
    - VM `test_negotiate_controller.py::TestSourceConfirmationWindow::test_a_round_refused_while_the_site_fails_succeeds_once_it_answers`.
      A round refused retryably while the site fails is countered once it answers.
    - API credits
      `test_lifecycle_status.py::test_the_seed_completes_once_the_credits_service_answers`.
      `listing-seed` waits while the credits ledger refuses connections, then registers and
      creates the listing once it answers.
    - Site recovery after a restart while unreachable was already shown by
      `test_pool_overrides_api.py::test_a_site_with_no_projection_holds_its_listings_and_its_override_is_unknown`.
  - **Open for triage:** with a candidate to publish and every registry refusing, the
    publication cycle completes, reporting `registry_not_converged` per listing, so loop
    status shows no failed cycle. Decision 20's "a failed publication or convergence cycle in
    loop status" therefore still disagrees with the code. Neither side is changed here.

## 12. Helm test pods carry no workload selector label

Delivers a test-labels helper in every chart and a topology render assertion (D21;
`deployment-state` "Helm test pods carry no workload selector labels"). Touches
`helm/charts/*` and `helm/tests/test_release_topology.py`.

- [x] 12.1 A `<chart>.testLabels` helper in each chart's `templates/_helpers.tpl` —
      `registry`, `storefront`, `provisioning`, `e2e-tests`, `validate-contracts`,
      `bare-metal-storefront` — carrying chart, version, managed-by, instance, and
      `app.kubernetes.io/component: test`, never `app.kubernetes.io/name` (D21).
      Done; each helper's comment states why `name` is left out. The version label
      renders where the chart states an `appVersion`, as each chart's general labels do;
      bare metal's general labels carry none, its test labels do.
- [x] 12.2 Each chart's test Pod takes it, under `helm/charts/`:
      `registry/templates/tests/registry-environment-test.yaml`,
      `storefront/templates/tests/storefront-environment-test.yaml`,
      `provisioning/templates/tests/provisioning-smoke-test.yaml`,
      `helm/charts/e2e-tests/templates/tests/e2e-deal-test.yaml`,
      `validate-contracts/templates/tests/chain-environment-test.yaml`, and
      `bare-metal-storefront/templates/tests/health-test.yaml`, which also gains
      `"helm.sh/hook-delete-policy": before-hook-creation` as the others have (D21).
      Done; bare metal's hook annotation is now quoted as the others are. These six are
      every `helm.sh/hook` the chart templates hold (read from the templates); the
      topology test below ties the test pods it checks to the Pods rendered from each
      chart's `templates/tests/`.
- [x] 12.3 `helm/tests/test_release_topology.py` (chart render): over both topology releases,
      parse each Deployment's `spec.selector.matchLabels` and each Pod annotated
      `helm.sh/hook: test` in either quoting; assert no such Pod carries all of any
      Deployment's `matchLabels`, and each carries `component: test` and no `name`.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts the delete policy
      (D21).
      Done (chart render). `test_no_test_pod_carries_a_workload_selector` reads both
      releases' Deployment selectors and test Pods' labels with the standard library;
      asserts the Pods it reads as test pods are exactly those rendered from a chart's
      `templates/tests/`, each selector requires `name`, and each test Pod carries
      `component: test` and its release's instance label and no `name` and no
      Deployment's whole selector. It is a static stand-in for the scenario "A registry's
      pods are selected", which only a cluster shows. Broken once while written: with
      `app.kubernetes.io/name` added to the registry's test labels it fails naming that
      Pod and its `name` label (an earlier break, the Pod back on its general labels,
      failed first on `component`); restored, it passes. Bare metal's
      `test_the_health_test_pod_is_replaced_on_each_run_and_selected_by_no_workload` asserts
      the quoted hook and delete policy, `component: test` and the instance label, no
      `name`, and that the Deployment's selector requires `name`; with the delete policy
      removed it fails, and restored it passes.
- [x] 12.4 **Verify.** `make -C helm test-render`; `make test`; `make check-packaging` if a
      chart version changed. End-to-end: the Helm topology check of 11.8 runs every test Pod;
      no compose scenario covers chart labels, and none is owed.
      No chart version changed: the change edits only test-hook templates and helpers, as
      the last chart change did to the registry's test Pod without a bump, and the
      storefront chart and umbrella already carry Section 11's bump. The bare-metal chart
      stays at 0.3.0 though its test template changes here (and its values schema did
      earlier in this change); whether a chart bumps for that is the owner's call, since
      `docs/development/RELEASING.md` does not cover charts. `make check-packaging` was run
      all the same, as `AGENTS.md` asks before a commit, and fails only on that local directory
      (Section 11's note). Results: `make -C helm test-render` passed on Helm v3.21.0, not
      the v4.3.0 `.github/workflows/tests.yml` pins, with both storefront environments
      present. **Differed:** `make test` was not rerun: Section 12 changes
      only chart templates and the render tests, which no suite but
      `test-deployment-packaging`'s Helm render reads, and that render is the run above;
      the rest of `make test` ran on Section 11's tree, and stops here on the
      environment's provisioning failure (Section 11's note). End-to-end: none; the
      topology check of 11.8 is the maintainer's, unrun here.

Section 12 notes (handoff):

- **Fresh-context check** of the diff against `218835f64`: no template, selector,
  comment-hygiene, placement, or public-repository finding; every selector the charts
  render requires `name`, so no test pod can match one. Fixed: the topology test now
  asserts the instance label on every test pod and ties the pods it reads to the chart
  test templates; the break-once evidence was redone so the `name` assertion itself fails,
  and bare metal's test was broken once too; the docstrings no longer claim runtime
  replacement or an unresolved spec citation; a stray blank line. Taken up rather than
  declined: `make check-packaging` run despite the plan's "if a chart version changed".
  Left to the owner: whether the bare-metal chart bumps for its test-template change.
- The topology test reads YAML with the standard library: `_mapping_under` takes the
  `key: value` lines nested one indent under a header line. A template that rendered a
  label as a flow mapping or a multi-line value would read as absent; none does today.

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
      Done. Each watchdog counts its timer cycles past the gate (`_timer_cycles_in_flight`;
      the lease lifecycle's `check_leases`, which its `LeaseWatchdog` timer calls, and the
      convergence loop's `_run_timer_cycle`) and reports `is_at_gate`: paused with none
      running. An explicit cycle (`force_check_leases`, `run_cycle`, `advance_cycle`) is
      the caller's own and does not count. A loop sleeping its interval while paused reads
      at its gate, since it can start no cycle before the gate. **Differed:** the routes
      file needed no change (route contracts carry no response shape); the field is the new
      `compute_provisioning_contracts.WorkerPauseResponse(paused, at_gate)`, which the four
      routes declare as their `response_model` and the clients return in place of a plain
      dict, so a caller reads `.at_gate`. Tests: unit `provisioning/compute/tests/unit/
      test_lease_lifecycle.py` and `service/tests/unit/services/
      test_fulfillment_convergence_gate.py` (idle: at the gate once paused; a timer cycle
      in flight keeps a paused watchdog off it until the cycle ends; an explicit cycle in
      flight does not), each cycle held on an event, no sleeps; application integration
      `test_system_api.py` `TestWorkerControls` through the typed client: pause, pause
      again after explicit cycles, and resume each answer the typed state (the harness
      starts no watchdog timer, so the in-flight case is the unit tests');
      `test_provisioning_client_endpoint_coverage.py` reads the typed response.
- [x] 13.2 `e2e-tests/tests/e2e/roles/helpers/compute_deal.py`: one helper per pause kind —
      storefront lifecycle loops (from `pause_storefront`), fulfillment convergence (from
      `convergence_paused`, which stops swallowing a failed pause), and the lease watchdog
      (new) — each pausing, waiting until every held loop reports itself at its gate,
      yielding, and resuming in a `finally`; their docstrings state the module-hold rule
      (D22).
      Done: `storefront_loops_held`, `fulfillment_convergence_held`, and
      `lease_watchdog_held`, context managers over one `_until_held`, which repeats the
      (idempotent) pause until its answer reports every held loop at its gate, bounded by
      `HOLD_TIMEOUT_SECONDS` (60) and polling every half second; a pause that raises fails
      the hold. The `finally` that resumes covers the wait as well as the module, so a hold
      that times out or fails also leaves its service running. The rule is stated once, in a comment above them (including that a module
      killed by `helm test`'s timeout runs no finaliser), and each docstring points to it. `pause_storefront` and
      `convergence_paused` are gone; `assert_storefront_loops_held` reads the hold back
      through system status for stages.
- [x] 13.3 Module-scoped lane fixtures built only on those helpers: `scenarios/vms/conftest.py`
      — Bob's loops, Alice's loops (Alice's admin client moves here from
      `test_multi_registry.py`), convergence, and the lease watchdog;
      `scenarios/bare_metal/conftest.py` — the storefront's loops (replacing
      `bare_metal_loops_held`), convergence, and the lease watchdog. API-credit scenarios
      hold nothing today, so that lane gains a fixture only when a module needs one (D22).
      Done, with one set of names across both lanes, so a module of either lane names
      the same holds and the source check knows one set: `storefront_loops_held` (Bob in the VM lane, the bare-metal storefront in its
      own), `fulfillment_convergence_held`, `lease_watchdog_held`, and in the VM lane
      `alice_loops_held`. `convergence_advanced_explicitly` and `bare_metal_loops_held`
      are gone. Alice's admin client and its two helpers (`_alice_url`,
      `_alice_publisher_trust`) moved to the VM conftest; `test_multi_registry.py` imports
      the helpers for its seller client.
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
      Done. Holds by module: the storefront's loops in all eleven; also Alice's in
      `test_multi_registry.py`; convergence and the lease watchdog in both typed and CLI
      VM deals and the bare-metal mock deal; convergence in `test_non_erc20_settlement.py`.
      The usefixtures mark is each module's first `pytestmark` entry. The shared stage is
      now `Stage00_LifecycleHeld` (its field `_lifecycle_held`), and each module's own
      Stage 00 (or its first stage) calls `assert_storefront_loops_held`, which counts
      only timed loops: a loop registered as a step alone reports no state, and the pause
      answer leaves it out too. Stages 10a and 11b (shared, and the CLI deal's own) and
      the bare-metal deal's 12d and 12e read the lease-watchdog hold back live through
      provisioning system status (`assert_lease_watchdog_held`, `checks.lease_watchdog ==
      "paused"`) instead of pausing or resuming it; none of them requests the hold
      fixture, so a module reusing them without the hold fails there rather than taking
      the hold mid-module. **Differed from D22**, which has these stages assert "the
      fixture's own state": that state is the pause answer frozen at setup, which the
      fixture yields only once it reads paused and at the gate, so asserting it could
      never fail; the live read can. The design's wording is left for closeout's
      promotion to settle. **Not exact to "listed first … released last":** pytest sets
      up autouse fixtures before marked ones, so the VM lane's autouse
      `ensure_storefront_resumed`, `reap_buyer_settle_subprocess`, and
      `release_reserved_resources` tear down after the holds. The first two touch no
      loop. The third now releases the storefront's reservations fleet-wide with its
      loops running again, where before this section the VM modules other than
      `test_vm_introduction.py` (whose own `held_loops` resumed them) never resumed Bob's
      loops and it ran with them paused. An admin release is an operation a live
      storefront takes with its loops running, and the next module's hold waits for every
      loop to reach its gate before its first stage, so this is left as it is; making the
      holds outlast it would mean ordering an autouse fixture after a marked one, which
      pytest offers no direct way to do. For triage.
- [x] 13.5 Source check (unit): `e2e-tests/tests/unit/test_scenario_holds.py` (new) walks
      every `tests/e2e/roles/scenarios/**/test_*.py` and the stage helpers with `ast` and
      fails, naming file and line, on any call of `admin_pause_lifecycle_loops`,
      `admin_resume_lifecycle_loops`, `pause_fulfillment_convergence`,
      `resume_fulfillment_convergence`, `pause_lease_watchdog`, `resume_lease_watchdog`, or
      a pause helper outside the hold helpers and lane conftests;
      `tests/unit/test_compute_deal_stages.py`'s shared-name and field checks follow
      Stage00's change (D22).
      Done (unit), wider than the task: every Python file under the roles' `scenarios/`
      and `helpers/` except the lane conftests, so drivers and other helpers are checked
      too, and `compute_deal.py` outside the three hold helpers' bodies. It flags any
      reference to a pause operation or hold helper (a call, or one passed as a callback),
      and any call whose arguments name a pause or resume route path
      (`lifecycle/pause`, `lease-watchdog/resume`, and the rest), so a raw HTTP post is
      caught as well as a typed-client call. Its own tests prove the checker names a
      planted direct pause, a hold-helper call, a resume, and a raw route post by file
      and line, that only the hold helpers' bodies are exempt, and that each lane conftest
      defines the hold fixtures over the helpers. `test_compute_deal_stages.py` needed no edit: it
      derives the shared names and fields from source, and passes over the renamed stage
      and field.
- [x] 13.6 Versions: `arkhai-compute-provisioning-contracts`,
      `arkhai-compute-provisioning-client`, the provisioning service, `arkhai-e2e-tests`;
      `make lock`.
      Contracts 0.9.1 → 0.10.0 (new model); client 0.7.0 → 0.8.0 (the pause methods return
      a model, not a dict: incompatible before 1.0); the provisioning service 0.17.3 →
      0.18.0 (its patch bump on this branch is too small for a new response field);
      `arkhai-compute-provisioning` 0.19.1 → 0.20.0, which the task omits but whose lease
      lifecycle gains `is_at_gate`; `arkhai-e2e-tests` is not bumped again: it is at 0.3.1
      from Sections 7 (0.2.1 → 0.3.0) and 8 (→ 0.3.1), already two bumps against
      `origin/dev` where `docs/development/RELEASING.md` allows one; collapsing them to
      0.3.0 is for triage. Floors raised where the new API is used: the client on contracts
      0.10.0, the service on contracts 0.10.0, `compute_provisioning` 0.20.0, and (dev) the
      client 0.8.0, and e2e-tests on contracts 0.10.0 and the client 0.8.0. `make lock`
      stops on that local directory before locking anything (Section 11's note), so it was run
      with `PROJECTS=` naming the eleven projects whose locks name a bumped package, and
      those eleven locks are committed; they also carry the environment's marker churn
      (Section 11's note). Twelve other locks the environment rewrote, naming no bumped
      package (`core/registry`, the API-credit service and storefront, `domains/vms/buyer`,
      and eight under `kit/`), are left uncommitted.
- [x] 13.7 **Verify.** `make test-e2e-unit` (unit); `make test-provisioning`; `make test`;
      `make check-packaging`. End-to-end: every lane's scenarios run on the holds
      (`make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal`, `test-e2e-apicredits`), and
      after `make helm-topology-check` Bob's loops report running (the maintainer's, 11.8).
      Results:
      - `make test-e2e-unit` (unit): 82 passed, among them `test_scenario_holds.py` over
        every scenario, helper, and lane conftest, and `test_hold_helpers.py` (new, added
        after review): against fake clients, a hold repeats its pause until every loop
        is at its gate, fails by its deadline (injected clock and sleep, no real wait),
        resumes after a failing module, resumes when its pause fails or the storefront
        reports its loops unpaused, and the read-backs skip step-only loops and read the
        lease watchdog's status. The resume-on-failed-hold test is the one that would
        fail with the wait outside the `try`, since nothing would have resumed.
      - `make test-provisioning`: the integration half (application integration) 488
        passed; the unit half 665 passed and 1 failed, the environment's
        `test_provisioning_bootstrap_dotenv_uses_environment_layer_without_dotenv_local`
        (Section 11's note), so `make test` stops there.
      - `make test`: every suite before `test-provisioning` passed (core, kits,
        provisioning contracts 59, client 50, `compute_provisioning` 233, ansible 92),
        then the stop above. Of the suites after it, those covering code or locks this
        section moved were run one by one: `make test-provisioning-adapter` (passed),
        `make test-bare-metal` (passed: 134, 449, 11, 40), `make test-storefront` (passed:
        1108 and 1 skipped, 457), `make test-vms-domain` (53 passed), `make test-compute` (5 passed).
        Not run: `test-provisioning-iac`, `test-registry`, `test-registry-client`,
        `test-vms-buyer`, `test-apicredits`, `test-deployment-packaging`, none of which
        reads a file or lock this section changed.
      - `make check-packaging`: stops at `check-uv-setup` on 51 problems, all under
        that local directory; its other stages, run one by one, report only it too
        (locks 37, Python version 25, project layout 28, architecture 22), the same counts
        as Section 11's note.
      - `make check-change`: fails only on comment hygiene's findings in that local directory and
        the one citation of a file Section 22 creates
        (`e2e-tests/tests/e2e/roles/helpers/introduction_stages.py`).
      **End-to-end:** not run here. The scenarios that exercise this section once
      deployed are the eleven held modules' markers: `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_buy`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `multi_registry`,
      `e2e_non_erc20_settlement`, `e2e_vm_introduction`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_publication`, and `e2e_bare_metal_introduction`; the API-credit lane
      holds nothing and is unchanged. The Helm topology check (11.8) is the maintainer's.

Section 13 notes (handoff):

- **Fresh-context checks**, two. The first found two defects, both fixed: a hold that
  failed to reach its gate left its service paused (the wait sat before the `try`), and
  the storefront read-back counted step-only loops, which report no state, so Alice's
  storefront without contact exchange would have failed it. Also fixed from it: Stage 10a's
  assertion of the frozen fixture answer, which could not fail (now a live status read,
  also in 11b, 12d, 12e); a test docstring naming the wrong event; the source check's
  whole-file exemption of `compute_deal.py`, now its hold helpers' bodies only, and its
  blindness to raw route posts; a docstring phrased as history; the 13.4 note's incomplete
  list of autouse fixtures. The second found no layering, hygiene, version, or spec
  defect; fixed from it: the conftests' lease-watchdog docstrings, the 13.3/13.4/13.6
  notes (the D22 departure, `test_vm_introduction.py`'s former resume, the e2e-tests
  double bump, the twelve uncommitted locks), the `# Listed first` comments, which now
  name the autouse exception, the hold-section header placed above Alice's client, the
  conftests now checked outside their hold fixtures, route strings caught outside call
  arguments, and the hold helpers' missing unit test. Declined: `_until_held`'s half-second
  poll, since the provisioning pause routes answer at once and offer no server-side wait;
  replacing `run_cycle` on the convergence watchdog's instance in its gate test, since the
  constructor offers no cycle seam and adding one for a test is outside this section; and
  a resume failure in the `finally` masking a failed hold, since Python chains it and
  pytest reports both.
- **For triage:** `release_reserved_resources` now tears down with the loops running
  (13.4); `arkhai-e2e-tests` carries two bumps (13.6); D22's "the fixture's own state"
  against the live read (13.4); the delta scenario "failed publication cycle" against the
  degraded start's completed step with a hold (Section 11's note).
- **Owed to closeout:** `TESTING.md`'s module-hold guidance replaces its
  `bare_metal_loops_held` passage (23's promotion item names it).
- **Seams:** a hold's gate state is the pause answer itself — the storefront's loop
  states, provisioning's new `at_gate` — so a hold needs no second read; the read-backs
  stages use are system status, which is what a module that forgot its hold would show.
- **Corrections after this section** (the repair pass of Section 11's corrections):
  - `make test` passed every suite through the API-credit Python suites, including the
    provisioning service's unit suite (666, with the dotenv test corrected) and integration
    suite (488), then stopped at `domains/apicredits`' middleware toolchain check, which needs
    Node 22.6 or later and that run's path lacked. On Node 22.23.1 the targets after it then
    passed one by one: `make test-apicredits` (its Python suites, and the TypeScript and Rust middleware
    ports), `make test-e2e-unit` (82), and `make test-deployment-packaging` (release tooling
    1092, with the timing-dependent test corrected; the Helm render on v4.3.0). A single
    uninterrupted `make test` on this commit has not been run.
  - `make check-packaging` and `make check-comment-hygiene` pass.
  - `make check-change` fails only on the citation of
    `e2e-tests/tests/e2e/roles/helpers/introduction_stages.py`, which Section 22 creates; its
    strict OpenSpec validation passes. A citation preceding its target is a plan issue for
    triage, not a reason to implement Section 22 early.
  - Of the items "For triage" above, two are now resolved and two stay open:
    - **Release order (resolved).** The VM lane's `ensure_storefront_resumed`,
      `reap_buyer_settle_subprocess`, and `release_reserved_resources` are no longer autouse;
      every VM scenario module, `test_pool_declared_offering_modes.py` included, lists them
      after its holds, so they finalise while the holds stand and the holds are released
      last. `e2e-tests/tests/unit/test_scenario_cleanup_order.py` (unit) reads the order pytest
      resolves (`pytest --setup-plan` over the real conftests and modules) and fails any module
      whose holds are released before a fixture that cleans up. Only a `close()` of the very
      object a fixture yielded is exempt from counting as cleanup. Over the unchanged modules
      it failed all eight held VM modules, naming the three fixtures; after the change, the
      e2e-tests unit suite passed (107). No deployed lane has run on the new order.
    - **Live read-back (resolved).** Design decision 22 now says stages assert a hold
      through live system status, which is stronger than the fixture's state at setup.
    - **The degraded start (partly open).** See Section 11's corrections.
    - **The double `arkhai-e2e-tests` bump (open).**

## 14. The delegate decides delivery terms

Delivers the backing delegate's two delivery-term operations (D5, D1;
`resource-pool-management` "Capacity backing is interpreted by one delegate"). Touches
`kit/resource-pools-contracts`.

- [ ] 14.1 `kit/resource-pools-contracts/src/market_resource_pools_contracts/backing.py`:
      `CapacityBacking.carry_delivery_terms(terms)` — backed returns the terms as given,
      unbacked returns none — and `delivery_term_constraints(terms)` — backed refuses a
      term that is not present, unbacked refuses one that is — beside
      `admissible_settlement`, on the delegate's own state as its other operations are. One
      presence rule: neither absent nor `None`; a string or collection non-empty; a boolean
      present as `True` or `False`. A refusal names every offending term (D5).
- [ ] 14.2 Tests in `kit/resource-pools-contracts/tests/unit/test_backing.py` (unit): each
      delegate's operations over present, absent, `None`, empty-string, empty-list, and
      `False` terms (D5).
- [ ] 14.3 Version: `arkhai-kit-resource-pools-contracts`; `make lock`.
- [ ] 14.4 **Verify.** `make -C kit test-resource-pools-contracts`; `make test`; `make
      check-packaging`. End-to-end: none alone; Sections 15–19 and 22's scenarios.

## 15. The bare-metal carrier validates delivery terms against its pool's backing

Delivers the listing and view models without host defaults, and the shared carrier's
validation by its pool's backing (D5, D6; `storefront-publication` "A bare-metal listing
carries delivery terms only when backed", "A bare-metal listing sells one whole unit";
`physical-provisioning` "A bare-metal publication view is built from its capacity
declaration"). Touches `domains/bare_metal/src/arkhai_bare_metal/` and the two bare-metal
storefront call sites of the reader.

- [ ] 15.1 `schema.py` `BareMetalListing`: `host_id` and `physical_host_id` optional;
      `access_methods` optional with its `["ssh"]` default removed; the validator checks
      structure and applies its backing's `delivery_term_constraints` to `host_id`,
      `physical_host_id`, and `access_methods` (D5).
- [ ] 15.2 `projections.py`: `BareMetalResourceProjection`'s `host_id`, `physical_host_id`,
      `available`, and `access_methods` optional, no default, structure checks only.
      `TrustedBareMetalResource` gains `capacity_backing`; given a label, its validator
      applies that delegate's `delivery_term_constraints` to the four terms beside the
      `pool_id` containment check; with none, no term check runs (D6).
- [ ] 15.3 `publication.py` `trusted_bare_metal_projection(*, site_id, projection,
      backings)`: each resource is validated with its pool's resolved label, or none where
      the pool is absent from `backings`; a violation refuses the generation as every
      malformed view does. `available_bare_metal_listings` passes on only the terms a view
      carries, and availability is read only for a backed pool (D6, D3).
- [ ] 15.4 `fixtures/publication_view.py`: `build_bare_metal_publication_view` builds an
      unbacked view; `validate_bare_metal_publication_view` takes the backing and validates
      through the carrier, so both sides of the boundary test against one rule (D6).
- [ ] 15.5 The storefront's two readers, `src/publication.py` `_classify_site` and
      `src/listing_source_check.py` `build_listing_source_check`, call `read_site_pools`
      before `trusted_bare_metal_projection` and pass `backings=reading.backings` (D6).
- [ ] 15.6 Tests: unit `domains/bare_metal/tests/test_schema.py`, `test_projections.py`, and
      `test_publication.py` — an unbacked listing or view with no terms valid and with any
      term refused, a backed one missing a term refused, `available=False` valid when
      backed, an unchecked pool absent from `backings`, no `access_methods` default, one
      inconsistent view refusing the generation. Library `tests/test_publication_cycle.py`
      and application integration `tests/test_http_negotiation.py` (through
      `StorefrontClient`) in the storefront: a generation whose backed view lacks
      `available` is held as `site_projection_refused` with the validation error, in a
      cycle and at an opening (D6).
- [ ] 15.7 Versions: `arkhai-bare-metal`, `arkhai-bare-metal-storefront`; `make lock`.
- [ ] 15.8 **Verify.** `make test-bare-metal`; `make test`; `make check-packaging`.
      End-to-end: `e2e_bare_metal_publication` and `e2e_bare_metal_mock_deal` show backed
      views and listings unchanged.

## 16. Resource views receive their pool's context and never fail the projection

Delivers the pool context in the contributed-view seam, the bare-metal view builder through
the delegate and the carrier, and `publication_view_problems` carried to storefronts (D3,
D4; `physical-provisioning` "Domains contribute their inventory views", "A bare-metal
publication view is built from its capacity declaration"). Touches
`provisioning/compute` (`compute_provisioning`), the provisioning service, the VM and
bare-metal provisioning adapters, `kit/site`, and `kit/site-client`.

- [ ] 16.1 `provisioning/compute/src/compute_provisioning/inventory_views.py`: a frozen
      pool-context type (pool ID, provider, resolved `PoolDeclarations`);
      `resource_views(declaration, *, pool)` returns the views it built and the problems,
      keyed by view identifier, that kept it from building one; the composer merges both
      and applies `_check_declared` to problem keys too. Export it.
      `provisioning/compute/pyproject.toml` declares `arkhai-kit-resource-pools-contracts`.
      Tests in `provisioning/compute/tests/unit/test_composition.py` (unit) (D4).
- [ ] 16.2 The provisioning service, `src/services/capacity_inventory.py`: one row-to-context
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
- [ ] 16.3 VM adapter `domains/vms/provisioning/adapter/.../inventory_views.py`: the new
      signature and return shape (D4).
- [ ] 16.4 Bare-metal adapter `domains/bare_metal/provisioning/adapter/.../inventory_views.py`
      `BareMetalPublicationViews.resource_views`: delivery terms through the pool's
      `carry_delivery_terms`; the view built through `TrustedBareMetalResource` with the
      pool's label; the no-host rule a problem for a backed pool only; a missing or invalid
      `allocation_mode`, a missing `physical_host_id`, missing access methods, or a
      private-looking key a problem rather than a raise. Its `pyproject.toml` declares
      `arkhai-kit-resource-pools-contracts`. Tests in its `tests/test_inventory_views.py`
      (unit): unbacked with and without a host; each problem; nothing raises (D3, D4, D5).
- [ ] 16.5 `kit/site/src/market_site/projections.py` `resource_pool_projection` copies
      `publication_view_problems` when present, uninterpreted, as it copies
      `publication_views`; `kit/site-client/.../fixtures/resource_pools.py`
      `build_projected_resource` and `validate_resource_pool_projection` carry and check it.
      Tests in `kit/site/tests/unit/test_projections.py` and
      `kit/site-client/tests/unit/test_resource_pool_fixture.py` (unit) (D4).
- [ ] 16.6 Versions: `arkhai-compute-provisioning`, the two adapters, the provisioning
      service, `arkhai-kit-site`, `arkhai-kit-site-client`; `make lock`.
- [ ] 16.7 **Verify.** `make test-compute-provisioning`, `make test-provisioning` (with the
      mock profile), `make -C domains test-provisioning-adapter`, `make -C kit test-site
      test-site-client`; `make check-architecture` (the new
      `compute_provisioning` → contracts edge is permitted); `make test`; `make
      check-packaging`. End-to-end: every bare-metal-lane scenario reads views through the
      changed resource pass.

## 17. One site-derivation log for both compute storefronts

Delivers the kit-owned site-derivation log, one status shape, and logging on change (D10;
`storefront-publication` "A compute storefront reports and logs its site derivation").
Touches `kit/capacity-publication`, `core/storefront`'s and `core/storefront-client`'s
status models, `domains/vms/listings`, and the VM and bare-metal storefronts.

- [ ] 17.1 `kit/capacity-publication/src/market_capacity_publication/cycle.py`: a
      site-derivation log keyed by publication source and site, recording a site's
      summary — `holds`, `refusals`, `reports`, each entry a reason code with its pool or
      Physical Resource and detail — only from a real cycle; logging an entry as a warning
      when it first appears and at info when it clears; a site absent until a cycle derives
      it. Export it. Tests in `kit/capacity-publication/tests/unit/test_cycle.py` (unit,
      `caplog`): appear, stand, clear, previews unlogged and unrecorded, two sources kept
      apart (D10).
- [ ] 17.2 VM: `domains/vms/listings/.../reconciler.py` loses the module dictionary,
      `_record_site_report`, and the `record_reports` flag, keeping the `reports=`
      out-parameter; `services/publication_loop.py` converts a real cycle's reports to
      entries (`regionless_pools` a `pool_region_missing` hold, `retired_pricing_keys` a
      report naming the keys, and so on) and records them in the log, which `container.py`
      holds and `services/system_service.py` serves; listing-source checks, capacity-event
      reconciliation, and failure actions record nothing (D10).
- [ ] 17.3 Bare metal: `src/publication.py`'s `SiteDerivation` and `PublicationDerivation`
      give way to the kit log, with its per-cycle log lines (`_classify_site`,
      `_hold_unbounded_pools`, `_hold_pools_without_clauses`, `_report_pools`) removed;
      `runtime.py`, `lifecycle_steps.py` (no clearing at cycle start: a cycle that fails
      before deriving a site leaves that site's last derivation, which status keeps
      reporting), `publication_composition.py`, and `models.py` follow (D10).
- [ ] 17.4 `core/storefront/.../models/system_models.py` and
      `core/storefront-client/.../models.py`: `publication_derivation` is the shared shape,
      its comment describing the entries rather than VM's categories (D10).
- [ ] 17.5 Tests: VM `tests/integration/test_publication_loop.py`,
      `test_pool_overrides_api.py`, `test_reconciler_projection.py`,
      `test_reconciler_derivation.py`, `_reconciler_cases.py`, and unit
      `tests/unit/test_reconciler.py` follow the shape and the out-parameter; bare metal
      `tests/test_http_system.py` and `test_publication_cli.py`. Application integration
      through `StorefrontClient` in both: a regionless pool reported under the site's
      `holds` as `pool_region_missing` alike in VM and bare metal; a preview changes
      nothing; a site absent before its first cycle; a listing-source check records nothing
      (D10).
- [ ] 17.6 Versions: `arkhai-kit-capacity-publication` (exact pins in both storefronts),
      `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-vms-listings`, both
      storefronts; `make lock`.
- [ ] 17.7 **Verify.** `make -C kit test-capacity-publication`; `make test-core`; `make
      test-vms-domain`, `make test-storefront`, `make test-bare-metal`; `make test`; `make
      check-packaging`. End-to-end: `e2e_compute_dynamic_listings`, `e2e_listing_shapes`,
      and `e2e_bare_metal_publication` read status after publication.

## 18. A candidate with no settlement option yields no listing; an open one closes or is held

Delivers the typed refusal, the classification of the admissible clauses' mechanisms, and the
runner's close hook, for VM and bare metal (D7; `storefront-publication` "A compute candidate
with no settlement option yields no listing", "Publication derives all ready settlement
options"). Touches `core/storefront`'s publication runner and sources, and the VM and
bare-metal storefronts.

- [ ] 18.1 `core/storefront/src/core_storefront/publication_runner.py`: a typed refusal a
      payload builder may return, stating whether every mechanism is ruled out by
      configuration; `publish_round` calls the source's close hook for such a refusal and
      otherwise reports it, leaving the listing as it is, as every other payload failure.
      `publication_sources.py` `PublicationSource` gains the close hook, with a default
      that closes nothing. Tests in `core/storefront/tests/unit/test_publication_runner.py`
      and `test_publication_sources.py` (unit) (D7).
- [ ] 18.2 Bare metal `src/publication_composition.py` `publication_payload_builder`: the
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
- [ ] 18.3 VM `services/listing_service.py` (`_admissible_settlement_terms`,
      `derive_listing`) keeps the readiness `publication_artifacts` returns and raises the
      typed refusal; `services/publication_loop.py` `_create_request`'s no-clause case is the
      same refusal; `_build_payload` records it with site, pool, and resource; VM's close
      hook finds the open listing by the candidate's derivation key and closes it through
      `_reconciliation_close` (D7).
- [ ] 18.4 Both storefronts' adapters (`arkhai_bare_metal/storefront_adapter.py`,
      `arkhai_vms/storefront_adapter.py`) pass the hook into the source (D7).
- [ ] 18.5 Tests: bare metal `tests/test_publication_cycle.py` (library) and VM
      `tests/integration/test_publication_loop.py` (application integration, through
      `StorefrontClient`): an open listing whose only mechanism is configured away closes as
      `no_settlement_option` and reopens under its identity when it builds again; one whose
      only mechanism's chain is unprobed is held with its terms; a pool override leaving no
      admissible clause closes; an unknown mechanism outside the admissible clauses holds
      nothing; a contact-only candidate whose origin has no contact yields no listing. Bare
      metal `tests/test_http_system.py`'s no-clause hold test becomes the close. VM
      `tests/unit/test_unbacked_settlement_options.py` (unit) follows the typed refusal (D7).
- [ ] 18.6 Versions: `arkhai-core-storefront`, `arkhai-bare-metal`, `arkhai-vms`, both
      storefronts; `make lock`.
- [ ] 18.7 **Verify.** `make test-core`; `make test-vms-domain`, `make test-storefront`,
      `make test-bare-metal`; `make test`; `make check-packaging`. End-to-end:
      `e2e_compute_dynamic_listings` and `e2e_bare_metal_publication`; no scenario closes a
      listing for configuration, and integration is the evidence.

## 19. Bare metal publishes unbacked listings

Delivers unbacked bare-metal derivation through the shared runtime, its recheck, and the
removal of the unbacked refusal (D1, D2, D3, D8, D11, D13, and D5's readers;
`storefront-publication` "Bare-metal publication derives unbacked listings", "Bare-metal
opening rechecks its listing against its source", "A bare-metal listing carries delivery
terms only when backed"; the removed "An unbacked pool yields no bare-metal listing";
`registry-discovery` "Compute listings publish their capacity backing"). Touches
`arkhai_bare_metal` and the bare-metal storefront.

- [ ] 19.1 Delete `SitePoolReading.unbacked`, `read_site_pools`'s unbacked branch, and
      `_report_pools`' `pool_unbacked` report (`src/site_reading.py`, `src/publication.py`)
      (D11).
- [ ] 19.2 `arkhai_bare_metal/storefront_publication.py`: an unbacked candidate's dictionary,
      source envelope, and comparison sets carry no host fields; availability is never
      read for it, so an enabled, shaped resource is a candidate and a disabled one is
      withdrawn; the region, asking-rate, and override holds apply unchanged (D2, D3).
- [ ] 19.3 `src/sqlite_client.py` `upsert_bare_metal_listing`: the source envelope omits
      absent host fields (D2).
- [ ] 19.4 The remaining readers of the delivery terms: `src/negotiation.py`'s admission
      refusal reads absent `access_methods` as no access method listed, so a bargaining
      round against an unbacked listing is refused with
      `bare_metal_access_method_not_listed` rather than raising; confirm each other reader
      (`negotiation_runtime.py`, `deal_controls.py`, `fulfillment_service.py`,
      `settlement_service.py`, `load_bare_metal_fulfillment_context`) is reached only
      through a stage that fulfils through capacity or after Section 20's refusal, and
      record any that is not as a defect to fix here (D5).
- [ ] 19.5 Recheck: `arkhai_bare_metal/inventory_guard.py` is unchanged; tests confirm an
      unbacked listing is refused only by its declaration (shape, region, Physical
      Resource, or its resource now in another pool, as `declared_mismatch`), and a site
      not held or unconfirmed refuses openings as retryable for either backing (D8).
- [ ] 19.6 Tests: unit `domains/bare_metal/tests/test_storefront_publication.py` and
      `test_inventory_guard.py` (the moved-pool case); library
      `tests/test_publication_cycle.py` — `test_an_unbacked_pool_yields_no_listing_and_is_reported`
      replaced by publication of an unbacked listing with `capacity_backing: unbacked`, no
      host fields, no `access_methods`, and only its admissible options; a withdrawn
      unbacked pool's listing closing on the next cycle (D13); application integration
      `tests/test_http_negotiation.py` through `StorefrontClient` — the unbacked recheck
      cases, and a bargaining round against an unbacked listing refused (D1, D2, D3, D8).
      Registry: `core/registry/tests/integration/test_capacity_backing_filter.py` already
      proves the exact filter; add a bare-metal listing case if it carries none.
- [ ] 19.7 Versions: `arkhai-bare-metal`, `arkhai-bare-metal-storefront`; `make lock`.
- [ ] 19.8 **Verify.** `make test-bare-metal`; `make test-core` if the registry test
      changes; `make test`; `make check-packaging`. End-to-end:
      `e2e_bare_metal_unbacked_introduction` (Section 22), and `e2e_bare_metal_publication`
      for backed supply unchanged.

## 20. A deal settled by introduction has no settlement or fulfillment, in both domains

Delivers the `completes_outside_settlement` stage declaration, the shared refusal in
`kit/storefront`, and the route order (D9; `storefront-publication` "A deal settled by
introduction has no settlement or fulfillment"). Touches `kit/storefront` and the VM and
bare-metal storefronts.

- [ ] 20.1 `kit/storefront/src/market_storefront_kit/introduction_routes.py` (new, importing
      only `.lifecycle_routes`): the shared refusal, given the accepted stage's
      `completes_outside_settlement` and the domain's reason text, raising a
      `LifecycleRouteError` of 409 for a settle request and 404 for a fulfillment read or
      teardown; exported from `__init__.py`. Tests in
      `kit/storefront/tests/unit/test_introduction_routes.py` (new, unit) (D9).
- [ ] 20.2 Stage tables: every seller stage in VM (`settlement_stages.py`:
      `VmAlkahestSellerStage`, `VmPaymentsSellerStage`, `VmContactSellerStage`) and bare
      metal (`settlement_stages.py` `SellerStage` and its subclasses, keyword-only;
      `settlement_composition.py` `SELLER_STAGES`) declares `completes_outside_settlement`
      with no default, contact exchange `True`, beside `settles_from_agreement` and
      `release_models`. API credits composes no introduction and no refusal, and its stage
      table is unchanged (the delta's "every compute domain"). VM's `VmContactSellerStage.start`
      no longer raises its own 409 (D9).
- [ ] 20.3 Routes: VM `controllers/settle_controller.py` `settle_escrow` applies the refusal
      after resolving the stage and before `stage.start`; bare metal `src/api.py` `settle`
      and `GET /api/v1/settle/{ref}/status` apply it after `accepted_stage` and before
      verification; bare metal's fulfillment status, access, result, and teardown routes
      check ownership and the accepted thread's terminal state in `_fulfillment_identity`,
      then resolve the stage, apply the refusal, and only then build the fulfillment
      service or load its context (D9).
- [ ] 20.4 Bare metal stops recording the reveal as settlement evidence: delete
      `ContactStage.record_reveal`, `runtime.py`'s `_RevealRecordingRuntime` and
      `_record_collected_introduction`, and pass the settlement runtime to the
      contact-exchange composition as VM does. Its only readers were the contact stage's
      own revalidation (now behind the refusal) and the fulfillment lifecycle's
      `settlement_verified` precondition, which an introduction deal never reaches; the
      contact-exchange kit's retention, deletion, and re-delivery read the introduction
      store. `verify_contact` and `revalidate_contact` go if nothing else calls them (D9).
- [ ] 20.5 Tests: VM unit `tests/unit/test_unbacked_settlement_options.py` (every stage
      declares the field; a stage omitting it cannot be constructed) and
      `test_settlement_start_authority.py`; VM application integration
      `tests/integration/test_introduction_origins.py` — settle answers 409. Bare metal
      application integration `tests/test_http_introductions.py` through the typed clients
      — settle and settle status answer 409, fulfillment status, access, result, and
      teardown 404, another buyer refused as for any deal, the settlement record still
      `accepted` after the reveal; an unbacked, host-less binding answering 404 without
      loading a context; `test_domain_runtime.py`, `test_selection_dispatch.py`,
      `test_app_composition.py` follow the stage table (D9).
- [ ] 20.6 Versions: `arkhai-kit-storefront` (exact pins in both storefronts), both
      storefronts; `make lock`.
- [ ] 20.7 **Verify.** `make -C kit test-storefront`; `make test-storefront`, `make
      test-bare-metal`; `make test`; `make check-packaging`. End-to-end:
      `e2e_vm_introduction` and `e2e_bare_metal_introduction`; the fulfillment 404 in
      `e2e_bare_metal_unbacked_introduction` (Section 22).

## 21. Bare metal's settlement commands sit under its own command

Delivers the bare-metal buyer's `settlement` group under `market bare-metal` and the core
buyer's refusal of a root command two domains register (D14; `buyer-orchestration` "Two
domains may not register one root command"). Touches `core/buyer` and
`domains/bare_metal/buyer`.

- [ ] 21.1 `core/buyer/src/core_buyer/cli.py` `build_app`: refuse at startup a root command
      name two installed domains register, naming the command and both domains, from each
      domain's registered names. Tests in `core/buyer/tests/unit/test_cli.py` (unit): two
      plugins registering `settlement` refuse; distinct names compose (D14).
- [ ] 21.2 `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py` `register_commands`
      adds `settlement` to `bare_metal_app` beside `request-introduction`; VM's root
      commands stay. Tests in `domains/bare_metal/buyer/tests/test_buyer_composition.py`
      (unit) (D14).
- [ ] 21.3 Versions: `arkhai-core-buyer` (the bare-metal buyer's exact pin),
      `arkhai-bare-metal-buyer`; `make lock`.
- [ ] 21.4 **Verify.** `make test-core`, `make test-bare-metal`, `make test-vms-buyer`; `make
      test`; `make check-packaging`. End-to-end: every VM-lane CLI scenario
      (`e2e_deal_buyer_cli`, `e2e_buy`, `e2e_vm_introduction`) runs with all three buyers
      installed, and Section 22's scenario uses the namespaced commands.

## 22. Unbacked bare-metal discovery reaches a usable introduction

Delivers the bare-metal Goal 7 evidence on shared introduction stages, VM's introduction
scenario moved onto them, and the bare-metal lane's mail sink (D14, D15, D12;
`storefront-publication` "Bare-metal publication derives unbacked listings";
`registry-discovery` "Compute listings publish their capacity backing"). Touches `e2e-tests/`,
the bare-metal lane's compose overlay, and the bare-metal storefront's development
configuration.

- [ ] 22.1 `e2e-tests/tests/e2e/roles/helpers/introduction_stages.py` (new): the stages VM's
      introduction scenario runs, as non-`Test*` stage classes over a driver protocol each
      domain supplies for supply seeding and its CLI verbs, as `compute_deal_stages.py`
      does; `scenarios/vms/test_vm_introduction.py` moves onto them with a VM driver. A
      source check beside `tests/unit/test_compute_deal_stages.py` holds both domains to the
      shared stages (D14).
- [ ] 22.2 The lane's mail sink: a `mailpit` service in `compose.bare-metal-local.yml`, so the
      existing `MAILPIT.API_URL` setting applies; `domains/bare_metal/storefront/storefront.dev.toml`
      configures `[Delivery]` with a `seller-mail` SMTP sink to it, as VM's
      `storefront.bob.toml` does; `e2e-tests/tests/unit/test_domain_stack_configuration.py`
      asserts both (D14).
- [ ] 22.3 `scenarios/bare_metal/test_bare_metal_unbacked_introduction.py` (new), marker
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
- [ ] 22.4 `e2e-tests/pyproject.toml` registers the marker; `e2e-tests/Makefile`'s
      `E2E_BARE_METAL_MODULE` includes it (D14).
- [ ] 22.5 Version: `arkhai-e2e-tests`; `make lock`.
- [ ] 22.6 **Verify.** `make test-e2e-unit`; `make -C e2e-tests test-e2e-bare-metal` and
      `test-e2e-vm` (system); `make test`; `make check-packaging`. End-to-end:
      `e2e_bare_metal_unbacked_introduction` and `e2e_vm_introduction`.

## 23. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order,
replacing the placeholder 2.1. It edits documentation only; a part needing code returns the
change to implementation.

- [ ] 23.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes, and read the
      comments and docstrings the change added (the diff from its branch point on `dev`)
      for fuzzier provenance: none names this change, a review, a round, or a migration,
      and none describes the removed preflights, init containers, `accepted_escrow_terms`,
      or unbacked refusal as history.
- [ ] 23.2 **Import placement.** Confirm every import each section added or touched is at
      module level, or has its reason beside it (a verified cycle or a deliberate lazy
      load) — in particular `compute_provisioning`'s and the bare-metal adapter's contracts
      imports, each storefront's chain-probe imports, and the e2e hold helpers. One that
      should move returns the change to implementation.
- [ ] 23.3 **Documentation compliance.** Re-check D1–D26 against
      `openspec/README.md#documentation-placement` and `AGENTS.md`'s "Documentation
      ownership": behaviour in the `spec.md` deltas, rationale in the architecture
      companions, repository-wide principles in `ARCHITECTURE.md`, nothing durable left only
      in `design.md`, no production code citing `openspec/changes`. D24 (stage events) and
      D25 (upgrade order) owe no document; D26's edits to other changes are on the branch;
      D15 is 2.2.
- [ ] 23.4 **Narrative compression.** Shorten Sections 3–22's completed-task notes to final
      behaviour, material validation evidence, deferred work, and destinations; move any
      alternatives or debugging narrative into `design.md` first. 1.1–1.15 and 2.2 stay as
      they are.
- [ ] 23.5 **Roadmap currency.** `docs/development/ROADMAP.md`: Goal 7's "Current state"
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
      by closeout (round 1's triage, 85 F17). Name each in the design-promotion record.
- [ ] 23.6 **Campaign index currency.** `openspec/changes/README.md`: this change's row and
      notes current, the Goal 7 campaign graph naming it current, and the two-seller scenario
      still recorded as unowned; other rows' `Depends on` are left to archive cleanup; `make
      check-change-index` passes. Name the update in the design-promotion record.
- [ ] 23.7 **Packaging.** `make check-packaging` passes with every failure resolved; `make
      check-architecture-change CHANGE=unbacked-bare-metal-listings` reports no exception or
      override row this change owns. `make check-agent-skills` is not owed: the change
      touches nothing under `.agents/`, `.claude/`, or `.codex/`.
- [ ] 23.8 **End-to-end pipeline.** Record a passing pipeline run of all three lanes on the
      closeout commit, its result, and the scenarios that exercise the change: VM lane
      `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_alkahest_escrow_codecs`, `e2e_non_erc20_settlement` (settlement against the plan,
      buyer derivation, pinned openings, readiness kinds, the chain probe),
      `e2e_compute_dynamic_listings` and `e2e_listing_shapes` (site derivation),
      `e2e_vm_introduction` (shared introduction stages, the settle refusal); API-credit lane
      `e2e_credits_deal` and `e2e_credits_payment_deal` (`listing-seed`, the CLI through the
      typed client); bare-metal lane `e2e_bare_metal_unbacked_introduction` (unbacked
      discovery reaching a usable introduction; a rate-bounded query returning backed and
      unbacked bare-metal listings together, carried from `publish-indicative-listing-rates`
      7.13; the backing filter; the fulfillment 404), `e2e_bare_metal_introduction`,
      `e2e_bare_metal_publication`, and `e2e_bare_metal_mock_deal`; every lane on the module
      holds. Record the local Helm topology evidence of D14 — `make helm-topology-up` and
      `make helm-topology-check` on the change's commit, Bob's lifecycle loops running after
      the check, no init containers on the VM storefront — run by the maintainer, or record
      it unrun. A pipeline that cannot run for a reason unrelated to the change is recorded
      as a blocker naming its cause and owner, and what it gates as unrun.
- [ ] 23.9 **Promotion.** Write the permanent documents and complete the design-promotion
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
        `startupProbe` assertions.
      - `openspec/specs/storefront-publication/architecture.md`: "Bare-metal listing
        shapes" — unbacked candidates, delivery terms, the one-unit commitment;
        "Reconciliation" — the recheck on the held projection and the no-option close or
        hold; "Settlement option reconciliation" — classification of the admissible clauses'
        mechanisms, and its release-condition paragraph rewritten (conditions derived only
        under a ready Alkahest; an undeliverable model unready rather than a startup
        refusal); "Autonomous publication" — the site-derivation log.
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
        passage; `docs/seller-quickstart.md`'s `publication_derivation` passages.
      - The `spec.md` files of the ten capabilities the deltas cover are written by the
        archive (23.11) and named in the record. `openspec/specs/README.md` gains nothing:
        no new capability or companion.
- [ ] 23.10 **Documentation citations.** `make check-doc-citations
      CHANGE=unbacked-bare-metal-listings` after promotion, every match resolved; then
      `openspec validate unbacked-bare-metal-listings --strict`.
- [ ] 23.11 **Archival.** Last: `openspec archive unbacked-bare-metal-listings -y`, merging
      the deltas into `openspec/specs/` (no `--skip-specs`: no `spec.md` was promoted by
      hand); the change's row then links the archive directory.

## Design promotion record

Completed at closeout (23.9).

| Accepted decision | Permanent location |
|---|---|
