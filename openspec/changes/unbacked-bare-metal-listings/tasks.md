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
      (`kit/storefront/tests/unit/test_zz_sdk_construction_probe.py`). It connects to a
      refused loopback port, so it is not a pure unit test, and its name is left from a
      scratch probe; this session could neither rename nor move files (`mv` and `git mv`
      were refused). **For triage:** move it to `tests/integration/` under a permanent name.
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

## 6. API credits publishes once its dependencies answer

Delivers the `listing-seed` loop step, the create route's retryable refusal, and the
storefront CLI's listing commands as clients of the running storefront (D19;
`storefront-publication` "API-credit listing creation waits for or names an unreachable
mechanism"). Touches the API-credit storefront.

- [ ] 6.1 `src/startup.py`: the configured seed no longer runs in startup. It is the
      `listing-seed` loop and lifecycle step (`lifecycle_steps.py`): it waits, logging
      nothing at error level, while the credits service cannot be reached for its quota
      registration or a mechanism its clauses use is unknown (every blocker a reachability
      blocker); gives up, logging once, on a configuration failure; and finishes once the
      listing exists, created or found (D19).
- [ ] 6.2 `services/listing_service.py` and `controllers/listings_controller.py`: a create
      refused only because a mechanism is unknown raises a distinct error the route answers
      with 503, naming the unreached mechanism and that the create can be retried; a
      configuration refusal stays a 400 with its blocker codes (D19).
- [ ] 6.3 `listing_publication.py`: `ApiCreditListingClient` and
      `SyncApiCreditListingClient` gain a list method over the listing route, in both
      variants. `cli.py` `publish` and `listings` call the running storefront through them
      and no longer build services or open the database in their own process (D19).
- [ ] 6.4 Tests: unit `tests/unit/test_listing_publication_client.py` (parity of the new
      method) and `tests/unit/test_listing_publication_entry_points.py` (inverted: the CLI
      uses the typed client); unit `tests/unit/test_startup_seed_quota.py` moved onto the
      step — waits on an unreachable credits service and on an unprobed chain, gives up on
      configuration, finishes once found; application integration
      `tests/integration/test_publish_reconcile.py` through `ApiCreditListingClient` — a
      create against an unprobed chain answers 503 naming Alkahest, a configuration refusal
      400, and a stepped probe then lets the same create succeed; `tests/unit/test_server_composition.py`
      lists `listing-seed` (D19).
- [ ] 6.5 Versions: `arkhai-apicredits-storefront`; `make lock`.
- [ ] 6.6 **Verify.** `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` run on the seeded
      listing, so their passing proves the step publishes once dependencies answer.

## 7. Settlement verifies against the plan committed at acceptance

