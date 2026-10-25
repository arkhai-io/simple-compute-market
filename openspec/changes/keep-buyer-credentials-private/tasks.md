# Implementation Tasks

One implementation section, then closeout. Decisions are cited as `D<n>` from
`design.md`; requirements by the delta that states them (`buyer-orchestration`,
`api-family`). The end-to-end scenarios are run by validation, not on the
implementing machine.

**Dependencies.** `compose-api-family-kit`, whose buying library this changes.

## 1. The private store, the scrubbed run log, and retrieval

Touches `domains/api/buying/src/arkhai_api_buying/` (`credentials.py` new;
`stages.py`, `buy.py`, `common.py`, `commands.py`, `settle.py`,
`settlement_composition.py`), `domains/api/buying-alkahest/src/arkhai_api_buying_alkahest/stage.py`,
their tests, `domains/apicredits/buyer/tests/`, `e2e-tests/tests/e2e/roles/buyer_cli.py`,
both API-credit scenarios, and `docs/cookbooks/vllm-apicredits-seller.md`.

- [ ] 1.1 Add `arkhai_api_buying.credentials`: the `CredentialStore` protocol,
      `FileCredentialStore` under `runs_dir().parent / "buy-credentials"`
      (`0700` directory, `0600` file, atomic write, symlink and run-ID refusal),
      `public_fields`, and `DeliveryRunLog` (D1, D2; `buyer-orchestration` "A
      buyer's private credential store"). Unit tests with a temporary
      `XDG_STATE_HOME`: modes, atomic replace, symlinked directory and file
      refused, unsafe run ID refused, nested `tenant_credentials` scrubbed.
- [ ] 1.2 Give `BuyerSettlementComposition` a `credential_store`; record
      delivery through one helper used by `SettlementResume.finish` and `buy`:
      `credentials_delivered` with `key_id`, `base_url`, `balance`,
      `delivery_ref`, or `credentials_unsaved` with the error class, panel, and
      exit 8 (D2, D4). Wrap `buy`'s and `SettlementResume.open_log`'s logs in
      `DeliveryRunLog`; print the Alkahest submit response through
      `public_fields`. Update `test_settle.py` and `test_settle_credentials.py`.
- [ ] 1.3 Add `credentials show --from <run-id> [--json]` to the command group,
      with the legacy run-log fallback (D3, D5; `buyer-orchestration` "A buyer
      retrieves a delivered credential by run"). Application-integration tests
      in `domains/apicredits/buyer/tests/` through the plugin's app: stored
      key, `--json`, legacy run, no delivery.
- [ ] 1.4 Canary test: `credits settle --from` with the secret in the submit
      response, a poll body, and the terminal status; it appears only in the
      store and the panel, not in the run log, captured logging, or other output
      (D6). Failed-write test: a symlinked store directory gives
      `credentials_unsaved`, the panel, and exit 8.
- [ ] 1.5 `BuyerCli.credentials`; migrate `e2e_credits_deal` and
      `e2e_credits_payment_deal` to it (D7). Add retrieval to the cookbook's
      buyer section.
- [ ] 1.6 Versions (design "Versions"), wheels, relocks of the buying
      libraries, `domains/apicredits/buyer`, `domains/apicredits/storefront`,
      and `e2e-tests`. Run `make test-api-buying`, `-alkahest`,
      `-arkhai-payments`, `make -C domains/apicredits test-buyer`,
      `make -C domains/apicredits/storefront test`; on a clean copy
      `make check-packaging`, `make check-comment-hygiene`,
      `make check-change CHANGE=keep-buyer-credentials-private`, and
      `make -k test`. One fresh-context compliance check of the diff.

## 2. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only; a part needing a code edit returns the
change to implementation.

- [ ] 2.1 **Comment hygiene.** `make check-comment-hygiene` passes.
- [ ] 2.2 **Import placement.** The imports section 1 added are module-level,
      or their task note records why not.
- [ ] 2.3 **Documentation compliance.** Re-check D1–D7 against the placement
      rules and the record below.
- [ ] 2.4 **Narrative compression.** Shorten section 1's notes.
- [ ] 2.5 **Roadmap currency.** No roadmap goal names this gap; record that
      disposition.
- [ ] 2.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md`.
- [ ] 2.7 **Packaging.** `make check-packaging`, then
      `make check-architecture-change CHANGE=keep-buyer-credentials-private`
      (the change owns no exception row).
- [ ] 2.8 **End-to-end pipeline.** Record the run and that `e2e_credits_deal`
      and `e2e_credits_payment_deal` exercised retrieval.
- [ ] 2.9 **Promotion.** Write `openspec/specs/api-family/architecture.md`'s
      buyer-side note on the store and the scrubbed log (D1, D2); complete the
      record below.
- [ ] 2.10 **Documentation citations.** `make check-doc-citations
      CHANGE=keep-buyer-credentials-private`; then
      `openspec validate keep-buyer-credentials-private --strict`.
- [ ] 2.11 **Archival.** `openspec archive keep-buyer-credentials-private -y`,
      after `compose-api-family-kit`, whose `api-family` specification the
      delta extends.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — a private buyer credential store behind a scheme-naming interface; the file store's modes, atomic write, and refusals | `openspec/specs/buyer-orchestration/spec.md` ("A buyer's private credential store"); `openspec/specs/api-family/architecture.md` (the file store's location and injection point) |
| D2 — `credentials_delivered` without the secret; every recorded status body scrubbed | `openspec/specs/buyer-orchestration/spec.md` ("Buyer evidence is separate from private delivery"); `openspec/specs/api-family/spec.md` ("The buying library keeps a delivered credential private") |
| D3, D5 — retrieval by run, the legacy fallback, no rewrite | `openspec/specs/buyer-orchestration/spec.md` ("A buyer retrieves a delivered credential by run") |
| D4 — a failed write shows the key once, records `credentials_unsaved`, exits 8 | `openspec/specs/buyer-orchestration/spec.md` ("A failed private write does not lose a delivered credential") |
| D6 — the secret reaches only the panel | `openspec/specs/api-family/spec.md` ("The buying library keeps a delivered credential private") |
| D7 — scenarios retrieve through the command | Test code only (`e2e-tests/tests/e2e/roles/buyer_cli.py`) |
| Deferred — keyring store, legacy migration, `secret` in the core role's refused fields | `design.md` "Deferred" (no permanent home until a change takes them) |
