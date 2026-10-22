## Context

An API-credit deal settled through Arkhai payments runs: discover a listing advertising a payment option, select that option, negotiate a scalar amount, approve the payment, have the seller verify the receipt and issue credits. Each repaired defect stopped the run at a different point, and fixing one exposed the next (see `proposal.md`).

The work landed as three stacked pull requests before it had a change directory: #270 (scenario configuration), #271 (scenario invocation and option persistence), and #272 (buyer selection, pricing, principal, and publisher identity). This change records all three retroactively, so the design review and the rounds after it have one home.

## Goals / Non-Goals

**Goals:** a credits payment purchase negotiates from the selected option's advertised rate and settles; payment scenarios are configured explicitly and block only on an unavailable payments target.

**Non-Goals:** new settlement policy or wire fields, migration of stored listings, live payment qualification.

## Decisions

- **D1 — Shared orchestration resolves the selection to the advertised option.** When a domain hook returns a `SettlementSelection`, `core_buyer.orchestration` resolves it against the listing with `market_policy.scalar_policies.selected_settlement_artifact` and hands the resulting `SettlementOption` to negotiation and revalidation. A hook need not return a cached selected option, so every buyer entry point gets the option's rate and acceptance contract. `core_buyer` already declares `arkhai-kit-policy`.
- **D2 — The credits buy command selects before pricing.** `market credits buy` builds each match's settlement proposal first, resolves its advertised artifact, and keeps the choice on the match, so the existing price resolver prices from the selected artifact and interactive selection is not repeated during negotiation. A match whose proposal or artifact cannot be resolved is dropped before pricing.
- **D3 — The shared transport owns the buyer principal.** The credits settlement payload names only the negotiation; the transport binds and authenticates the marketplace buyer principal.
- **D4 — Publisher subjects compare as retained text.** Recovery retains registry subject IDs as text in the run context, so the authenticated refresh compares `str(publisher_id)` on both sides.
- **D5 — Listing persistence stores JSON values.** The credits storefront stores `model_dump(mode="json")` of each typed `SettlementOption`.
- **D6 — Payment scenarios share one explicit policy.** `e2e-tests/tests/e2e/roles/helpers/payments.py` reads the `PAYMENTS` settings into an `ArkhaiPaymentsConfig`, checks the target's `/health`, and serializes one named payments table; `livemode` and the authentication choice are always explicit. A blank `SERVICE_URL`, meaning no target is configured, or an unready target is a blocked skip, never an Alkahest fallback. With `SERVICE_URL` set, every other setting — service identity, dispute authority, buyer account, and the buyer and seller marketplace credentials — is required, and a missing one fails, naming it, before readiness is checked: the pipeline, which configures no target, stays a skip, while a misconfigured payments run fails deterministically. `LIVEMODE` and `DEVELOPMENT_AUTH` parse as strict booleans, since a settings value of the string `"false"` would otherwise read as true (01 F3).
- **D7 — `--max-matches` counts sellers with a usable settlement option.** `market credits buy` selects before capping, as `market vms buy` does, so a listing the buyer cannot settle with never takes one of the N tries; before selection moved, such a listing used a try and exited `no_compatible_settlement_option` without contacting its seller. Selection stops once N usable matches are found, so the capped list is unchanged but no buyer is prompted, and no wallet balance read, for a listing past it. The option's help states this meaning (01 F2).
- **D8 — An unmatched selection exits before negotiating.** When a hook's `SettlementSelection` resolves to no advertised option, `_negotiate_matches` records the attempt and exits `unadvertised_settlement_selection`, before revalidation and without contacting the seller — the neighbour of its `no_compatible_settlement_option` exit (01 F4).

## Risks / Trade-offs

- **[Listings already stored with model-valued options]** → discovery shows them without payment options until republished; no migration (non-goal).
- **[Preselection over discovered matches]** → bounded by D7: selection stops at N usable matches.
- **[Buyer selection is carried by rewriting a copy of the advertised listing]** → the credits buyer narrows `settlement_options` and `accepted_escrows` on a working copy, as the VM buyer narrows `settlement_options`; no defect follows today, since only pricing and D1's resolution read them and revalidation re-reads the registry. Representing the selection explicitly beside an unchanged listing, in kit for all three domains, is recorded as unowned work in `openspec/changes/README.md` (01 F6).
