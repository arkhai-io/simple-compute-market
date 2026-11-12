## Why

A compute buyer's stance on an option's lifecycle terms is one fixed function, `default_buyer_refusals`, and one boolean, `--allow-unprotected-terms`, that the VM and bare-metal buyers thread through their compositions; it waives the delivery deadline, the penalty and the partial-period treatment together or not at all. A seller's stance is a constant in each storefront composition. Neither party can state a policy of its own, and a buyer who wants one right waived and the others kept has no way to say so.

## What Changes

- Add a buyer terms-policy protocol and a seller terms-policy protocol to the settlement runtime kit, each resolved by name from an entry-point group and selected by a root `terms_policy` configuration key.
- Ship today's behaviours as the packaged policies: buyer `default` and `permissive`, seller `default`. With no configuration, every decision is the one made today.
- `--allow-unprotected-terms` stays, as shorthand in the VM and bare-metal buyer commands that selects the packaged `permissive` policy. No composition takes the boolean.
- The buyer's selected policy also runs at payment approval. Today approval always applies the default refusals to a recurring option, so a recurring option taken under the flag is selected and negotiated and then refused at approval; with this change approval follows the policy that selected it.
- The missing-delivery-deadline refusal moves out of term validation into the buyer policy, which already makes the same refusal first. Term validation keeps only what the codec and the authority require.
- The seller policy takes the two choices the compositions hard-code at publication: the penalty a recurring preset gets when its clause names none, and whether a derived option is published.
- The seller policy is also asked when a buyer selects an advertised option, after every other check of the round, and can refuse the selection with a reason the buyer receives as an ordinary `offer_unfulfillable` refusal or rejection.
- A buyer policy may order one listing's acceptable options; the packaged policies keep the order mechanism priority, authority preference and option identity give.
- A buyer whose terms policy refused every option it was offered is told the policy's reasons, where it was told only that no listing matched.
- Document writing and installing a policy package, with an example a test exercises.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-configuration`: adds terms-policy selection, the packaged policies, and what a policy cannot waive.
- `deal-lifecycle`: the delivery-deadline requirement names the buyer's terms policy as the owner of the refusal.

## Non-Goals

- API credits. Its buyer ranks options by dispute authority alone and never consults the compute rights refusals, so it does not share the path.
- A seller policy that alters an option, at publication or at selection. Composing options belongs to publication clauses, presets and the composition; price rounds stay with the negotiation middleware chain.
- Ordering across listings, which stays with clause order, mechanism priority and the buyer's aggregation policy. A preference orders the options of one listing.
- A second attempt on the same listing with the next preferred option when the first fails. The buyer moves to the next listing, as it does now.
- File-based policy discovery, which the negotiation middleware and aggregation policies have. A terms policy is installed.
- No wire, database or deployment change. A run log records `terms_policy` (the selected name) in place of `allow_unprotected_compute_terms`.

## Impact

`kit/settlement-runtime` (protocols, loader, packaged policies), `core/buyer` (`BuyerSettlementPolicy.option_order`), the VM and bare-metal storefronts' negotiation runtimes, `kit/deal-lifecycle` (`TermContext` loses `allow_missing_delivery_deadline`), `kit/arkhai-payments` (`PaymentApproval` takes the protocol), the VM and bare-metal buyers and storefronts, `docs/development/ARCHITECTURE.toml` (two plugin groups). `BuyerTermsPolicy` in `market_settlement_runtime.buyer_terms`, the class composing refusals with authority ranking, is renamed `BuyerTermsAdmission`; the name now belongs to the protocol.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/settlement-configuration/architecture.md`, a "Terms policies" section: where the protocols live and why.
- D2: `docs/development/ARCHITECTURE.md`, "Kind": the two groups join the plugin entry-point groups, owned by `kit/settlement-runtime`; `openspec/specs/settlement-configuration/spec.md` by the archive.
- D3: `docs/development/DEPLOYMENT_AND_CONFIG.md`, beside the dispute-authority keys: the `terms_policy` key in both forms.
- D4: `openspec/specs/settlement-configuration/spec.md` by the archive; `docs/terms-policy-authoring.md` (written with the code, since the example test reads it).
- D5: `openspec/specs/settlement-configuration/architecture.md`, "Terms policies": the line between a policy's decision and the checks it cannot waive.
- D6: `openspec/specs/settlement-configuration/spec.md` by the archive.
- D7: `openspec/specs/settlement-configuration/architecture.md`, "Terms policies": where a seller's term choices are made and why the seam is at publication.
- D8: `docs/buyer-quickstart.md`: the flag as shorthand for the `permissive` policy.
- D9: `openspec/specs/settlement-configuration/architecture.md`, "Terms policies": where selection is admitted and how the refusal is carried; `openspec/specs/settlement-configuration/spec.md` by the archive.
- D10: `openspec/specs/settlement-configuration/architecture.md`, "Terms policies": what a preference orders and what it does not; `spec.md` by the archive.
- D11: `openspec/specs/settlement-configuration/spec.md` by the archive.
