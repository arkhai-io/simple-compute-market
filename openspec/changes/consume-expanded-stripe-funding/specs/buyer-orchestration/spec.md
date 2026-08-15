## ADDED Requirements

### Requirement: Buyer payer-profile utilities are direct and namespaced

The core buyer CLI MUST expose hosted payer management under `market settlement stripe payer`. Create/show/delete, owner rotate/retire, setup/status, instrument list/default/revoke/delete commands MUST use the exact released hosted client and the selected or recorded persistent marketplace signer. Only these payer operations and exact per-purchase authorization MAY call the hosted authority directly; escrow start/status/reclaim remain storefront-mediated.

The local buyer profile MUST store only authority/environment, opaque payer binding, bound canonical principal, and safe lifecycle metadata. CLI output and metadata MUST exclude Customer, PaymentMethod, mandate, bank/card detail, client secret, provider payload/identifier, and raw action URL.

#### Scenario: Buyer creates a hosted payer profile

- **WHEN** the selected marketplace signer completes the released payer create operation
- **THEN** the local profile atomically records only the opaque authority binding and safe owner state

#### Scenario: Setup requires action

- **WHEN** payer setup returns a transient hosted action
- **THEN** the CLI applies `--action open|print|fail` and stores no URL or client secret

### Requirement: Exact purchase authorization precedes storefront start

After accepted terms are durably recorded and before hosted start, the buyer MUST construct the exact authorization from accepted obligation hash, amount, currency, destination account, funding profile, marketplace operation ID, expiry, local payer binding, and user-selected interactive mode or ready instrument. The selected profile signer MUST sign through the released hosted client. Exact retry MUST return the same `funding_authorization_ref`; changed input MUST fail without starting settlement.

Only the operation-scoped authorization reference MAY be written to the run log or submitted to the storefront. The buyer MUST revalidate local payer/instrument/profile readiness immediately before authorization and MUST NOT select another profile or instrument after acceptance.

#### Scenario: Instrument was revoked after negotiation

- **WHEN** the selected saved instrument is no longer ready before authorization
- **THEN** authorization fails without starting the storefront settlement or falling back to another instrument

#### Scenario: Authorization acknowledgement is lost

- **WHEN** the buyer retries the identical accepted obligation and marketplace operation ID
- **THEN** the hosted authority returns the same safe authorization reference and storefront start retains one operation identity

### Requirement: Off-session automation is buyer-owned and obligation-exact

When the configured automation policy exactly admits authority, profile, currency, amount, aggregate window, and optional seller principal, the buyer MAY sign the current exact purchase authorization without prompting. Policy failure, missing consent/mandate, revoked binding/instrument, or hosted `requires_action` MUST use the ordinary interactive action flow. The seller, storefront, listing, and hosted authority MUST NOT broaden or override local policy.

#### Scenario: Accepted purchase is within all bounds

- **WHEN** the buyer opted in and one accepted obligation matches every policy bound and ready saved-instrument requirement
- **THEN** the buyer signs only that exact authorization and records its safe operation-scoped reference

#### Scenario: Hosted confirmation is required

- **WHEN** an automated off-session attempt returns `requires_action`
- **THEN** the same obligation and operation continue through transient confirmation without switching instrument, profile, amount, destination, or operation ID

### Requirement: Delayed bank state is resumable and provider-neutral

Fresh and resumed buyer flows MUST understand provider-neutral awaiting-payment reason/deadline/action metadata for bank instructions, ACH processing, and off-session confirmation. Run logs MUST retain only opaque settlement and authorization refs, funding profile, public state/reason/deadline, action kind/expiry, and accepted identities. Resume MUST re-fetch current state and apply the current action policy; it MUST NOT rely on a persisted URL, bank detail, or provider status.

#### Scenario: Push transfer is awaiting funds

- **WHEN** status reports safe bank-instruction action metadata but no authoritative funding
- **THEN** the buyer may present the transient action and remains pending without claiming readiness

