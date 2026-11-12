## 1. Protocols, loader and packaged policies

- [ ] 1.1 `kit/settlement-runtime/src/market_settlement_runtime/terms_policy.py`: `BuyerTermsPolicy`, `BuyerTermsOffer`, `SellerTermsPolicy`, `SellerTermsOffer`, `SellerTermsReview`, `TermsPolicySelection`, `terms_policy_selection`, `load_terms_policy`, and the packaged `default`/`permissive` buyer and `default` seller factories (D1–D4, D7). Register them in `kit/settlement-runtime/pyproject.toml`; add the two groups to `docs/development/ARCHITECTURE.toml`.
- [ ] 1.2 Unit tests, `kit/settlement-runtime/tests/unit/test_terms_policy.py`: selection parsing in both forms; each loader refusal (absent, duplicate, wrong export, failing factory, settings to a packaged policy); the packaged policies registered under their names in the installed metadata; `default` equal to `default_buyer_refusals` and `permissive` empty over the refusal cases.

## 2. Buyer admission and approval

- [ ] 2.1 `market_settlement_runtime.buyer_terms`: `BuyerTermsAdmission(authority, policy)` replaces the class taking the boolean. `market_deal_lifecycle.terms`: remove `allow_missing_delivery_deadline` and the buyer deadline refusal from `validate_terms` (D5). Unit tests: a permissive policy does not admit an unaccepted authority or an invalid dispute window; a raising policy refuses.
- [ ] 2.2 `market_arkhai_payments.buyer.PaymentApproval` takes a `BuyerTermsPolicy` (D6). Unit test in `kit/arkhai-payments/tests/test_buyer.py`: a recurring option the default refuses is approved under `permissive` and refused with none; a mismatched mandate is refused under `permissive`.
- [ ] 2.3 VM buyer (`settlement_composition.py`, `buy_cli.py`, `negotiate_cli.py`, `arkhai_payments.py`) and bare-metal buyer (`settlement_composition.py`, `cli.py`, `config.py`): resolve the selection from configuration, the flag selecting `permissive` or being refused (D8); pass the policy to admission and approval; record `terms_policy` in the run log. Tests at each buyer's composition level.

## 3. Seller publication

- [ ] 3.1 VM storefront `settlement_composition.py` and bare-metal storefront `settlement_composition.py`, `runtime.py`, `config.py`: load the seller policy at startup; `default_penalty_periods` and `review` replace the constants (D7). Tests: a refusing policy withholds one option with its diagnostic and publishes the rest; `default` emits today's diagnostics.

## 4. Author documentation

- [ ] 4.1 `docs/terms-policy-authoring.md` and `kit/settlement-runtime/examples/terms_policies.py`; a unit test loads the example through `load_terms_policy` from the entry-point values the document states.

## 5. Validation

- [ ] 5.1 Suites of `kit/settlement-runtime`, `kit/deal-lifecycle`, `kit/arkhai-payments`, the VM and bare-metal buyers and storefronts; typing where configured; `make check-comment-hygiene`; `make check-packaging`; `make check-change CHANGE=install-compute-terms-policies`.
- [ ] 5.2 One compose VM end-to-end run (`PROVISIONING_MODE=mock make -C e2e-tests test-e2e-vm`), whose scenarios pass `--allow-unprotected-terms` unchanged.
- [ ] 5.3 By hand: a throwaway third-party policy package installed into the buyer's environment and selected for a purchase; frictions recorded in the pull request.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes; a finding returns the change to implementation.
- [ ] 6.2 **Import placement.** Confirm the imports this change added are at module level or have a recorded reason; one that should move returns the change to implementation.
- [ ] 6.3 **Documentation compliance.** Re-check D1–D8 against `openspec/README.md`'s placement rules.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final behaviour, evidence, deferred work and destinations.
- [ ] 6.5 **Roadmap currency.** Expected: `docs/development/ROADMAP.md`'s per-period goal speaks of "a buyer who has not changed their client's defaults"; confirm whether it should name the terms policy, and record the disposition.
- [ ] 6.6 **Campaign index currency.** Update this change's row in `openspec/changes/README.md`.
- [ ] 6.7 **Packaging.** `make check-packaging`, then `make check-architecture-change CHANGE=install-compute-terms-policies`.
- [ ] 6.8 **End-to-end pipeline.** Record the passing run, its result, and the scenarios that exercise this change (every VM and bare-metal purchase passing `--allow-unprotected-terms`).
- [ ] 6.9 **Promotion.** Write `openspec/specs/settlement-configuration/architecture.md` "Terms policies" (D1, D5, D7), `docs/development/ARCHITECTURE.md` "Kind" (D2), `docs/development/DEPLOYMENT_AND_CONFIG.md` (D3), `docs/buyer-quickstart.md` (D8), and complete the design-promotion record. `settlement-configuration` and `deal-lifecycle` `spec.md` are written by the archive in 6.11.
- [ ] 6.10 **Documentation citations.** `make check-doc-citations CHANGE=install-compute-terms-policies`, then `openspec validate install-compute-terms-policies --strict`.
- [ ] 6.11 **Archival.** `openspec archive install-compute-terms-policies -y`; point the index row at the archive; `openspec validate --specs --strict`.
