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

- [x] 1.1 Empty `AlkahestBuyerStage.options`; read the wallet with no
      overrides, the token and decimals from the selected escrow, and the
      escrow identity from the run (D1, D2, D4, D5). Drop `select_chain_for_listing`'s
      override and point its refusals at the listing and configuration (D3).
      *Done.* `options` is `()`; `wallet()` takes no overrides; the
      negotiation's decimals come from `token_decimals`, which refuses a
      native-token escrow or an unreadable token; settle reads the chain from
      the accepted proposal or run log and the escrow from `deal.escrow_uid`.
      `select_chain_for_listing` has no override and no all-chains fallback,
      and every refusal names the listing.
- [x] 1.2 `buy`: choose the chain per listing in the session's proposal step,
      build the escrow adapters from the accepted proposal's chain at
      settlement, and scale explicit prices after selection through
      `BuySession.scale_explicit_prices(initial, maximum, matches)`, refusing
      tokens of different decimals (D3, D4; `api-family` "A buyer stage adds no
      mechanism override to a normal command"). The payments session takes the
      new signature.
      *Done.* The session keeps the configured chains, chooses one in
      `propose`, and builds its escrow adapters from the accepted proposal's
      chain in `settle`; buy's `run_started` no longer records a chain, since
      none is chosen before discovery. `buy.py` scales after
      `select_settlement_for_matches`.
- [x] 1.3 Tests: the Alkahest library's session tests (no options, per-listing
      chain, `--yes` refusal naming candidates, scaling from the selected
      token, mixed decimals refused); the plugin's `test_negotiate_cli.py`
      (prices scaled from the chain's decimals, removed flags refused) and
      `test_settle_credentials.py` (wallet and chain from configuration and
      run); the buying library's selection tests for the new call order.
      *Done.* Alkahest library (`test_buy_session.py`, 18): no options,
      one-chain selection, skip, `--yes` refusal naming both chains, scaling
      from the selected token, mixed decimals and native token refused,
      adapters on the accepted chain. Plugin (`test_negotiate_cli.py`): the
      negotiation's prices scaled by the chain's decimals, `negotiate --yes`
      refusing a two-chain listing by name, every removed flag refused on
      `buy`, `negotiate`, and `settle` (18 cases), and `buy` scaling explicit
      prices from the selected listing's token. That last ordering is a
      property of the `buy` command, so it is proven there, through the
      plugin app with discovery and `run_buy` replaced, rather than by a
      buying-library unit test. `test_settle_credentials.py` asserts settle's
      chain, escrow, and address come from the run and configuration.
- [x] 1.4 Migrate `test_credits_deal_buyer_cli.py` and the cookbook (D7).
      *Done.* Both buys in the scenario drop `--chain anvil`; its buyer
      configures only `[chains.anvil]`. The cookbook's command drops it and
      says where the chain and key come from. Not run locally.
- [x] 1.5 Versions (design "Versions"), wheels, relocks of the buying
      libraries, `domains/apicredits/buyer`, `domains/apicredits/storefront`,
      and `e2e-tests`. Run `make test-api-buying`, `-alkahest`,
      `-arkhai-payments`, `make -C domains/apicredits test-buyer`,
      `make -C domains/apicredits/storefront test`; on a clean copy
      `make check-packaging`, `make check-comment-hygiene`,
      `make check-change CHANGE=derive-buyer-settlement-inputs`, and
      `make -k test`. One fresh-context compliance check of the diff.
      *Done.* `arkhai-api-buying` 0.3.0, `arkhai-api-buying-alkahest` 0.2.0,
      `arkhai-api-buying-arkhai-payments` 0.1.1 (0.1.2 after the rebase, R1), `arkhai-apicredits-buyer`
      0.8.0; six projects relocked. Suites: `test-api-buying` 40,
      `-alkahest` 18, `-arkhai-payments` 8, `test-buyer` 54, storefront 174,
      all passing. On a clean copy after the compliance fixes,
      `check-packaging` and `check-comment-hygiene` pass; `check-change`
      reports only the citations of `openspec/specs/api-family/spec.md` and
      `architecture.md`, the promotion destinations that exist once
      `compose-api-family-kit` archives. `make -k test` fails only where the
      tree is known to (IaC relay teardown ×3, VM storefront Alkahest
      toolchain ×2, release tooling's GNU make `--eval`); it ran before the
      compliance fixes, which the focused suites cover. The fresh-context
      check found no blocking defect; its coverage and consistency findings
      are fixed, and its note that one ambiguous listing ends a `--yes` buy
      is in design "Risks".

### Review round 1

The owner approved fixing the external review's findings. The section was
rebased onto `keep-buyer-credentials-private`'s review round, which took
`arkhai-api-buying-arkhai-payments` 0.1.1, so this change's bump is 0.1.2.

- [x] R1.1 **Explicit prices across mechanisms.** `buy` refuses explicit prices
      when the selected listings settle through more than one mechanism
      (`refuse_mixed_explicit_units`, D4); per-mechanism constraints were
      rejected because the core buyer's constraints carry one pair. Test:
      `test_buy_refuses_explicit_prices_across_mechanisms_of_different_units`,
      which reaches `run_buy` with (200, 300) for a payments listing on the
      reviewed commit.
- [x] R1.2 **Cookbook command.** `--service-name vllm-chat` became
      `--resource 'service_name="vllm-chat"'`. Both `market` commands the
      cookbook shows were parsed by the built plugin app: neither is refused
      as an unknown option, and the old form is.
- [x] R1.3 **Checks.** Suites: buying 59, Alkahest 18, payments 9, plugin 60,
      storefront 174. On a clean copy `check-packaging` and
      `check-comment-hygiene` pass; `check-change` reports only the two
      promotion-destination citations. A fresh-context check of the round and
      the rebase found no defect; its two notes (the deferred per-mechanism
      constraints had no recorded owner, and the refusal follows selection
      prompts) are in design "Deferred" and "Risks".

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
