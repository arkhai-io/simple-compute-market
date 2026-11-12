## Why

A compute buyer's stance on an option's lifecycle terms is one fixed function, `default_buyer_refusals`, and one boolean, `--allow-unprotected-terms`, that the VM and bare-metal buyers thread through their compositions; it waives the delivery deadline, the penalty and the partial-period treatment together or not at all. A seller's stance is a constant in each storefront composition. Neither party can state a policy of its own, and a buyer who wants one right waived and the others kept has no way to say so.

## What Changes

- Add a buyer terms-policy protocol and a seller terms-policy protocol to the settlement runtime kit, each resolved by name from an entry-point group and selected by a root `terms_policy` configuration key.
- Ship today's behaviours as the packaged policies: buyer `default` and `permissive`, seller `default`. With no configuration, every decision is the one made today.
- `--allow-unprotected-terms` stays, as shorthand in the VM and bare-metal buyer commands that selects the packaged `permissive` policy. No composition takes the boolean.
- The buyer's selected policy also runs at payment approval. Today approval always applies the default refusals to a recurring option, so a recurring option taken under the flag is selected and negotiated and then refused at approval; with this change approval follows the policy that selected it.
- The missing-delivery-deadline refusal moves out of term validation into the buyer policy, which already makes the same refusal first. Term validation keeps only what the codec and the authority require.
- The seller policy takes the two choices the compositions hard-code at publication: the penalty a recurring preset gets when its clause names none, and whether a derived option is published.
- Document writing and installing a policy package, with an example a test exercises.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-configuration`: adds terms-policy selection, the packaged policies, and what a policy cannot waive.
- `deal-lifecycle`: the delivery-deadline requirement names the buyer's terms policy as the owner of the refusal.

## Non-Goals

- API credits. Its buyer ranks options by dispute authority alone and never consults the compute rights refusals, so it does not share the path.
- A seller decision at negotiation time. A buyer selects an advertised option by its identity and cannot counter its lifecycle terms, so the seller has no term decision to make there; its price rounds stay with the negotiation middleware chain.
- Policy-supplied ordering among acceptable options. A buyer policy refuses or does not; order stays with mechanism priority and dispute-authority preference.
- File-based policy discovery, which the negotiation middleware and aggregation policies have. A terms policy is installed.
- No wire, database or deployment change. A run log records `terms_policy` (the selected name) in place of `allow_unprotected_compute_terms`.

## Impact

`kit/settlement-runtime` (protocols, loader, packaged policies), `kit/deal-lifecycle` (`TermContext` loses `allow_missing_delivery_deadline`), `kit/arkhai-payments` (`PaymentApproval` takes the protocol), the VM and bare-metal buyers and storefronts, `docs/development/ARCHITECTURE.toml` (two plugin groups). `BuyerTermsPolicy` in `market_settlement_runtime.buyer_terms`, the class composing refusals with authority ranking, is renamed `BuyerTermsAdmission`; the name now belongs to the protocol.

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