Delivers settle verification, and every other post-acceptance reader, on the committed
`settlement_plan` (D16; `settlement-servicing` "Settlement verifies against the accepted
plan"). Touches `kit/alkahest`, `core/storefront`'s settle models, `core/storefront-client`,
and the three storefronts.

- [ ] 7.1 `kit/alkahest/src/market_alkahest/escrow_verification.py`: a verification form
      taking the accepted obligation (from the committed plan, through
      `escrow_terms_from_settlement_plan`) rather than a listing, sharing the codec lookup
      and the comparison, expiry included, with the listing form; registered as the
      settlement verifier the domains reach. Tests in
      `kit/alkahest/tests/unit/test_native_escrow_verification.py` (unit): a plan whose
      listing has since changed release policy, wallet, or address book verifies; an escrow
      differing from the plan does not (D16).
- [ ] 7.2 VM `settlement_composition.py` `prepare_vm_settlement` verifies and builds its
      obligations from `thread["settlement_plan"]`, as `failure_actions.py`'s refund does;
      `settlement_stages.py` `AlkahestStage.recover_evidence` re-derives from the plan, not
      the evidence's stored `order` (D16).
- [ ] 7.3 VM heartbeat and interrupt: `controllers/deals_controller.py` reads the cadence
      from the committed plan's `service_terms.heartbeat.interval_seconds`, and a plan with
      no heartbeat term (a deal that is not oracle-gated) reports no expected heartbeat;
      `controllers/admin_controller.py` `_deal_is_interruptible` reads the plan's
      `interruptible` term, never the current listing or chain address configuration (the
      listing is still loaded for its capacity binding) (D16).
- [ ] 7.4 Bare metal `settlement_stages.py` `verify_alkahest` and `revalidate_alkahest`
      verify against the committed plan. Acceptance builds its plan from the listing record
      the opening authorized: today every round reloads the listing and `build_artifacts`
      re-authorizes against the reloaded record, and no snapshot of the opening's record is
      kept, so `negotiation_runtime.py`'s `persist_opening` persists the authorized record
      with the opening and acceptance (`build_artifacts`, force-accept included) builds from
      it (D16).
- [ ] 7.5 VM administrator dry-run verify: `VerifyEscrowRequest`
      (`core/storefront/.../models/settle_models.py`) gains `negotiation_id`, as
      `EvaluateSettleRequest` has, since the escrow row exists only at settle;
      `services/admin_settle_service.py` loads that accepted deal's committed plan and
      verifies against it with the 7.1 form; `storefront_client`'s async and sync
      `verify_settle` send it; bare metal's twin (`deal_controls.py`
      `settlement_admin_routes.verify`, `BareMetalVerifyEscrowRequest`) does the same; e2e
      Stage07b (`helpers/compute_deal_stages.py`, `vms/test_full_deal_buyer_cli.py`) names
      the negotiation (D16).
- [ ] 7.6 API credits `settlement_stages.py` `_prepare_alkahest_settlement` verifies and
      builds against the committed plan rather than `order` (D16).
- [ ] 7.7 Tests: VM `tests/unit/test_settlement_composition.py`,
      `unit/services/test_admin_settle_service.py`, `unit/test_interrupt_deal_admin.py`,
      `unit/test_heartbeat_gated_listings.py` (unit); VM
      `tests/integration/test_settle_controller.py` and `test_deals_controller.py`
      (application integration through `StorefrontClient`): a deal whose listing changed
      release policy after acceptance settles; the dry-run and the real verification agree;
      the interrupt and heartbeat follow the plan. Bare metal `tests/test_http_settlement.py`
      and `tests/test_deal_controls.py` (application integration): a listing refreshed after
      the opening does not change the accepted plan, and settle verifies against it. API
      credits `tests/unit/test_settlement_fulfillment.py` (unit) (D16).
