# Tasks — move-api-family-kit-into-domains

Sections 1 and 2 are the move; sections 3 to 6 are the fixes. A specification,
guidance, or the architecture description names no change
(`docs/guidance/engineering/documentation.md`, "Specifications, guidance, the
architecture description and handbooks name no change"), so every task that
writes one states the fact without the pointer.

This change's dependency on `compose-api-family-kit`, which is archived on this
branch, is released.

## 1. The family at `domains/api`, read as a family only there

Delivers D1: the tree, the rules, the build, the continuous-integration job,
the manifest, and every test that reaches the family by path. Touches
`kit/api` (moved whole), `scripts/architecture.py`,
`scripts/tests/test_architecture.py`, `docs/development/ARCHITECTURE.toml`,
`kit/Makefile`, `domains/Makefile`, `.github/workflows/tests.yml`,
`manifests/release-components.json`, and tests under `domains/apicredits`,
`domains/inference`, and `tools/issue-discovery`.

- [x] 1.1 Remove the ignored `domains/api` directory of stale environments and
      caches, on the owner's word, then `git mv kit/api domains/api` (D1).
      Verify: `git ls-files kit/api` lists nothing, `git ls-files domains/api`
      lists the family, and no path is `domains/api/api`.
      *Note:* done. 262 tracked files moved; `git ls-files kit/api` lists
      nothing and no path is `domains/api/api`. The ignored `domains/api`
      held environments and caches only (787 MB, no tracked file). The
      family's ignored `.venv` directories moved with it, carrying absolute
      paths to `kit/api`, so `uv run` could not spawn `pytest`; they were
      removed and rebuilt by each project's `reinit`.
- [x] 1.2 `docs/development/ARCHITECTURE.toml`: the `api` family's `directory`
      is `domains/api`. `scripts/architecture.py`: `read_path` reads a family
      only under `domains/`, as the branch this change lands on has it.
      `scripts/tests/test_architecture.py`: remove
      `test_a_family_under_kit_is_read_as_its_family` (D1). Verify: `make
      check-architecture` passes with no new exception or override row, and
      `make test-release-tooling TESTS=scripts/tests/test_architecture.py`
      passes.
      *Note:* `scripts/architecture.py` and its test are restored to the
      landing branch's bytes (`git diff origin/dev` empty for both). `make
      check-architecture` holds the layer, scope, dependency, and kind rules
      with no new row; 61 cases pass.
- [x] 1.3 Move the family's `dist-api*` and `test-api*` recipes from
      `kit/Makefile` to `domains/Makefile`, with the wheelhouse variable they
      use; add them to `domains/Makefile`'s `.PHONY`, `dist-release`, and
      `test`; remove them, `test-api` from `test`, the `dist-api*` targets from
      `dist-ci`, `API_DIST_DIR`, and the comments naming them from
      `kit/Makefile` (D1). Verify: `make -C domains -n test` names `test-api`,
      `make -C kit -n test` does not, and `make dist` builds the twelve family
      wheels.
      *Note:* `kit/Makefile` is restored to the landing branch's bytes. The
      recipes use `domains/Makefile`'s own `DIST_DIR`, already absolute, so
      `API_DIST_DIR` is not carried over; that file already exports the
      Python version and build constraint the family's recipes needed. The
      family's wheels precede the API-credits and inference wheels in
      `dist-release`, and `test-api` precedes `test-apicredits` in `test`.
      `make -C domains -n test` runs the family's thirteen recipe lines;
      `make -C kit -n test` names none; `make dist-clean && make dist` built
      the twelve.
- [x] 1.4 `.github/workflows/tests.yml`: the Node and Rust installs and the
      Rust cache's `workspaces` follow the family to the job that runs the
      domain tests, with the comment above them (D1). Verify: the conditions
      name the domain target and the cache names `domains/api/gate-ports/rust`.
      *Note:* the three steps and their comment now match the landing
      branch's shape, with the cache at `domains/api/gate-ports/rust`,
      checked by reading; no test reads a step's condition or the cache's
      workspace, so the dispatched run 1.8 owes is what shows them working.
      `test_tests_workflow.py` and `test_workflow_targets.py`, which hold the
      matrix equal to `make test`'s targets: 10 passed.
- [x] 1.5 `manifests/release-components.json`: the twelve family `path` values
      (D1). Verify: `make check-release-components` passes.
      *Note:* twelve paths rewritten; `make check-release-components`
      passes.
- [x] 1.6 Tests that build the family's path from separate words:
      `domains/apicredits/tests/conftest_wheels.py`,
      `domains/inference/tests/conftest_wheels.py`,
      `domains/apicredits/service/tests/integration/test_compat_baseline.py`,
      `domains/apicredits/tests/test_issuance_pins.py`,
      `domains/apicredits/storefront/tests/unit/test_issuance_pins.py`, and the
      family's `tests/integration/test_distribution.py`; and
      `tools/issue-discovery/tests/test_bootstrap.py`, which runs a recipe in
      the family's directory (D1). Verify: each named suite passes from the new
      path.
      *Note:* a tree-wide search for the path written whole or as `"kit" /
      "api"` found exactly these seven files. The six Python tests pass in
      the suites 1.8 names. The issue-discovery bootstrap suite did not run:
      on this Mac 15 of its 18 cases fail in a fixture asserting `getent`, a
      Linux tool, before any test body, and the local end-to-end image has
      `getent` but no `make`, which the cases calling the edited line need.
      The suite is in no CI matrix (design, "Notes for planning"), so no
      validation runs it either: the edited line is unexercised. Running the
      recipe by hand under the real `PATH` exits 0, which is not the test's
      faked environment.
- [x] 1.7 Lines inside the family that name its own path: the gate ports'
      READMEs and source comments, the TypeScript gate's `package.json`
      `repository.directory` and `homepage`, and the gate's module docstrings
      (D1). Verify: `git grep -n "kit/api" -- domains/api` finds nothing.
      *Note:* nine files; `git grep -n "kit/api" -- domains/api` finds
      nothing.
- [x] 1.8 Verification. `make dist-clean && make dist && make lock`, then
      reinstall each dependent's environment; the twelve locks are unchanged
      but for their path. Family suites, unit and library integration:
      `make -C domains test-api`. Domain suites, unit and application
      integration: `make -C domains test-apicredits test-inference`. `make
      check-packaging`.
      End-to-end: `e2e_credits_deal` on the API-credit lane and
      `e2e_inference_deal` on the inference lane exercise the family's code
      from its new path; no scenario is added.
      *Note:* `make dist-clean && make dist && make lock` passed and changed
      no lock: each records the wheelhouse by a relative path whose depth
      the move keeps. Family, unit and library integration, `make -C
      domains test-api`: twelve Python suites, 786 passed; the Rust port 10
      passed; the TypeScript port's check passed. Domain, unit and
      application integration, `make -C domains test-apicredits
      test-inference`: 471 and 358 passed, five suites each. `make
      check-packaging` passed. `change-workflow run pre-commit --base
      origin/dev`: the relock and every repository check passed; its `make
      test` stopped at the bare-metal provisioning IaC suites, which read
      `/proc/self/fdinfo` and fail on macOS on the landing branch too,
      before it reached the family. End-to-end scenarios confirmed as the
      plan names them: `e2e_credits_deal` and `e2e_inference_deal` install
      the family's wheels, built from the new path; neither was run here,
      and no scenario is added.
      Owed by validation (ci tests.yml): job `test · test-domains` — the
      Node and Rust installs and the Rust cache of
      `domains/api/gate-ports/rust` run, and `make test-domains` runs the
      family's Python suites, the TypeScript port's check, and the Rust
      port's `cargo test`, each passing.

## 2. Documents and citations follow the move

Delivers D1's permanent wording and D6. Touches
`docs/guidance/repository/package-layers.md`,
`docs/development/ARCHITECTURE.md` and its `diagrams/domain-anatomy` source and
export, `docs/development/ROADMAP.md` (the kit goal's path),
`docs/guidance/repository/published-packages.md`, `contract-conformance.md`,
and `migrations-at-startup.md`, the specifications' evidence sections and
companions that cite the path, and the active changes' documents that cite it.

- [ ] 2.1 `docs/guidance/repository/package-layers.md`, "Scope": a package
      several domains of a family share goes under the family's directory, and
      `kit/` holds no specialization; the sentences placing the api family
      under `kit/` go (D1). Verify: the paragraph names `domains/api` and
      `domains/compute` under one rule.
- [ ] 2.2 `docs/development/ARCHITECTURE.md`, "Package and dependency layers"
      and "Family kits": the vocabulary paragraph and the distribution table
      name `domains/api`, and the count of distributions matches the tree; the
      domain-anatomy diagram's source and its export carry the new labels (D1).
      Verify: `git grep -n "kit/api" -- docs` finds nothing.
- [ ] 2.3 `docs/guidance/repository/published-packages.md`, "Published
      packages" and the npm path it names; `contract-conformance.md`;
      `migrations-at-startup.md`; `docs/development/ROADMAP.md`'s kit goal
      (D1). Verify: `make test-release-tooling
      TESTS=scripts/tests/test_publish_matrix.py` passes.
- [ ] 2.4 The evidence sections of `openspec/specs/deployment-state/spec.md`,
      `resource-pool-management/spec.md`, and `storefront-publication/spec.md`,
      and the companions `openspec/specs/api-family/architecture.md` and
      `openspec/specs/inference/architecture.md`: each cited path (D1). The
      requirement text of `api-family`, `market-composition`, and `api-credits`
      is the archive's to write from this change's deltas. Verify: `git grep -n
      "kit/api" -- openspec/specs` finds only the three requirements the deltas
      modify.
- [ ] 2.5 The `kit/api` citations in the documents of
      `keep-buyer-credentials-private`, `derive-buyer-settlement-inputs`,
      `kit-owned-storefront-auth-and-persistence`,
      `repair-storefront-alkahest-configuration`, and
      `sign-multi-language-credits-middleware`, and in the change index (D6).
      Verify: `git grep -n "kit/api" -- openspec/changes ':!openspec/changes/archive'`
      finds only this change's own account of the move.
- [ ] 2.6 Verification. `make check-doc-citations` reports no failure it did
      not report before the section; `make check-guidance`;
      `change-workflow run pre-commit move-api-family-kit-into-domains`.
      End-to-end: none exercises a document.

## 3. The authority refuses a pinned key's consumption at another amount

Delivers D4 and the delta requirement "A key is scoped to its first grant".
Touches `domains/api/contracts` and `domains/api/authority`.

- [ ] 3.1 `arkhai_api_contracts/refusals.py`: `CHARGE_MISMATCH` beside the
      others and outside `CONSUME_REFUSALS`, whose comment says it holds the
      refusals of a key or its credit; `models.py`: the consume refusal
      model's description says the same (D4). Verify: the contracts unit suite
      and the gate's contract parity test pass unchanged.
- [ ] 3.2 `arkhai_api_authority/keys_service.py`: `consume` refuses an amount
      other than the first grant's pinned charge, after the not-found, revoked,
      and out-of-scope refusals and before the idempotency lookup and the
      balance check, answering the key's balance and debiting nothing; an
      unpinned key is charged the amount sent. `route_services.py`: the reason
      answers `409` (D4). Verify: unit cases for each scenario of the delta —
      another amount, a revoked pinned key, a replay at another amount, an
      unpinned key — and for a batch carrying one mismatched item.
- [ ] 3.3 Application integration: the inference service refuses a signed
      consume of a pinned key at another amount with `409 charge_mismatch`
      through its typed client, and the API-credits service's recorded
      baselines are unchanged (D4). Verify: `make -C domains
      test-inference-service test-apicredits`.
- [ ] 3.4 Verification. `make -C domains test-api-authority`; the contracts
      and gate suites; `change-workflow run pre-commit
      move-api-family-kit-into-domains`.
      End-to-end: none reaches the refusal, since the gate always sends the
      pinned charge; `e2e_inference_deal` shows a pinned key still charged its
      pinned amount. None is owed.

## 4. The selling library takes the emitter by injection and assembles the settlement composition

Delivers D5 and D7. Touches `domains/api/selling`, the API-credits and
inference storefronts, and `docs/development/ARCHITECTURE.toml`.

- [ ] 4.1 `ListingService`, `StorefrontLoops`, and `build_negotiation_runtime`
      take `stage_event` as a required keyword, and `listings.py`,
      `lifecycle.py`, and `negotiation.py` stop importing it from the
      storefront role; each storefront passes the emitter where it constructs
      them (D5). Verify: `git grep -n "core_storefront.stage_log" --
      domains/api/selling/src` finds nothing, and the selling unit suite
      passes with a recorder in its fixtures.
- [ ] 4.2 `docs/development/ARCHITECTURE.toml`: the reason of the exception row
      for `arkhai-api-selling` on `arkhai-core-storefront` no longer lists the
      stage-event log (D5). Verify: `make check-architecture` passes.
- [ ] 4.3 `arkhai_api_selling/settlement_composition.py`: one builder that
      takes the contributions, stages, domain, database path, settlement
      configuration, the storefront's resources, signer, authority client,
      failure policy, worker identity, servicing interval, and event recorder,
      with an optional dispute policy and dispute interfaces, and returns the
      composition; and the stage-validation function both storefronts repeat
      (D7). The library gains no dependency. Verify: library-integration cases
      build a composition with and without a dispute policy, and assert the
      evidence service trusts only the signer passed.
- [ ] 4.4 Each storefront's `settlement_composition.py` builds its own
      resources and calls the library's builder; API credits alone passes the
      dispute policy and the mediation interface.
      `services/fulfillment_service.py` is unchanged in both (D7). Verify:
      the storefronts' application-integration suites pass unchanged.
- [ ] 4.5 Verification. `make -C domains test-api-selling test-apicredits
      test-inference-storefront`; `make check-packaging`;
      `change-workflow run pre-commit move-api-family-kit-into-domains`.
      End-to-end: `e2e_credits_deal` and `e2e_inference_deal` settle and
      issue through the builder and record stage events through the injected
      emitter.

## 5. Tests take their doubles through seams, and the family replays its own pin

Delivers D8 and D9. Touches `domains/api/buying-alkahest`,
`domains/api/buying`, `domains/api/tests`, `domains/inference/buyer/tests`,
and `domains/apicredits/tests`.

- [ ] 5.1 `AlkahestBuyerStage`: optional keyword collaborators for the two
      seller calls and the chain resolver its settle path uses, each resolved
      when called and falling back to the module's function (D8). Verify: the
      API-credits and inference buyer suites pass unchanged.
- [ ] 5.2 The scope-refusal test moves to the Alkahest buying library's unit
      tests, driving `AlkahestBuyerStage.resume` through those collaborators
      and a settlement resume whose log, buy configuration, and seller
      principals are doubles; it replaces no library name (D8). Verify: it
      fails against the stage without the collaborators
      (`change-workflow run test-before`) and passes with them.
- [ ] 5.3 `domains/inference/buyer/tests/test_scope_refusal.py`: the delivered
      credential's rows are asserted by calling the settlement resume's
      `finish` with the inference contributions, a memory credential store,
      and a log double (D8). Verify: the module holds no `monkeypatch.setattr`.
- [ ] 5.4 `FileCredentialStore`: optional `replace`, `fsync`, and `open`
      parameters. `tests/unit/test_credentials.py`: each standard-library
      patch becomes a parameter, the patch of a method no code under test
      calls is deleted, and the log failures use a log double or a real
      unwritable path (D8). Verify: the module patches nothing in `os` or on
      `RunLog`, and the buying unit suite passes.
- [ ] 5.5 The family's `tests/unit/test_issuance_pins.py` replays the
      inference-label case from the recorded fixture, its helper carrying
      accepted terms, the terms digest, and the request charge;
      `domains/apicredits/tests/test_issuance_pins.py` keeps its own cases and
      a writer for those alone. The fixture's bytes do not change (D9).
      Verify: `git diff --stat` shows no change to
      `tests/fixtures/pins/issuance_pins.json`, and both suites pass.
- [ ] 5.6 Verification. `make -C domains test-api-buying
      test-api-buying-alkahest test-api test-inference-buyer test-apicredits`;
      `change-workflow run pre-commit move-api-family-kit-into-domains`.
      End-to-end: `e2e_credits_deal` and `e2e_inference_deal` settle through
      the Alkahest buyer stage with its default collaborators.

## 6. The roadmap, the notes, and the rows

Delivers D10, D12, the reason D7 states, and D4's consequence for the roadmap. Touches
`docs/development/ROADMAP.md`, `openspec/specs/inference/architecture.md`,
`openspec/changes/README.md`, and two other changes' documents.

- [ ] 6.1 `docs/development/ROADMAP.md`, the inference goal: the paragraph
      fixing the campaign's order and recounting a withdrawn approach is
      replaced by its closing pointer to the change index (D10). Verify: the
      goal holds no sentence of sequence.
- [ ] 6.2 `docs/development/ROADMAP.md`, the inference goal's current state:
      the sentence saying the authority's consumption route accepts a variable
      amount says instead that it charges an unpinned key the amount sent and
      refuses a key whose first grant pins a request charge, as every
      inference key's does, at any other amount, so a measured charge needs
      routes of its own (D4; the workflow's closeout part "Roadmap currency").
      Verify: the sentence agrees with the delta requirement "A key is scoped
      to its first grant". The `qualify-inference-market` row's reference to
      its goal's completion test, which D10 also names, is already corrected.
- [ ] 6.3 `openspec/specs/inference/architecture.md`, "Role composition over
      the family kit": inference composes no dispute policy because it settles
      through Alkahest alone and reads no dispute authority (D7). Verify: the
      sentence is present and names no change.
- [ ] 6.4 `openspec/changes/move-escrow-into-alkahest/proposal.md`: a bullet
      naming the three Alkahest buyer modules of the family's buying library,
      the VM buyer's copies, the cycle and the configuration read that keep
      them from the Alkahest kit today, and the question of a buyer-side
      Alkahest kit; and its index row's Notes (D12). Verify: the row and the
      bullet name the same three files.
- [ ] 6.5 `openspec/changes/kit-owned-storefront-auth-and-persistence/design.md`,
      "Questions to settle before planning": the negotiation service's error
      is an import of the selling library the carve-out places; and its index
      row's Notes (D12). Verify: present in both.
- [ ] 6.6 Index rows' Notes: `sign-multi-language-credits-middleware` — the
      ported gates send no key scope and ignore a pinned charge, and the
      TypeScript gate answers an unknown refusal as exhausted credit;
      `keep-buyer-credentials-private` — the parameters section 5 adds to the
      credential store and the rewrite of its test module;
      `derive-buyer-settlement-inputs` — the collaborators section 5 adds to
      the Alkahest buyer stage (D12). Verify: `change-workflow check index`.
- [ ] 6.7 The index's unowned work for the kit goal: add the payments adapter
      the VM and bare-metal buyers each construct in near-identical lines
      (D12). The row saying the API-credit lane has never run against the
      family kit, which D12 also names, left the index with
      `compose-api-family-kit`'s archive cleanup, whose row records the run.
      Verify: `change-workflow check index`.
- [ ] 6.8 Verification. `make check-doc-citations
      CHANGE=move-api-family-kit-into-domains`; `change-workflow run
      pre-commit move-api-family-kit-into-domains`.
      End-to-end: none exercises a document.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** `make check-comment-hygiene` passes; the
      comments sections 3 to 5 added describe the current system and name no
      change.
- [ ] 7.2 **Import placement.** The imports sections 3 to 5 added are at
      module level, or carry their reason.
- [ ] 7.3 **Documentation compliance.** Re-check D1 to D13 against the
      placement rules, and each permanent document this change wrote for the
      current state stated declaratively and naming no change.
- [ ] 7.4 **Narrative compression.** Shorten the notes of sections 1 to 6 to
      final behaviour, validation evidence, and destinations.
- [ ] 7.5 **Roadmap currency.** The inference goal's two changes are section 6's;
      the kit goal's path is section 2's; record that no gap row closes.
- [ ] 7.6 **Campaign index currency.** This change's row and the kit goal's
      graph line; `make check-change-index`.
- [ ] 7.7 **Packaging.** `make check-packaging`, then `make
      check-architecture-change CHANGE=move-api-family-kit-into-domains`,
      which finds no row this change owns.
- [ ] 7.8 **End-to-end pipeline.** Record the run the latest passing
      validation gathered, its result on the four lanes, and that
      `e2e_credits_deal` and `e2e_inference_deal` exercise the moved family.
- [ ] 7.9 **Promotion.** Confirm what sections 2 and 6 wrote —
      `docs/guidance/repository/package-layers.md`, "Scope";
      `docs/development/ARCHITECTURE.md`, "Family kits";
      `docs/development/ROADMAP.md`'s inference goal;
      `openspec/specs/inference/architecture.md`, "Role composition over the
      family kit" — and write `openspec/specs/api-family/architecture.md`:
      "The gate", that the authority refuses a pinned key's consumption at
      another amount and that a batched item so refused is neither resent nor
      charged (D4); "Current limits", that the selling library takes the
      stage-event emitter by injection (D5); "Mechanism stages", that the
      selling library assembles the settlement composition from the resources
      a storefront passes (D7). The three `spec.md` files the deltas cover are
      the archive's. Complete the design promotion record.
- [ ] 7.10 **Guidance placement.** Read the rewritten paragraph of
      `package-layers.md` against the layer test; `make check-guidance`.
- [ ] 7.11 **Documentation citations.** `make check-doc-citations
      CHANGE=move-api-family-kit-into-domains`, then `change-workflow
      openspec validate move-api-family-kit-into-domains --strict`.
- [ ] 7.12 **Archival.** `change-workflow openspec archive
      move-api-family-kit-into-domains -y`, which merges the three deltas.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1: a family kit lives under its family's directory | `docs/guidance/repository/package-layers.md`, "Scope"; `docs/development/ARCHITECTURE.md`, "Family kits"; `openspec/specs/api-family/spec.md`; `openspec/specs/market-composition/spec.md`; `openspec/specs/api-credits/spec.md` |
| D4: the authority refuses a pinned key's consumption at another amount | `openspec/specs/api-family/spec.md`, "A key is scoped to its first grant"; `openspec/specs/api-family/architecture.md`, "The gate" |
| D5: the selling library takes the stage-event emitter by injection | `openspec/specs/api-family/architecture.md`, "Current limits" |
| D7: the selling library assembles the settlement composition; inference composes no dispute policy | `openspec/specs/api-family/architecture.md`, "Mechanism stages"; `openspec/specs/inference/architecture.md`, "Role composition over the family kit" |
| D10: the inference goal fixes no order | `docs/development/ROADMAP.md` |
