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
- [x] 3.3 **Confirmed.** `[SETTLEMENT] mechanism=alkahest.v1 configured=True
      enabled=True ready=True blockers=` with zero `option suppressed` lines.
      **10 failed, 47 passed, 44 skipped** from 11 failed / 38 passed / 52
      skipped: the seven listing-create refusals are gone, nine more tests
      pass, and eight fewer skip. The escrow phases now execute.
- [x] 3.3a Original wording, kept for the criteria it names:
      `make -C e2e-tests test-e2e`: confirm `checks.alkahest` reports
      `anvil`, that no `[SETTLEMENT] option suppressed` line names
      `alkahest.v1`, and that the seven listing-create refusals are gone.
      Compare failure *causes*, not counts — the escrow phases have never run,
      so new failures downstream of a now-publishing listing are the expected
      result and are findings for classification, not regressions.
- [ ] 3.4 `make test` stays green. No production Python changed, so nothing is
      expected here; run it rather than assume.

## 3b. Drift the settling stack exposed

Publishing listings reached code that had never run. Three were mine.

- [x] 3b.1 `ProvisioningTestClient._verify` omitted `verify_response`'s
      required `max_skew`. Now carries `max_timestamp_skew=300`, mirroring the
      canonical client's own default rather than a new number.
- [x] 3b.2 `validate_publish_listing` is a seller operation but two tests still
      called it on the buyer-role client. The registry refused it and the
      refusal was not a signed v2 response, so the client reported
      `unsupported_version` wrapped as `502` — a confusing surface for a plain
      role error. Repointed to `registry_seller_client`, which existed but had
      no callers.
- [x] 3b.3 Four raw `httpx.get` reads of `/listings/{id}` sent no headers;
      that route authenticates and admits `buyer`, `seller`, or `service`, so
      it answered `401 context_mismatch`. Signed via a helper, verified against
      the registry's own `verify_request`. They stay raw because they assert on
      the status code — 200 against 404 is what distinguishes "published here"
      from "not published here", and the typed client raises instead of
      reporting it. The two private-registry reads keep their bearer token
      alongside the signature: both gates apply and neither substitutes for
      the other.

- [ ] 3b.4 **Findings, not repaired here.** Each is downstream of a listing
      that now publishes, so none was observable before this change:

      | Finding | Tests |
      |---|---|
      | `409 No available compute VM matched required attributes` on admin reservation | 2 |
      | `500 UNIQUE constraint failed: storefront_listing_bindings.derivation_key` on a second listing create | 1 |
      | `market credits buy` exits `rc=2` before writing a run-log (carried from the previous change) | 1 |

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
