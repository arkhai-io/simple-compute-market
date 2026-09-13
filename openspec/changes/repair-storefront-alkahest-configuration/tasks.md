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

## 3i. Faults in the restored stages

Run: **14 failed, 61 passed, 39 skipped** from 8/57/36. The rise is the 13
restored stages running for the first time since August; 14 = the 8 carried
failures plus 6 new, all in the restored code.

- [x] 3i.1 **The capacity-admin client was signing as the wrong principal.**
      Five failures, one per executor stage:
      `SiteCapacityAdminClientError: Invalid marketplace authentication`.
      `SiteCapacityAdminClient` asserts the `seller` role, and provisioning
      binds that role to the storefront principal it serves
      (`PROVISIONING_STOREFRONT_IDENTITY__IDENTIFIER`, Anvil 2). The fixture
      signed as the provisioning administrator, which is trusted for `admin`
      and refused here.

      The August fixture passed a shared admin key, under which the caller's
      identity did not matter; it does now. Declaring sellable capacity is a
      seller's act, so the corrected principal agrees with what the call means
      rather than merely satisfying the check. Verified the signer derives to
      exactly the identifier provisioning pins.

- [x] 3i.2 **Two constants and a helper were left behind by the restoration.**
      `DYNAMIC_POOL_ID`, and `E2E_LEASE_EXPIRY_BACKDATE` with
      `_expired_lease_end()`. Inserting stage bodies moved the code that used
      module-level names without the names themselves — the restoration was
      scoped to functions and classes, and nothing checked what they referenced.

      Swept the modules with pyflakes rather than fixing the one name the run
      reported: that found the other two before they cost a round. Added to the
      pre-handoff checks alongside the signature comparison, for the same
      reason — a `NameError` in a stage that has not run yet is invisible to
      both collection and the AST signature check.

- [ ] 3i.3 Findings unchanged: `409 No available compute VM` (2),
      `offer_unfulfillable` (2), `no_matching_inventory` (1),
      `500 UNIQUE ...derivation_key` (1), `market credits buy` `rc=2` (1),
      `market buy` `rc=0` with no run-log (1). The inventory cluster should
      clear once the executor stages authenticate.

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
