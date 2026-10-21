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
- **D6 — Payment scenarios share one explicit policy.** `e2e-tests/tests/e2e/roles/helpers/payments.py` reads the `PAYMENTS` settings into an `ArkhaiPaymentsConfig`, checks the target's `/health`, and serializes one named payments table; `livemode` and the authentication choice are always explicit. A missing or unready payments target is a blocked skip, never an Alkahest fallback.

## Risks / Trade-offs

- **[Listings already stored with model-valued options]** → discovery shows them without payment options until republished; no migration (non-goal).
- **[Preselection runs over every discovered match]** → under the design review's triage (01 F2).