#### Scenario: ACH resumes after restart

- **WHEN** a run restarts while ACH remains pending its availability gate
- **THEN** the buyer reuses the exact settlement/authorization/operation identities and polls current public state without creating another debit

## MODIFIED Requirements

### Requirement: Storefront-mediated hosted buyer action

After accepted terms, a VM buyer selecting `fiat.stripe.v1` MUST obtain one exact purchase authorization directly from the hosted authority, then start and poll the opaque settlement through the seller storefront. Direct hosted calls are limited to payer-profile/instrument management and exact purchase authorization; escrow creation, status, reclaim, fulfillment, and collection MUST remain mediated by the storefront. Setup, payment, confirmation, and bank-instruction actions are transient and MUST NOT enter run-log events.

#### Scenario: Buyer selects hosted Checkout

- **WHEN** explicit mechanism/profile/currency constraints select one advertised hosted option
- **THEN** the buyer records accepted terms, obtains the exact funding authorization, starts the accepted obligation by deterministic ID through the storefront, and reports ready only after the storefront confirms authoritative funding and fulfillment

### Requirement: Hosted buyer action handling

Payer setup, accepted start, and resume MAY return a transient setup, payment, confirmation, or bank-instruction action. Fresh purchase and resume MUST apply the common `--action open|print|fail` policy. The CLI MUST persist only opaque payer binding where locally authorized, operation-scoped funding authorization and settlement references, public status/reason/deadline, action type, and expiry; it MUST NOT persist or log an action URL, client secret, bank/card/payment/customer data, stable instrument ref in storefront state, provider identity, request credential, or raw service body.

#### Scenario: Hosted Checkout action is returned

- **WHEN** settlement start returns a browser redirect action and action policy is `open`
- **THEN** the CLI opens it and stores only the allowed opaque action metadata

#### Scenario: Hosted Checkout action is printed

- **WHEN** settlement start or resume returns a browser redirect action and action policy is `print`
- **THEN** the CLI displays it without opening it or writing it to the run log

#### Scenario: Buyer resumes after losing the redirect

- **WHEN** a run log contains the hosted settlement and authorization references but no URL
- **THEN** the buyer retrieves the current action/status from the storefront and applies the current action policy rather than relying on a persisted URL or creating another settlement

#### Scenario: Bank instructions are returned

- **WHEN** payer or settlement state returns transient push-transfer instructions
- **THEN** the CLI presents them according to action policy and persists only safe kind, expiry, reason, and deadline metadata

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Hosted payer lifecycle commands MUST live below `market settlement stripe payer`; direct purchase authorization is an internal accepted-run step rather than a top-level raw mutation. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism/profile inputs from the selected option, persistent buyer profile, and accepted run and MUST NOT accept chain-, token-, provider-, raw payer-ref-, or browser-specific override flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

#### Scenario: Buyer manages a saved ACH instrument

- **WHEN** the buyer invokes the Stripe payer instrument namespace
- **THEN** the released client uses the selected profile signer and returns only safe instrument metadata plus transient actions

### Requirement: No provider call before accepted terms

Discovery, filtering, preference, and proposal construction MUST use listing data plus local selected-profile readiness only. Hosted payer profile/setup/instrument management MAY occur as an explicit namespaced user command before a purchase, but exact purchase authorization, hosted escrow, and funding mutation MUST NOT occur until seller-accepted terms containing the exact settlement option/profile are durably recorded.

#### Scenario: Negotiation exits before acceptance

- **WHEN** the buyer declines, times out, or reaches a pricing limit before accepted terms
- **THEN** no purchase authorization, hosted escrow, Checkout/payment/debit, charge, transfer, refund, or settlement operation is created

#### Scenario: Buyer performs setup independently

- **WHEN** the buyer explicitly invokes a payer setup command without negotiating
- **THEN** only the payer-authorized setup lifecycle may run and no marketplace obligation or funding authorization is created
