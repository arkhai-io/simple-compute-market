# Tasks — repair-storefront-alkahest-configuration

## Implementation status

**Implemented, unverified against the stack.** All three gaps are closed and
each fix is verified against the real packages at unit level. The e2e run that
confirms settlement becomes ready has not happened yet.

## 1. Supply the EVM credential

- [x] 1.1 Add `STOREFRONT_WALLET__PRIVATE_KEY` for `bob-storefront` and
      `alice-storefront` to `compose.local-identities.yml`, `@str`-marked.
      Anvil 2 for Bob and Anvil 4 for Alice, each derived and checked against
      the `Wallet.address` its own storefront config declares.
- [x] 1.2 Record at the call site why the name differs from the `AGENT_PRIV_KEY`
      the adjacent env files supply, so the next reader does not "fix" it back.

## 2. Make the address configuration reachable

- [x] 2.1 Bind-mount `alkahest_anvil_addresses.json` to
      `/app/alkahest_anvil_addresses.json` for both VM storefronts in
      `domains/vms/compose.yml`, matching the API-credits convention.
- [x] 2.2 Point `Settlement.alkahest.address_config_path` at the mount in
      `storefront.bob.toml` and `storefront.alice.toml`.
- [x] 2.3 Add `Chains.anvil.alkahest_address_config_path`, which client
      construction reads separately from the readiness preflight, and note
      that the two reads are independent.

## 3. Validation

- [x] 3.1 `build_alkahest_clients` reproduces the production symptom with no
      credential and proceeds past address-config resolution with one, failing
      only on DNS for the compose-internal RPC host.
- [x] 3.2 `alkahest_preflight` carries `alkahest.address_config_invalid` for
      the current path and not for the mounted one.
- [ ] 3.3 `make -C e2e-tests test-e2e`: confirm `checks.alkahest` reports
      `anvil`, that no `[SETTLEMENT] option suppressed` line names
      `alkahest.v1`, and that the seven listing-create refusals are gone.
      Compare failure *causes*, not counts — the escrow phases have never run,
      so new failures downstream of a now-publishing listing are the expected
      result and are findings for classification, not regressions.
- [ ] 3.4 `make test` stays green. No production Python changed, so nothing is
      expected here; run it rather than assume.

## 3j. Two pauses, and pools that declare what they deliver

Run: **7 failed, 69 passed, 38 skipped** from 14/61/39. Capacity declaration
worked: `no_matching_inventory` and the strategy's terminal `reject` are gone,
and the two reservation refusals moved from "no VM matched" to a mode
declaration — further down the same path.

- [x] 3j.1 **I conflated the two pause controls.** `negotiate/new` refused with
      `503 {"error":"paused","reason":"global"}` because I wired
      `set_loops_paused` into `admin_pause`, which also stops trading. August
      kept them separate and its docstring said why: *"a scenario needs
      deterministic reconciliation and a deal to agree."* A single control
      makes the second impossible.

      Restored `/lifecycle/pause` and `/lifecycle/resume` as loop-only
      controls with their own contracts and client methods; `/admin/pause`
      returns to trading only. My own gate module docstring claimed the two
      were "deliberately separate" while the controller wired them together —
      the test caught what the comment asserted.

      A gain from separating them: the loop-only response carries per-loop gate
      state, so `pause_storefront` again asserts that each loop reached its
      gate rather than that a pause was merely requested. That closes the
      weakening recorded in 3g.6.

- [x] 3j.2 **Pools must declare the offering modes they deliver.** Reservation
      refused with `offering mode 'vm' is not declared by matching pool(s)`.
      The August `register_e2e_pool` predates `pool-declared-offering-modes`
      (2026-09-04) and set only `listing_mode`. It now writes the
      `deliverable_modes` policy tag, and reconciles it on an existing pool the
      same way the listing mode already was. Verified against the server's own
      `pool_delivers_offering_mode` predicate, including that the old tag shape
      fails it.

- [ ] 3j.3 **Remaining.** Findings: `500 UNIQUE ...derivation_key` (1),
      `market credits buy` `rc=2` (1), `market buy` `rc=0` with no run-log (1).
      Out of scope: alice's `offer_unfulfillable` (1) — provisioning serves one
      storefront, so her capacity view cannot load; to be deprecated with that
      reason recorded. Expected to clear next run: the two reservation
      refusals (2).

## 4. Closeout

- [ ] 4.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 4.2 **Import placement.** No Python changed; record that disposition.
- [ ] 4.3 **Documentation compliance.** Confirm the no-permanent-change
      disposition still holds once the stack result is known.
- [ ] 4.4 **Narrative compression.** Reduce these notes to final state.
- [ ] 4.5 **Roadmap currency.** Expected to own nothing; record either way.
- [ ] 4.6 **Campaign index currency.** Move the alkahest item out of the
      campaign's unowned table into this change's row, and reconcile on
      archival.
- [ ] 4.7 **Promotion.** Complete the design-promotion record.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| *(none expected — configuration only; the conventions relied on are already demonstrated elsewhere in the repository)* | — |

## Deferred, carried out of this change

- [ ] 5.1 Converge compose configuration onto a single source shared with the
      tests, and reconcile it with the Helm charts, which express the same
      deployment more coherently. Accepted as follow-up during this change and
      deliberately not attempted here.
- [ ] 5.2 Stop the shared Dynaconf loader TOML-parsing environment values bound
      for string fields, so `0x`-prefixed credentials do not need `@str` per
      value. Second occurrence of the workaround; also carried as an inherited
      question from `provide-e2e-development-identities`.
- [ ] 5.3 Delete or rewrite `domains/vms/storefront/.env.{bob,alice}.docker`,
      which carry configuration for a layout that no longer exists, including a
      stale `ALKAHEST_ADDRESS_CONFIG_PATH`. Left in place because the compose
      files still reference them.
