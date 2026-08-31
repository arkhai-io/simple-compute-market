## ADDED Requirements

### Requirement: Mechanism-neutral constrained preference

Buyer orchestration MUST normalize legacy escrow entries and settlement options into immutable preference candidates only after compatibility, active chain, mechanism, asset, and other authoritative filters. Explicit `--settlement-mechanism` and `--settlement-asset` constraints MUST be applied before policy ranking; policy output MUST NOT introduce an unadvertised or incompatible choice.

#### Scenario: Buyer requests hosted fiat
- **WHEN** `--settlement-mechanism fiat.stripe.v1` and a supported asset leave several options
- **THEN** buyer policy ranks only those hosted options and exact deterministic fallback applies if it expresses no preference

#### Scenario: Buyer selects Alkahest
- **WHEN** constraints or interactive choice select an existing Alkahest escrow
- **THEN** the existing escrow creation/submission path and run-log fields remain unchanged and no hosted API is called

### Requirement: Hosted buyer action handling

After accepted terms are submitted, the buyer MAY start the accepted hosted obligation and retrieve its current action. The CLI MUST print the action and MAY open it unless `--no-browser` is set, but MUST persist only the opaque settlement reference, public status, action type, and expiry. It MUST NOT persist or log a Checkout URL, payment/customer/card data, provider identity, request credential, or raw service body.

#### Scenario: Hosted Checkout action is returned
- **WHEN** settlement start returns a browser redirect action
- **THEN** the CLI displays it, conditionally opens it, and stores only the allowed opaque action metadata

#### Scenario: Buyer resumes after losing the redirect
- **WHEN** a run log contains the hosted settlement reference but no URL
- **THEN** the buyer retrieves the current action/status from the storefront rather than relying on a persisted URL or creating another settlement

### Requirement: No provider call before accepted terms

Discovery, filtering, preference, and proposal construction MUST use listing data only. Stripe or hosted-authority mutation MUST NOT occur until seller-accepted terms containing the exact settlement selection are durably recorded.

#### Scenario: Negotiation exits before acceptance
- **WHEN** the buyer declines, times out, or reaches a pricing limit before accepted terms
- **THEN** no hosted escrow, Checkout Session, charge, account mutation, or provider operation is created
