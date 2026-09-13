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

## 3k. The lifecycle module I was reinventing

Run: **10 failed, 72 passed, 32 skipped** from 7/69/38. Six previously-skipped
stages now run, which is why passes and failures both rose.

- [x] 3k.1 **My pause assertion asserted what I had documented it could not.**
      `set_loops_paused` returned a snapshot, and my own docstring said so: *"a
      loop mid-cycle when the request arrives is still `running` ... a caller
      that needs the stronger property waits."* `pause_storefront` then
      asserted every loop was already `paused`. Two rounds running I wrote the
      correct reasoning in a comment and contradicted it in code.

- [x] 3k.2 **An eighth deleted module: `market_storefront/lifecycle.py`**, 350
      lines, which is the designed version of the gate I hand-rolled. It has
      what mine lacked: a per-loop acknowledgement event, `await_quiescence`
      with a bounded wait so pausing returns only once loops sit at their
      gates, `pausing` distinguished from `paused`, and a warning when a loop
      gates under an unregistered name. Its comments also record the exact
      trap I fell into: *"conflating the two made the second impossible to ask
      for."*

      Restored it and tombstoned my `core_storefront/loop_lifecycle.py`.
      `server._set_loops_paused` awaits quiescence before reporting.
      `CLAIMS_ENGINE` becomes `SETTLEMENT_SERVICING`, the same periodic sweep
      under the name the neutrality redesign gave it.

- [x] 3k.3 Restored `test_lifecycle_registry.py` and
      `test_lifecycle_client_parity.py`, also deleted. Storefront suite
      **1128 passed** (from 1107), with the 4 pre-existing failures.

- [ ] 3k.4 **`test_loop_gate_wiring.py` is held back, and is the next task.**
      Restoring it fails 10 tests, which is the correct answer: it asserts that
      *every* production loop acknowledges its gate, and my rewiring covers
      four of five. The capacity-events poller is ungated and registers one
      loop per site, which the test also checks. Not shipped only because
      landing a red suite is worse than landing a precise specification of the
      remaining wiring; it goes in next round with the wiring that satisfies
      it, and must not be weakened to fit.

- [ ] 3k.5 **New, needs diagnosis.** Reservations moved from `502` to
      `500` and a `settle/{escrow}` call now fails — both further along the
      capacity path than before, both first-time-reached. Findings unchanged:
      `500 UNIQUE ...derivation_key`, credits `rc=2`, `market buy` `rc=0`.
      Out of scope: alice `offer_unfulfillable`.

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
