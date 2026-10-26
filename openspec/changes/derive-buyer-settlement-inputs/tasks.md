# Implementation Tasks

One implementation section, then closeout. Decisions are cited as `D<n>` from
`design.md`; requirements by the delta that states them (`buyer-orchestration`,
`api-family`). The end-to-end scenario is run by validation, not on the
implementing machine.

**Dependencies.** `compose-api-family-kit`, whose buyer-side Alkahest stage this
changes, and `keep-buyer-credentials-private`, on whose branch it is stacked.

## 1. Derived Alkahest inputs and no override flags

Touches `domains/api/buying-alkahest/src/arkhai_api_buying_alkahest/` (`stage.py`,
`chains.py`), `domains/api/buying/src/arkhai_api_buying/` (`buy.py`, `stages.py`),
`domains/api/buying-arkhai-payments/src/arkhai_api_buying_arkhai_payments/stage.py`,
their tests, `domains/apicredits/buyer/tests/`,
`e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py`,
and `docs/cookbooks/vllm-apicredits-seller.md`.

- [ ] 1.1 Empty `AlkahestBuyerStage.options`; read the wallet with no
      overrides, the token and decimals from the selected escrow, and the
      escrow identity from the run (D1, D2, D4, D5). Drop `select_chain_for_listing`'s
      override and point its refusals at the listing and configuration (D3).
- [ ] 1.2 `buy`: choose the chain per listing in the session's proposal step,
      build the escrow adapters from the accepted proposal's chain at
      settlement, and scale explicit prices after selection through
      `BuySession.scale_explicit_prices(initial, maximum, matches)`, refusing
      tokens of different decimals (D3, D4; `api-family` "A buyer stage adds no
      mechanism override to a normal command"). The payments session takes the
      new signature.
- [ ] 1.3 Tests: the Alkahest library's session tests (no options, per-listing
      chain, `--yes` refusal naming candidates, scaling from the selected
      token, mixed decimals refused); the plugin's `test_negotiate_cli.py`
      (prices scaled from the chain's decimals, removed flags refused) and
      `test_settle_credentials.py` (wallet and chain from configuration and
      run); the buying library's selection tests for the new call order.
- [ ] 1.4 Migrate `test_credits_deal_buyer_cli.py` and the cookbook (D7).
- [ ] 1.5 Versions (design "Versions"), wheels, relocks of the buying
      libraries, `domains/apicredits/buyer`, `domains/apicredits/storefront`,
      and `e2e-tests`. Run `make test-api-buying`, `-alkahest`,
      `-arkhai-payments`, `make -C domains/apicredits test-buyer`,
      `make -C domains/apicredits/storefront test`; on a clean copy
      `make check-packaging`, `make check-comment-hygiene`,
      `make check-change CHANGE=derive-buyer-settlement-inputs`, and
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
      `make check-architecture-change CHANGE=derive-buyer-settlement-inputs`
      (the change owns no exception row).
- [ ] 2.8 **End-to-end pipeline.** Record the run and that `e2e_credits_deal`
      bought without `--chain`.
- [ ] 2.9 **Promotion.** Write `openspec/specs/api-family/architecture.md`'s
      note on where the buyer-side Alkahest stage derives each input (D2–D5);
      complete the record below.
- [ ] 2.10 **Documentation citations.** `make check-doc-citations
      CHANGE=derive-buyer-settlement-inputs`; then
      `openspec validate derive-buyer-settlement-inputs --strict`.
- [ ] 2.11 **Archival.** `openspec archive derive-buyer-settlement-inputs -y`,
      after `compose-api-family-kit` and `keep-buyer-credentials-private`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1, D6 — the stage contributes no override option; the flags are gone without a window | `openspec/specs/api-family/spec.md` ("A buyer stage adds no mechanism override to a normal command"); `openspec/specs/buyer-orchestration/spec.md` ("The API-credit buyer derives its Alkahest inputs") |
| D2–D5 — wallet, chain, token, decimals, and escrow identity derived; the `--yes` refusal; explicit prices scaled after selection | `openspec/specs/buyer-orchestration/spec.md` ("The API-credit buyer derives its Alkahest inputs"); `openspec/specs/api-family/architecture.md` (where the buyer-side Alkahest stage derives each input) |
| D7 — scenario and cookbook migrated | `docs/cookbooks/vllm-apicredits-seller.md`; test code |
| Deferred — a default settlement chain setting | `design.md` "Deferred" (no permanent home until a change takes it) |