- [ ] 7.8 Versions: `arkhai-kit-alkahest`, `arkhai-core-storefront`,
      `arkhai-core-storefront-client` (and the exact pin in `provisioning/compute/service`),
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
- [ ] 7.9 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make
      test-storefront`, `make test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`;
      `make test`; `make check-packaging`. End-to-end: `e2e_deal` and
      `e2e_deal_buyer_cli` (Stage07b's dry-run and settle), `e2e_non_erc20_settlement`,
      `e2e_bare_metal_mock_deal`, and `e2e_credits_deal` settle against the plan.

## 8. An escrow proposal naming no escrow contract is refused

Delivers the refusal at the seller guard and at `kit/alkahest`'s materialization chokepoint,
and removes every unpinned branch (D18; `negotiation-protocol` "An Alkahest obligation uses
exactly the release condition its listing authorizes"; `storefront-publication` "Complete
bare-metal seller lifecycle"). Touches `kit/policy`, `kit/alkahest`,
`core/storefront-client`, the three storefronts' pricing, and the tests and scenarios that
opened unpinned.

- [ ] 8.1 `kit/policy/src/market_policy/scalar_policies.py`: `escrow_shape_guard` refuses an
      escrow proposal whose escrow address is empty or zero with a named reason, and still
      passes a negotiation carrying no escrow proposal; `_accepted_escrow_for_proposal`
      loses its zero-address case. Tests in `kit/policy/tests/unit/test_escrow_shape_guard.py`
      (unit): the "unpinned escrow" case inverted (D18).
- [ ] 8.2 `kit/alkahest`: `proposals.py` `authorize_escrow_proposal` and `alkahest.py`
      `materialize_escrow_terms_from_proposal` refuse an unpinned proposal through the
      existing `ReleaseConditionError` family, which every caller already translates, with
      its own code; `escrow_verification.py`'s default-kind branch goes. Tests in
      `test_release_authorization.py` and `test_native_escrow_verification.py` (unit) (D18).
- [ ] 8.3 First-entry pricing goes: VM `storefront_round.py` (`_selected_option`,
      `_seller_reference_amount`) and `domains/vms/listings/.../pricing.py`; API credits
      `pricing.py`'s first-escrow and first-option fallbacks; bare metal
      `negotiation_runtime.py` `_priced_acceptance`'s chain-blind fallback (D18).
- [ ] 8.4 `core/storefront-client/src/storefront_client/client.py` `_negotiate_new_proposal`
      no longer fills a zero escrow address or token for an escrow opening, which would
      build exactly the refused shape: an escrow opening requires its escrow address, and a
      caller with no escrow uses the selection-only opening. Tests in
      `core/storefront-client/tests/test_negotiate_new_payload.py` (unit) (D18).
- [ ] 8.5 Callers that opened unpinned move to a pinned or selection-only opening: VM
      `tests/unit/test_escrow_fields_policy.py`, `unit/test_escrow_verification.py`,
      `integration/test_negotiate_controller.py`, `integration/test_listings_api.py`; bare
      metal `tests/test_http_negotiation.py` (its `_UNPINNED` cases become refusals); e2e
      `helpers/compute_deal_stages.py` (the opening and the evaluate-negotiate dry-run),
      `vms/test_full_deal_buyer_cli.py`, `vms/test_multi_registry.py`,
      `vms/test_non_erc20_settlement.py`, `bare_metal/test_bare_metal_mock_deal.py` (D18).
- [ ] 8.6 Application integration through `StorefrontClient`: in VM's
      `tests/integration/test_negotiate_controller.py` and bare metal's
      `tests/test_http_negotiation.py`, an unpinned escrow opening is refused naming the
      reason, with the seller's guard composed and with it omitted (the kit chokepoint
      refuses it) (D18).
- [ ] 8.7 Versions: `arkhai-kit-policy` (and the exact pin in `kit/negotiation-runtime`),
      `arkhai-kit-alkahest`, `arkhai-core-storefront-client`, `arkhai-vms-listings`,
      the three storefronts, `arkhai-e2e-tests`; `make lock`.
- [ ] 8.8 **Verify.** `make -C kit test-policy test-alkahest test-negotiation-runtime`;
      `make test-core`; `make test-vms-domain`, `make test-storefront`, `make
      test-bare-metal`, `make test-apicredits`; `make test-e2e-unit`; `make test`; `make
      check-packaging`. End-to-end: `e2e_deal`, `multi_registry`,
      `e2e_non_erc20_settlement`, and `e2e_bare_metal_mock_deal` open
      pinned and negotiate as before.

## 9. A buyer funds only what it derives

Delivers the accept reply without `accepted_escrow_terms`, the buyer's own derivation checked
against the seller's plan on every branch and on resume, and release conditions in the
run-log (D17; `negotiation-protocol` "The accept reply carries no escrow terms";
`buyer-orchestration` "A buyer funds only what it derives"). Touches `kit/alkahest`, `core`
(`market_core`), `core/storefront`, `core/buyer`, the VM and API-credit buyers, and bare
metal's reply.

- [ ] 9.1 Producers: `kit/alkahest/.../proposals.py` `accepted_escrow_artifacts_from_proposal`
      stops building the field; `plans.py`'s and `core/src/market_core/schemas.py`'s legacy
      coercions (`_coerce_legacy_escrow_terms`, `_coerce_legacy_terms_list`) go, and
      `escrow_terms_to_settlement_obligation` and `core/buyer`'s `deal_helpers.py` build the
      obligation explicitly rather than through them; `core_storefront/models/negotiation_models.py`
      `NegotiateNewResponse` and `NegotiateContinueResponse` lose the field and its
      docstring; bare metal's `_ESCROW_RESPONSE_ARTIFACTS` drops it (D17).
- [ ] 9.2 `core/buyer`: `negotiation_client.py` (`NegotiationOutcome`,
      `parse_accepted_terms_from_reply`, `ResumeState`, the reply parse and resume, the three
      accept branches), `orchestration.py` (`_settle_one` always derives through
      `build_escrow_terms`; the negotiate hook), and `deal_helpers.py` (`DealContext`,
      `load_deal_context` and its back-fill, `NegotiationResumePoint`) stop reading the
      field. `AdvertisedPlanValidatorFn` runs on every branch that receives a plan and on
      resume, not only the selection branch; its callable receives what a derivation needs
      (the accepted proposal or selection, the agreed amount and duration), and
      `core/buyer` gains no import of `kit/alkahest` (D17).
- [ ] 9.3 The run-log: `negotiation_completed` and both negotiate CLIs' `run_ended` record
      the selected listing's advertised release conditions; `load_deal_context` and the
      resume point read them; a resumed run derives from the Agreement's selected option and
      those conditions and checks any recorded seller plan against them; a run-log accepted
      without recorded conditions and not yet funded is refused before funding, naming that
      a new run is needed; a run whose escrow exists resumes (D17).
- [ ] 9.4 VM buyer (`settlement_stages.py` `enrich_deal`, `_accepted_proposal_chain`,
      `_resume_alkahest`, `_refuse_without_release_condition`; `escrow_client.py`;
      `escrow_cli.py`; `buyer_client.py`; `negotiate_cli.py`; `buy_cli.py`;
      `buy_orchestrator.py`) and API-credit buyer (`settlement_stages.py`
      `AlkahestBuyerStage.enrich`, `settle_cli.py`, `negotiate_cli.py`, `buyer_client.py`,
      `buy_cli.py`, `escrow_client.py`) stop reading the field; API credits supplies a plan
      validator over `kit/alkahest`'s `validate_selected_escrow_plan` as VM does (D17).
- [ ] 9.5 Tests (unit): `core/buyer/tests/unit/test_settlement_acceptance.py`,
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
- [ ] 9.6 Versions: `arkhai-kit-alkahest`, `arkhai-core`, `arkhai-core-storefront`,
      `arkhai-core-buyer` (and the exact pin in `domains/bare_metal/buyer`),
      `arkhai-vms-buyer`, `arkhai-apicredits-buyer`, the three storefronts; `make lock`.
- [ ] 9.7 **Verify.** `make -C kit test-alkahest`; `make test-core`; `make test-vms-buyer`,
      `make test-apicredits`, `make test-storefront`, `make test-bare-metal`; `make test`;
      `make check-packaging`. End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, and
      `e2e_credits_deal` fund through the buyer's own derivation, and
      `e2e_bare_metal_mock_deal` through the typed client.

## 10. The provisioning service refuses unserved providers and signs failures

Delivers the stored-provider startup refusal and signed 500s after authentication (D23;
`resource-pool-management` "A service refuses to start while a stored pool names an unserved
provider"; `physical-provisioning` "A failure after authentication is answered signed").
Touches `kit/resource-pools`, the provisioning service, and `kit/site`.

- [ ] 10.1 `kit/resource-pools/src/market_resource_pools/service.py`: a stored-provider
      check beside `stored_declaration_problems` naming each pool and the provider no
      registered handler serves; the provisioning service's `verify_pool_declarations`
      startup step (`src/app_runtime.py`) refuses on it, beside the invalid-declaration
      refusal. Tests: `kit/resource-pools/tests/integration/test_resource_pool_service.py`
      `TestStoredDeclarations` (library integration);
      `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`
      (application integration): a stored pool naming an unregistered provider refuses
      startup naming it (D23).
- [ ] 10.2 `src/middleware/auth.py` `ProvisioningAuthMiddleware.dispatch`: a route failure
      after authentication is logged and answered as a signed 500 with a fixed,
      non-revealing detail, following VM's `admin_identity.py`, and recorded as the
      request's outcome so an exact retry replays the same signed answer. Tests:
      `tests/unit/middleware/test_auth.py` (unit) and an application-integration case
      through `ProvisioningClients`: the typed client receives a signed 500, not a
      response-authentication error, and an exact retry gets the same answer rather than
      "in progress" (D23).
- [ ] 10.3 `kit/site/src/market_site/auth.py` `SiteAuthMiddleware.dispatch`: the same signed
      500, recording nothing; an exact retry of a retry-safe route runs again, and of an
      unsafe one is refused as today. Tests:
      `kit/site/tests/integration/test_site_auth_middleware.py` (library integration);
      `domains/apicredits/service/tests/integration/test_credits_signed_roundtrip.py`
      (application integration through the typed client) (D23).
- [ ] 10.4 Versions: `arkhai-kit-resource-pools`, `arkhai-kit-site`, the provisioning
      service, the API-credits service; `make lock`.
- [ ] 10.5 **Verify.** `make -C kit test-resource-pools test-site`; `make
      test-provisioning`; `make test-apicredits`; `make test`; `make check-packaging`.
      End-to-end: none exercises an unserved provider or a route failure, and none is owed;
      every lane's provisioning traffic passes through the changed middleware.

## 11. Storefronts start degraded rather than waiting on their dependencies

Delivers the VM storefront chart without dependency-waiting init containers and with a
`startupProbe`, and the VM and API-credit storefronts without their in-process dependency
preflights (D20; `deployment-state` "A deployment does not wait on a service's
dependencies"). Touches `helm/charts/storefront`, `helm/charts/bare-metal-storefront`'s
render test, `helm/scripts/test-render.sh`, the VM and API-credit storefronts' startup and
settings, a cookbook, and the `deployment-state` delta.

- [ ] 11.1 `helm/charts/storefront/templates/deployment.yaml`: delete the `initContainers`
      block (`wait-for-rpc`, `wait-for-registry`); add a `startupProbe` mirroring
      `helm/charts/bare-metal-storefront/templates/deployment.yaml`'s (`/health`, port
      `http`); drop the liveness and readiness `initialDelaySeconds` the startup probe
      replaces, as bare metal has none; the comment beside them states the current rule.
      `templates/_helpers.tpl`: delete `storefront.usesInternalRegistry` and the unused
      `rpc.url` and `rpc.wsUrl` helpers (D20).
- [ ] 11.2 Render tests (`docs/development/TESTING.md` "Chart Render Tests"):
      `helm/charts/storefront/tests/test_render.py` replaces every `wait-for-*` assertion
      with one test, over every fixture, that no container named `wait-for-` renders and
      that `startupProbe` does; the tests that a chain's RPC is or is not waited for go.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts its `startupProbe`.
      `helm/scripts/test-render.sh`: the EVM fixture's chain-readiness assertion goes and
      its `CHAIN_ID|RPC_URL` check stays (D20).
- [ ] 11.3 VM `src/startup.py`: delete `_preflight_provisioning` and its step, and correct
      the step list's docstring; `settings.toml` and `groups/config.py`'s template lose
      `[seller.provisioning].fail_on_unreachable` and `preflight_timeout`; both join
      `retired_settings.py`'s removed settings, so a configuration stating either is
      refused by key as every retired setting is; regenerate the values schema with `make
      helm-values-schema` and update `tests/unit/test_values_schema.py` and
      `tests/integration/test_publishable_startup.py` (D20).
- [ ] 11.4 API credits `src/startup.py`: delete `_preflight_credits_service` and its call;
      the refusal of an unset `[credits].service_url` stays, run with the storefront's other
      configuration refusals. `settings.toml`, `storefront.credits.toml`, and
      `docs/cookbooks/vllm-apicredits-seller.md` lose `[credits].fail_on_unreachable` and
      `preflight_timeout`; the storefront refuses both by key, as it refuses
      `claims_sweep_interval`. `tests/unit/test_server_composition.py` stops patching the
      preflight (D20).
- [ ] 11.5 Degraded start (application integration through the typed clients): VM
      `tests/integration/test_degraded_startup.py` (new), modelled on bare metal's
      refused-registry case in `tests/test_http_system.py` — a storefront whose registry,
      provisioning site, and chain RPC all refuse connections starts, `/health` answers, and
      `StorefrontClient.get_system_status` reports the registry check failing, the site's
      projection families unknown, Alkahest unready with `alkahest.chain_unreachable`, and
      the publication cycle failed, with no listing closed; once the chain answers, a stepped
      `alkahest-chain-probe` makes Alkahest ready without a restart. API credits
      `tests/integration/test_lifecycle_status.py`: it starts with its credits service
      unreachable and `listing-seed` waits (D20, D19).
- [ ] 11.6 The `deployment-state` delta: the permanent requirement "A storefront chart
      passes service configuration through" still permits a chart to wait for a configured
      chain's RPC or the internal registry before the storefront starts, which D20 and the
      delta's added requirement forbid. Add to `specs/deployment-state/spec.md` a MODIFIED
      block for that requirement, copied whole with that example removed, so the archive
      leaves no contradiction; `openspec validate unbacked-bare-metal-listings --strict`
      passes (D20; a correction of the delta to the reviewed decision).
- [ ] 11.7 Versions: `arkhai-vms-storefront`, `arkhai-apicredits-storefront`; the chart
      versions per the charts' own convention; `make lock`.
- [ ] 11.8 **Verify.** `make -C helm test-render` (chart render); `make test-storefront`,
      `make test-apicredits`; `make test`; `make check-packaging`. End-to-end: every VM-lane
      and API-credit-lane scenario starts on the changed startup. The local Helm topology
      run of D14 — `make helm-topology-up` and `make helm-topology-check` on this round's
      commit, no init containers on the VM storefront — is the maintainer's at this round's
      validation, recorded unrun if not done.

## 12. Helm test pods carry no workload selector label

Delivers a test-labels helper in every chart and a topology render assertion (D21;
`deployment-state` "Helm test pods carry no workload selector labels"). Touches
`helm/charts/*` and `helm/tests/test_release_topology.py`.

- [ ] 12.1 A `<chart>.testLabels` helper in each chart's `templates/_helpers.tpl` —
      `registry`, `storefront`, `provisioning`, `e2e-tests`, `validate-contracts`,
      `bare-metal-storefront` — carrying chart, version, managed-by, instance, and
      `app.kubernetes.io/component: test`, never `app.kubernetes.io/name` (D21).
- [ ] 12.2 Each chart's test Pod takes it, under `helm/charts/`:
      `registry/templates/tests/registry-environment-test.yaml`,
      `storefront/templates/tests/storefront-environment-test.yaml`,
      `provisioning/templates/tests/provisioning-smoke-test.yaml`,
      `helm/charts/e2e-tests/templates/tests/e2e-deal-test.yaml`,
      `validate-contracts/templates/tests/chain-environment-test.yaml`, and
      `bare-metal-storefront/templates/tests/health-test.yaml`, which also gains
      `"helm.sh/hook-delete-policy": before-hook-creation` as the others have (D21).
- [ ] 12.3 `helm/tests/test_release_topology.py` (chart render): over both topology releases,
      parse each Deployment's `spec.selector.matchLabels` and each Pod annotated
      `helm.sh/hook: test` in either quoting; assert no such Pod carries all of any
      Deployment's `matchLabels`, and each carries `component: test` and no `name`.
      `helm/charts/bare-metal-storefront/tests/test_render.py` asserts the delete policy
      (D21).
- [ ] 12.4 **Verify.** `make -C helm test-render`; `make test`; `make check-packaging` if a
      chart version changed. End-to-end: the Helm topology check of 11.8 runs every test Pod;
      no compose scenario covers chart labels, and none is owed.

## 13. Scenarios hold shared services for the whole module

Delivers one hold mechanism for every lane (D22; `test-compatibility` "Scenarios hold shared
services for the whole module"). Touches `e2e-tests/` and, for the gate state a hold waits
on, the provisioning service's two pause routes.

- [ ] 13.1 The provisioning service's fulfillment-convergence and lease-watchdog pause
      routes answer whether the loop is at its gate (waiting on its resume event with no
      cycle in flight), as the storefront's lifecycle pause reports each loop's gate state:
      the delta requires a hold to wait until each held loop reports itself paused at its
      gate, and these routes report only the flag. `src/controllers/system_controller.py`
      and the two watchdogs expose it; `compute_provisioning_contracts/routes.py` and the
      async and sync `compute_provisioning_client` methods return it. Tests: unit for each
      watchdog's gate state with a cycle in flight and idle; application integration per
      route through `ProvisioningClients`. The proposal's Impact "Wire" bullet names the
      field (D22).
- [ ] 13.2 `e2e-tests/tests/e2e/roles/helpers/compute_deal.py`: one helper per pause kind —
      storefront lifecycle loops (from `pause_storefront`), fulfillment convergence (from
      `convergence_paused`, which stops swallowing a failed pause), and the lease watchdog
      (new) — each pausing, waiting until every held loop reports itself at its gate,
      yielding, and resuming in a `finally`; their docstrings state the module-hold rule
      (D22).
- [ ] 13.3 Module-scoped lane fixtures built only on those helpers: `scenarios/vms/conftest.py`
      — Bob's loops, Alice's loops (Alice's admin client moves here from
      `test_multi_registry.py`), convergence, and the lease watchdog;
      `scenarios/bare_metal/conftest.py` — the storefront's loops (replacing
      `bare_metal_loops_held`), convergence, and the lease watchdog. API-credit scenarios
      hold nothing today, so that lane gains a fixture only when a module needs one (D22).
- [ ] 13.4 Every module that paused or resumed takes its holds with `usefixtures`, listed
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
- [ ] 13.5 Source check (unit): `e2e-tests/tests/unit/test_scenario_holds.py` (new) walks
      every `tests/e2e/roles/scenarios/**/test_*.py` and the stage helpers with `ast` and
      fails, naming file and line, on any call of `admin_pause_lifecycle_loops`,
      `admin_resume_lifecycle_loops`, `pause_fulfillment_convergence`,
      `resume_fulfillment_convergence`, `pause_lease_watchdog`, `resume_lease_watchdog`, or
      a pause helper outside the hold helpers and lane conftests;
      `tests/unit/test_compute_deal_stages.py`'s shared-name and field checks follow
      Stage00's change (D22).
- [ ] 13.6 Versions: `arkhai-compute-provisioning-contracts`,
      `arkhai-compute-provisioning-client`, the provisioning service, `arkhai-e2e-tests`;
      `make lock`.
- [ ] 13.7 **Verify.** `make test-e2e-unit` (unit); `make test-provisioning`; `make test`;
      `make check-packaging`. End-to-end: every lane's scenarios run on the holds
      (`make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal`, `test-e2e-apicredits`), and
      after `make helm-topology-check` Bob's loops report running (the maintainer's, 11.8).

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
      an unusable Alkahest section is unready. Name each in the design-promotion record.
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
        interval and timeout, the degraded start in "System status", and the rewritten
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
        blocker kind tells the publication runner.
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
