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

## 3c. Registry response-body authentication (production)

Round result: **9 failed, 50 passed, 42 skipped** from 10/47/44. All three
3b fixes landed — `max_skew` gone, the repoint took effect, and the signed
reads verify (`bob_in_a` and `alice_in_a` both true where both were 401).

- [x] 3c.1 **The registry verified proofs against a re-serialized model.**
      `validate_publish` hashed `ValidatePublishRequest.model_validate(body)
      .model_dump(mode="json")`, which materializes every defaulted field. A
      caller that omits an optional one — `demands`, here — signs a different
      document and is refused `401`. The refusal is unsigned, so the client
      cannot verify it and reports `unsupported_version` wrapped as `502`,
      naming nothing about the cause.

      Added `wire_body` and authenticated against the bytes received; the
      parsed model still serves validation. Only this route was affected:
      `publish_listing` and `update_listing` take `body: dict` and so already
      hashed what arrived.

- [x] 3c.2 **The test suite had encoded the defect.** `_ValidationAuth` signed
      `ValidatePublishRequest.model_validate(json.loads(request.content))
      .model_dump(mode="json")` — the same transformation the server applied —
      so the pair agreed while every real client failed. Corrected to sign the
      wire bytes, and added a guard asserting that a payload omitting optional
      fields authenticates.

      Evidence the corrected tests exercise the fix: against pristine
      production code **all 10 fail**; with the fix the registry integration
      suite is **112 passed**. Every one of those ten was previously green only
      because the test reproduced the server's serialization.

- [x] 3c.3 **Buyer CLI config carried no authority pins.** `market buy` exited
      1 with `Missing required [registry.authorities] identity pins`. The
      fixture wrote only `[registry] urls`. Now emits one pin per registry with
      `authority` and `identities`, the exact key set the loader requires, and
      rejects a mapping that does not cover every configured URL — the loader
      demands an exact match, so partial pins are an error rather than a
      narrower trust set.

- [x] 3c.4 **The private registry's bearer token was stale.** The test
      hardcoded `test-buyer-token`; the stack seeds its bootstrap key
      (`development-registry-bootstrap-key`). Sourced from configuration, and
      the module docstring that asserted the old token corrected.

- [ ] 3c.5 **Finding: the committed buyer config is stale the same way.**
      `dev-env/identities/buyer.config.toml` spells the pin key `principals`
      where the loader requires `identities`, so it would fail with
      "contains an invalid authority" rather than the missing-pins error.
      Not repaired here: it is not on the e2e path, and it belongs with the
      inherited API-credits pin questions.

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
