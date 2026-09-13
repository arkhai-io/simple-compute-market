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

## 3f. Buyer identity on the negotiation path

Round result: **8 failed, 57 passed, 36 skipped** from 8/55/38. Fan-in is
fixed; no per-URL registry errors remain.

- [x] 3f.1 **`buyer_address` is retired across the client.** No method accepts
      it, so all 14 call sites were latent `TypeError`s; only two had been
      reached. The replacement differs by method, which is why a blanket
      rename would have been wrong:
      - `negotiate_new` derives `buyer_principal` from the signer — the
        argument is simply gone.
      - `evaluate_negotiate` takes `buyer_principal: Identity`.
      - `settle` still needs the wallet, now as `buyer_evm_address`.
      - `get_settle_status` and `wait_for_settlement` never needed it.
- [x] 3f.2 **Corrected an error from 3d.** The two multi-registry buyer clients
      were built without a signer on the belief that `negotiate_new` is
      unauthenticated. It signs with `role="buyer"` and takes the buyer
      principal from the signer, so both now carry one.
- [x] 3f.3 **Checked the whole surface statically rather than per run.** Walked
      the AST of every e2e module and compared each storefront-client call
      against the installed signature: unknown keywords and missing required
      arguments. That found two sites in a module this round had not touched.
      **0 mismatches** remain suite-wide. Reacting to one `TypeError` per run
      is what turned this into five rounds; the signatures were readable all
      along.

- [x] 3f.4 **The 05a assertion earned its keep immediately.** It now reports
      `decision='reject' reason='no_matching_inventory'` — not a price problem.
      The message it replaced would have sent the reader to adjust
      `BUYER_INITIAL_PRICE`, which is why it was worth fixing before tuning
      anything.

- [ ] 3f.5 **Findings.** `no_matching_inventory` and the two
      `409 No available compute VM` reservation failures are plausibly one
      cause — the seeded inventory not matching the demanded resource
      attributes — and should be investigated together rather than as three.
      Also open: `500 UNIQUE ...derivation_key` (1), `market credits buy`
      `rc=2` (1), `market buy` `rc=0` with no run-log (1).

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
